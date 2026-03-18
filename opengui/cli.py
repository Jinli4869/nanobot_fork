"""Standalone CLI for driving OpenGUI without nanobot runtime imports."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import json_repair
import numpy as np
import yaml
from openai import AsyncOpenAI

from opengui.agent import AgentResult, GuiAgent
from opengui.backends.adb import AdbBackend
from opengui.backends.dry_run import DryRunBackend
from opengui.interfaces import LLMResponse, ToolCall
from opengui.memory.retrieval import MemoryRetriever
from opengui.memory.store import MemoryStore
from opengui.skills.executor import LLMStateValidator, SkillExecutor
from opengui.skills.library import SkillLibrary
from opengui.trajectory.recorder import TrajectoryRecorder

LocalDesktopBackend = None


DEFAULT_CONFIG_PATH = Path.home() / ".opengui" / "config.yaml"
DEFAULT_MEMORY_DIR = Path.home() / ".opengui" / "memory"
DEFAULT_SKILLS_DIR = Path.home() / ".opengui" / "skills"
DEFAULT_RUNS_DIR = Path("opengui_runs")


@dataclass(slots=True)
class ProviderConfig:
    base_url: str
    model: str
    api_key: str | None = None


@dataclass(slots=True)
class EmbeddingConfig:
    base_url: str
    model: str
    api_key: str | None = None


@dataclass(slots=True)
class AdbConfig:
    serial: str | None = None
    adb_path: str = "adb"


@dataclass(slots=True)
class CliConfig:
    provider: ProviderConfig
    embedding: EmbeddingConfig | None = None
    adb: AdbConfig = field(default_factory=AdbConfig)
    max_steps: int = 15
    memory_dir: Path | None = None
    skills_dir: Path | None = None


class OpenAICompatibleLLMProvider:
    """OpenAI-compatible chat bridge that satisfies opengui's LLM protocol."""

    def __init__(self, *, base_url: str, model: str, api_key: str | None = None) -> None:
        self._model = model
        self._client = AsyncOpenAI(
            api_key=api_key or "no-key",
            base_url=base_url,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": _sanitize_messages(messages),
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"

        response = await self._client.chat.completions.create(**kwargs)
        if not response.choices:
            raise RuntimeError("OpenAI-compatible API returned no choices")

        choice = response.choices[0]
        message = choice.message
        parsed_tool_calls: list[ToolCall] = []
        for index, tool_call in enumerate(message.tool_calls or []):
            parsed_tool_calls.append(
                ToolCall(
                    id=tool_call.id or f"tool-call-{index}",
                    name=tool_call.function.name,
                    arguments=_parse_tool_arguments(tool_call.function.arguments),
                )
            )

        return LLMResponse(
            content=_coerce_message_content(message.content),
            tool_calls=parsed_tool_calls or None,
            raw=response,
        )


class OpenAICompatibleEmbeddingProvider:
    """OpenAI-compatible embedding bridge for optional memory and skill search."""

    def __init__(self, *, base_url: str, model: str, api_key: str | None = None) -> None:
        self._model = model
        self._client = AsyncOpenAI(
            api_key=api_key or "no-key",
            base_url=base_url,
        )

    async def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)

        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
        )
        vectors = [item.embedding for item in response.data]
        return np.array(vectors, dtype=np.float32)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m opengui.cli")
    parser.add_argument("task_input", nargs="?", help="Task description")
    parser.add_argument("--task", dest="task_flag", help="Task description")
    parser.add_argument(
        "--backend",
        choices=("adb", "local", "dry-run"),
        default="local",
        help="Execution backend",
    )
    parser.add_argument("--dry-run", action="store_true", help="Shortcut for --backend dry-run")
    parser.add_argument("--json", dest="json_output", action="store_true", help="Emit JSON output")
    parser.add_argument("--config", type=Path, help="Config file path")

    args = parser.parse_args(argv)
    if not args.task_input and not args.task_flag:
        parser.error("task is required via positional input or --task")
    return args


def resolve_task(args: argparse.Namespace) -> str:
    task_flag = (args.task_flag or "").strip()
    task_input = (args.task_input or "").strip()
    if task_flag and task_input and task_flag != task_input:
        raise ValueError("Positional task and --task disagree")
    task = task_flag or task_input
    if not task:
        raise ValueError("Task is required")
    return task


def resolve_backend_name(args: argparse.Namespace) -> str:
    return "dry-run" if args.dry_run else args.backend


def load_config(path: Path | None = None) -> CliConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ValueError("Config root must be a mapping")

    provider_raw = _require_mapping(raw, "provider")
    provider_api_key = _optional_string(provider_raw, "api_key") or os.getenv("OPENAI_API_KEY")
    provider = ProviderConfig(
        base_url=_require_string(provider_raw, "base_url"),
        model=_require_string(provider_raw, "model"),
        api_key=provider_api_key,
    )

    embedding_raw = raw.get("embedding")
    embedding: EmbeddingConfig | None = None
    if embedding_raw is not None:
        if not isinstance(embedding_raw, dict):
            raise ValueError("embedding config must be a mapping")
        embedding = EmbeddingConfig(
            base_url=_require_string(embedding_raw, "base_url"),
            model=_require_string(embedding_raw, "model"),
            api_key=_optional_string(embedding_raw, "api_key") or provider_api_key,
        )

    adb_raw = raw.get("adb") or {}
    if not isinstance(adb_raw, dict):
        raise ValueError("adb config must be a mapping")
    adb = AdbConfig(
        serial=_optional_string(adb_raw, "serial"),
        adb_path=_optional_string(adb_raw, "adb_path") or "adb",
    )

    return CliConfig(
        provider=provider,
        embedding=embedding,
        adb=adb,
        max_steps=_coerce_positive_int(raw.get("max_steps"), default=15),
        memory_dir=_optional_path(raw.get("memory_dir")),
        skills_dir=_optional_path(raw.get("skills_dir")),
    )


