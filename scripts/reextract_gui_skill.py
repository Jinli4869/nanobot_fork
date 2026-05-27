from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import litellm
import numpy as np
import yaml

from nanobot.agent.gui_adapter import NanobotEmbeddingAdapter, NanobotLLMAdapter
from nanobot.config.loader import load_config, resolve_config_env_vars
from nanobot.providers.factory import build_gui_provider_snapshot
from opengui.cli import OpenAICompatibleEmbeddingProvider, OpenAICompatibleLLMProvider
from opengui.postprocessing import EvaluationConfig, PostRunProcessor


DEFAULT_NANOBOT_CONFIG = Path.home() / ".nanobot" / "config.json"
DEFAULT_OPENGUI_CONFIG = Path.home() / ".opengui" / "config.yaml"
POSTPROCESSING_LOGS = (
    "extraction_result.json",
    "extraction_usage.json",
    "evolution_result.json",
)


class NoSummaryPostRunProcessor(PostRunProcessor):
    async def _summarize_trajectory(self, trace_path: Path) -> str:
        return ""


@dataclass(frozen=True)
class ProviderBundle:
    llm: Any
    embedding_provider: Any | None
    embedding_signature: str | None
    skill_store_root: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-run OpenGUI post-run skill extraction for an existing trace.",
    )
    parser.add_argument(
        "trace_or_run_dir",
        type=Path,
        help="Trace JSONL path or a gui_runs run directory containing trace_*.jsonl.",
    )
    parser.add_argument(
        "--config-source",
        choices=("nanobot", "opengui"),
        default="nanobot",
        help="Provider config source. Defaults to ~/.nanobot/config.json.",
    )
    parser.add_argument(
        "--nanobot-config",
        type=Path,
        default=DEFAULT_NANOBOT_CONFIG,
        help="nanobot config path when --config-source=nanobot.",
    )
    parser.add_argument(
        "--opengui-config",
        type=Path,
        default=DEFAULT_OPENGUI_CONFIG,
        help="OpenGUI YAML config path when --config-source=opengui.",
    )
    parser.add_argument(
        "--skill-store-root",
        type=Path,
        default=None,
        help="Override skill store root. Defaults to nanobot gui_skills or OpenGUI skills_dir.",
    )
    parser.add_argument(
        "--task",
        default=None,
        help="Override task/instruction. Defaults to metadata or attempt_start task in trace.",
    )
    parser.add_argument(
        "--platform",
        default=None,
        help="Override platform. Defaults to metadata platform in trace.",
    )
    parser.add_argument(
        "--success",
        choices=("auto", "true", "false"),
        default="auto",
        help="Extraction success mode. auto uses the final result event.",
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Run only ordinary flat skill extraction, skipping failed-skill evolution.",
    )
    parser.add_argument(
        "--keep-logs",
        action="store_true",
        help="Do not delete existing extraction/evolution log files before rerun.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve inputs and print what would run without calling the LLM or writing files.",
    )
    return parser.parse_args()


def resolve_trace_path(value: Path) -> Path:
    path = value.expanduser()
    if path.is_file():
        return path
    if not path.is_dir():
        raise FileNotFoundError(f"Trace path or run directory not found: {path}")

    candidates = sorted(path.glob("trace_*.jsonl"))
    if not candidates:
        candidates = sorted(path.glob("trace.jsonl"))
    if not candidates:
        candidates = sorted(path.glob("*/trace.jsonl"))
    if not candidates:
        raise FileNotFoundError(f"No trace JSONL found under run directory: {path}")
    if len(candidates) > 1:
        top_level = [candidate for candidate in candidates if candidate.parent == path]
        if len(top_level) == 1:
            return top_level[0]
        names = "\n".join(f"- {candidate}" for candidate in candidates)
        raise ValueError(f"Multiple trace files found; pass one explicitly:\n{names}")
    return candidates[0]


def read_trace_metadata(trace_path: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    last_result: dict[str, Any] | None = None
    last_attempt_result: dict[str, Any] | None = None
    with trace_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_type = event.get("type") or event.get("event")
            if event_type == "metadata":
                metadata.update({
                    "task": event.get("task") or metadata.get("task"),
                    "platform": event.get("platform") or metadata.get("platform"),
                })
            elif event_type == "attempt_start" and not metadata.get("task"):
                metadata["task"] = event.get("task")
            elif event_type == "step" and not metadata.get("platform"):
                observation = event.get("observation")
                if not isinstance(observation, dict):
                    prompt = event.get("prompt")
                    observation = prompt.get("current_observation") if isinstance(prompt, dict) else None
                if isinstance(observation, dict) and observation.get("platform"):
                    metadata["platform"] = observation.get("platform")
            elif event_type == "attempt_result":
                last_attempt_result = event
            elif event_type == "result":
                last_result = event

    if last_attempt_result is not None and isinstance(last_attempt_result.get("success"), bool):
        metadata["success"] = bool(last_attempt_result.get("success"))
    elif last_result is not None:
        metadata["success"] = bool(last_result.get("success"))
    return metadata


def bool_from_success(value: str, metadata: dict[str, Any]) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    if "success" not in metadata:
        raise ValueError("Could not infer success from trace; pass --success true or --success false.")
    return bool(metadata["success"])


def load_provider_bundle(args: argparse.Namespace) -> ProviderBundle:
    if args.config_source == "opengui":
        return load_opengui_provider_bundle(args.opengui_config.expanduser(), args.skill_store_root)
    return load_nanobot_provider_bundle(args.nanobot_config.expanduser(), args.skill_store_root)


def load_opengui_provider_bundle(
    config_path: Path,
    skill_store_root: Path | None,
) -> ProviderBundle:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    provider = _require_mapping(raw.get("provider"), "provider")
    base_url = _require_string(provider.get("base_url"), "provider.base_url")
    model = _require_string(provider.get("model"), "provider.model")
    api_key = str(provider.get("api_key") or os.getenv("OPENAI_API_KEY") or "")
    llm = OpenAICompatibleLLMProvider(base_url=base_url, model=model, api_key=api_key)

    embedding_provider = None
    embedding_signature = None
    embedding = raw.get("embedding")
    if isinstance(embedding, dict):
        emb_base_url = str(embedding.get("base_url") or base_url)
        emb_model = str(embedding.get("model") or "")
        emb_api_key = str(embedding.get("api_key") or api_key)
        if emb_base_url and emb_model and emb_api_key:
            embedding_provider = OpenAICompatibleEmbeddingProvider(
                base_url=emb_base_url,
                model=emb_model,
                api_key=emb_api_key,
            )
            embedding_signature = f"OpenAICompatibleEmbeddingProvider|{emb_base_url}|{emb_model}"

    store_root = (
        skill_store_root
        or Path(str(raw.get("skills_dir") or (Path.home() / ".opengui" / "skills")))
    )
    return ProviderBundle(
        llm=llm,
        embedding_provider=embedding_provider,
        embedding_signature=embedding_signature,
        skill_store_root=store_root.expanduser(),
    )


def load_nanobot_provider_bundle(
    config_path: Path,
    skill_store_root: Path | None,
) -> ProviderBundle:
    config = resolve_config_env_vars(load_config(config_path))
    if config.gui is None:
        raise ValueError("nanobot config has no gui section")
    snapshot = build_gui_provider_snapshot(config)
    if snapshot is None:
        raise ValueError("Could not build GUI provider from nanobot config")

    llm = NanobotLLMAdapter(snapshot.provider, snapshot.model, capture_ttft=False)
    embedding_provider = None
    embedding_signature = None

    workspace = Path(config.agents.defaults.workspace).expanduser()
    store_root = (
        skill_store_root
        or workspace / "gui_skills"
    ).expanduser()
    if config.gui.embedding_model:
        resolved_model = _resolve_nanobot_embedding_model(
            snapshot.provider,
            config.gui.embedding_model,
            config.gui.provider,
        )
        embedding_provider = _build_nanobot_embedding_adapter(snapshot.provider, resolved_model)
        embedding_signature = _nanobot_embedding_signature(snapshot.provider, resolved_model, config.gui.provider)

    return ProviderBundle(
        llm=llm,
        embedding_provider=embedding_provider,
        embedding_signature=embedding_signature,
        skill_store_root=store_root,
    )


def _build_nanobot_embedding_adapter(provider: Any, resolved_model: str) -> NanobotEmbeddingAdapter:
    direct_client = getattr(provider, "_client", None)
    if direct_client is not None and hasattr(direct_client, "embeddings"):
        direct_model = _normalize_direct_embedding_model(resolved_model)

        async def _embed_direct(texts: list[str]) -> np.ndarray:
            async def _request_batch(batch: list[str]) -> list[list[float]]:
                response = await direct_client.embeddings.create(
                    model=direct_model,
                    input=batch,
                )
                return [item.embedding for item in response.data]

            return await _embed_texts_in_batches(texts, _request_batch)

        return NanobotEmbeddingAdapter(_embed_direct)

    async def _embed(texts: list[str]) -> np.ndarray:
        async def _request_batch(batch: list[str]) -> list[list[float]]:
            kwargs: dict[str, Any] = {
                "model": resolved_model,
                "input": batch,
                "encoding_format": "float",
            }
            api_key = getattr(provider, "api_key", None)
            if api_key:
                kwargs["api_key"] = api_key
            api_base = getattr(provider, "api_base", None)
            if api_base:
                kwargs["api_base"] = api_base
            extra_headers = getattr(provider, "extra_headers", None)
            if extra_headers:
                kwargs["extra_headers"] = extra_headers

            response = await litellm.aembedding(**kwargs)
            vectors: list[list[float]] = []
            for item in response.data:
                embedding = item.get("embedding") if isinstance(item, dict) else getattr(item, "embedding", None)
                if embedding is None:
                    raise ValueError("Embedding response item missing 'embedding' field")
                vectors.append(embedding)
            return vectors

        return await _embed_texts_in_batches(texts, _request_batch)

    return NanobotEmbeddingAdapter(_embed)


def _resolve_nanobot_embedding_model(provider: Any, embedding_model: str, provider_name: str | None) -> str:
    resolve = getattr(provider, "_resolve_model", None)
    resolved = resolve(embedding_model) if callable(resolve) else embedding_model
    if (
        isinstance(resolved, str)
        and "/" not in resolved
        and (provider_name or "").strip().lower() == "dashscope"
    ):
        return f"openai/{resolved}"
    return str(resolved)


def _nanobot_embedding_signature(provider: Any, resolved_model: str, provider_name: str | None) -> str:
    direct_client = getattr(provider, "_client", None)
    signature_model = (
        _normalize_direct_embedding_model(resolved_model)
        if direct_client is not None and hasattr(direct_client, "embeddings")
        else resolved_model
    )
    gateway = getattr(provider, "_gateway", None)
    signature_provider = (
        getattr(gateway, "name", None)
        or getattr(gateway, "litellm_prefix", None)
        or provider.__class__.__name__
    )
    api_base = getattr(provider, "api_base", None) or getattr(provider, "_api_base", None)
    if not api_base:
        api_base = _default_embedding_api_base(provider_name, resolved_model)
    parts = [str(signature_provider)]
    if api_base:
        parts.append(str(api_base))
    parts.append(signature_model)
    return "|".join(parts)


def _default_embedding_api_base(provider_name: str | None, resolved_model: str) -> str | None:
    if (provider_name or "").strip().lower() == "dashscope" and resolved_model.startswith("openai/"):
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"
    return None


async def _embed_texts_in_batches(
    texts: list[str],
    request_batch: Any,
) -> np.ndarray:
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)

    vectors: list[list[float]] = []
    for start in range(0, len(texts), 10):
        batch = texts[start:start + 10]
        vectors.extend(await request_batch(batch))
    return np.array(vectors, dtype=np.float32)