def build_backend(name: str, config: CliConfig) -> Any:
    if name == "adb":
        return AdbBackend(serial=config.adb.serial, adb_path=config.adb.adb_path or "adb")
    if name == "local":
        desktop_backend_cls = LocalDesktopBackend
        if desktop_backend_cls is None:
            from opengui.backends.desktop import LocalDesktopBackend as desktop_backend_cls
        return desktop_backend_cls()
    if name == "dry-run":
        return DryRunBackend()
    raise ValueError(f"Unsupported backend: {name}")


async def build_optional_components(
    config: CliConfig,
    *,
    provider: OpenAICompatibleLLMProvider,
    backend: Any,
) -> tuple[Any | None, Any | None, Any | None]:
    if config.embedding is None:
        return None, None, None

    embedding_provider = OpenAICompatibleEmbeddingProvider(
        base_url=config.embedding.base_url,
        model=config.embedding.model,
        api_key=config.embedding.api_key,
    )
    memory_store = MemoryStore(config.memory_dir or DEFAULT_MEMORY_DIR)
    memory_retriever = MemoryRetriever(embedding_provider=embedding_provider, top_k=5)
    await memory_retriever.index(memory_store.list_all())

    skill_library = SkillLibrary(
        store_dir=config.skills_dir or DEFAULT_SKILLS_DIR,
        embedding_provider=embedding_provider,
        merge_llm=provider,
    )
    skill_executor = SkillExecutor(
        backend=backend,
        state_validator=LLMStateValidator(provider),
    )
    return memory_retriever, skill_library, skill_executor


async def run_cli(args: argparse.Namespace) -> AgentResult:
    task = resolve_task(args)
    config = load_config(args.config)
    backend = build_backend(resolve_backend_name(args), config)
    provider = OpenAICompatibleLLMProvider(
        base_url=config.provider.base_url,
        model=config.provider.model,
        api_key=config.provider.api_key,
    )
    memory_retriever, skill_library, skill_executor = await build_optional_components(
        config,
        provider=provider,
        backend=backend,
    )

    run_root = DEFAULT_RUNS_DIR / datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S_%f")
    recorder = TrajectoryRecorder(output_dir=run_root, task=task, platform=backend.platform)
    agent = GuiAgent(
        llm=provider,
        backend=backend,
        trajectory_recorder=recorder,
        model=config.provider.model,
        artifacts_root=run_root,
        max_steps=config.max_steps or 15,
        progress_callback=_make_progress_printer(json_output=args.json_output),
        memory_retriever=memory_retriever,
        skill_library=skill_library,
        skill_executor=skill_executor,
    )
    return await agent.run(task)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = asyncio.run(run_cli(args))
    except Exception as exc:
        result = AgentResult(
            success=False,
            summary="CLI execution failed.",
            trace_path=None,
            steps_taken=0,
            error=f"{type(exc).__name__}: {exc}",
        )

    if args.json_output:
        print(json.dumps(asdict(result)))
    else:
        _print_human_result(result)
    return 0 if result.success else 1


def _print_human_result(result: AgentResult) -> None:
    print(f"success: {'true' if result.success else 'false'}")
    print(f"summary: {result.summary}")
    print(f"trace_path: {result.trace_path}")
    print(f"steps_taken: {result.steps_taken}")
    if result.error is not None:
        print(f"error: {result.error}")


def _make_progress_printer(*, json_output: bool) -> Any:
    async def _progress(message: str) -> None:
        print(message, file=sys.stderr if json_output else sys.stdout)

    return _progress


def _sanitize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for message in messages:
        normalized = dict(message)
        if normalized.get("content") is None:
            normalized["content"] = ""
        sanitized.append(normalized)
    return sanitized


def _coerce_message_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif hasattr(item, "text"):
                parts.append(str(item.text))
        return "".join(parts)
    return str(content)


def _parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    if arguments is None:
        return {}
    if isinstance(arguments, str):
        if not arguments.strip():
            return {}
        parsed = json_repair.loads(arguments)
    else:
        parsed = arguments
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


def _require_mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} config must be a mapping")
    return value


def _require_string(raw: dict[str, Any], key: str) -> str:
    value = _optional_string(raw, key)
    if not value:
        raise ValueError(f"Missing required config key: {key}")
    return value


def _optional_string(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_path(value: Any) -> Path | None:
    if value in (None, ""):
        return None
    return Path(str(value))


def _coerce_positive_int(value: Any, *, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected positive integer, got {value!r}") from exc
    return parsed if parsed > 0 else default


if __name__ == "__main__":
    raise SystemExit(main())