def _normalize_direct_embedding_model(model: str) -> str:
    if "/" not in model:
        return model
    return model.split("/", 1)[1]


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Missing mapping: {name}")
    return value


def _require_string(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Missing value: {name}")
    return text


def remove_previous_logs(trace_path: Path) -> list[Path]:
    removed: list[Path] = []
    for name in POSTPROCESSING_LOGS:
        path = trace_path.parent / name
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


async def run(args: argparse.Namespace) -> int:
    trace_path = resolve_trace_path(args.trace_or_run_dir).resolve()
    metadata = read_trace_metadata(trace_path)
    task = args.task or metadata.get("task")
    if not task:
        raise ValueError("Could not infer task from trace; pass --task.")
    platform = args.platform or metadata.get("platform") or "android"
    is_success = bool_from_success(args.success, metadata)
    bundle = load_provider_bundle(args)

    print(f"trace: {trace_path}")
    print(f"task: {task}")
    print(f"platform: {platform}")
    print(f"is_success: {is_success}")
    print(f"skill_store_root: {bundle.skill_store_root}")
    print(f"embedding: {'enabled' if bundle.embedding_provider is not None else 'disabled'}")
    if args.dry_run:
        logs = [trace_path.parent / name for name in POSTPROCESSING_LOGS]
        print("dry_run: true")
        print("would_overwrite:")
        for path in logs:
            print(f"  - {path}")
        return 0

    if not args.keep_logs:
        removed = remove_previous_logs(trace_path)
        if removed:
            print("removed_previous_logs:")
            for path in removed:
                print(f"  - {path}")

    processor = NoSummaryPostRunProcessor(
        llm=bundle.llm,
        merge_llm=bundle.llm,
        embedding_provider=bundle.embedding_provider,
        embedding_signature=bundle.embedding_signature,
        skill_store_root=bundle.skill_store_root,
        enable_skill_extraction=True,
        evaluation=EvaluationConfig(enabled=False),
    )
    if args.extract_only:
        await processor._extract_skill(
            trace_path,
            is_success,
            str(platform),
            task=str(task),
            evaluation_result=None,
            agent_success=is_success,
        )
    else:
        await processor._run_all(
            trace_path,
            is_success=is_success,
            platform=str(platform),
            task=str(task),
        )

    result_path = trace_path.parent / "extraction_result.json"
    usage_path = trace_path.parent / "extraction_usage.json"
    print(f"extraction_result: {result_path}")
    if result_path.exists():
        result = json.loads(result_path.read_text(encoding="utf-8"))
        print(f"status: {result.get('status')}")
        print(f"updated_functions: {result.get('updated_functions')}")
        print(f"compiled_skill_ids: {result.get('compiled_skill_ids')}")
    if usage_path.exists():
        print(f"extraction_usage: {usage_path}")
    return 0


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
