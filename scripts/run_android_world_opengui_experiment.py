from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from android_env import loader
from android_env.components import config_classes
from android_world import constants
from android_world import registry
from android_world import suite_utils
from android_world.env import android_world_controller
from android_world.env import env_launcher
from android_world.env import interface
from opengui.agent import (
    GuiAgent,
    _AgentActionGrounder,
    _AgentScreenshotProvider,
    _AgentSubgoalRunner,
)
from opengui.backends.adb import AdbBackend
from opengui.cli import OpenAICompatibleEmbeddingProvider, OpenAICompatibleLLMProvider
from opengui.postprocessing import EvaluationConfig, PostRunProcessor
from opengui.skills.code_first import CodeSkillLibrary
from opengui.skills.executor import LLMStateValidator, SkillExecutor
from opengui.skills.graph import GraphSessionCursor
from opengui.skills.reuser import SkillReuser
from opengui.trajectory.recorder import TrajectoryRecorder


ANDROID_WORLD_ROOT = Path("/Users/jinli/Documents/Project/android_world_v3.5")
DEFAULT_EXPERIMENT_ROOT = Path.home() / ".nanobot" / "experiment" / "android_world"
DEFAULT_CONFIG = Path.home() / ".opengui" / "config.yaml"
DEFAULT_TASK_SEED = 30
DEFAULT_MAX_STEPS = 15
DEFAULT_AGENT_MODEL = "qwen3.5-35b-a3b"
DEFAULT_EXTRACT_MODEL = "qwen3.5-397b-a17b"
DEFAULT_REUSER_MODEL = "qwen3.5-35b-a3b"
DEFAULT_AGENT_PROFILE = "general_e2e"
DEFAULT_TASK_COUNT = 20
DEFAULT_ADB = Path.home() / "Library" / "Android" / "sdk" / "platform-tools" / "adb"
DEFAULT_ADB_SERVER_PORT = 5038
DEFAULT_SKIP_TASKS = frozenset({
    "AudioRecorderRecordAudio",
    "AudioRecorderRecordAudioWithFileName",
})


class NoSummaryPostRunProcessor(PostRunProcessor):
    async def _summarize_trajectory(self, trace_path: Path) -> str:
        return ""


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    return payload


def _provider_config(config_path: Path) -> tuple[str, str]:
    config = _load_yaml(config_path)
    provider = config.get("provider")
    if not isinstance(provider, dict):
        raise ValueError(f"Missing provider config in {config_path}")
    base_url = str(provider.get("base_url") or "").strip()
    api_key = str(provider.get("api_key") or os.getenv("OPENAI_API_KEY") or "").strip()
    if not base_url:
        raise ValueError(f"Missing provider.base_url in {config_path}")
    if not api_key:
        raise ValueError(f"Missing provider.api_key in {config_path}")
    return base_url, api_key


def _embedding_config(config_path: Path) -> tuple[str, str, str] | None:
    config = _load_yaml(config_path)
    provider = config.get("provider") if isinstance(config.get("provider"), dict) else {}
    embedding = config.get("embedding")
    if not isinstance(embedding, dict):
        return None
    base_url = str(embedding.get("base_url") or provider.get("base_url") or "").strip()
    model = str(embedding.get("model") or "").strip()
    api_key = str(embedding.get("api_key") or provider.get("api_key") or os.getenv("OPENAI_API_KEY") or "").strip()
    if not base_url or not model or not api_key:
        return None
    return base_url, model, api_key


def _resolve_adb_path(value: str | None) -> str:
    if value:
        return value
    if DEFAULT_ADB.is_file():
        return str(DEFAULT_ADB)
    found = shutil.which("adb")
    if found:
        return found
    raise FileNotFoundError("adb not found")


def _default_tasks(count: int) -> list[str]:
    metadata_path = ANDROID_WORLD_ROOT / "android_world" / "task_metadata.json"
    with metadata_path.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    tasks: list[str] = []
    for item in metadata:
        tags = {str(tag) for tag in item.get("tags", []) if tag}
        if item["task_name"] in DEFAULT_SKIP_TASKS:
            continue
        if item.get("difficulty") != "easy" or "requires_setup" in tags:
            continue
        tasks.append(str(item["task_name"]))
        if len(tasks) >= count:
            break
    return tasks


def _load_and_setup_env(
    *,
    console_port: int,
    adb_path: str,
    grpc_port: int,
    adb_server_port: int,
) -> interface.AsyncEnv:
    config = config_classes.AndroidEnvConfig(
        task=config_classes.FilesystemTaskConfig(
            path=android_world_controller._write_default_task_proto()
        ),
        simulator=config_classes.EmulatorConfig(
            emulator_launcher=config_classes.EmulatorLauncherConfig(
                emulator_console_port=console_port,
                adb_port=console_port + 1,
                grpc_port=grpc_port,
            ),
            adb_controller=config_classes.AdbControllerConfig(
                adb_path=adb_path,
                adb_server_port=adb_server_port,
            ),
        ),
    )
    android_env_instance = loader.load(config)
    controller = android_world_controller.AndroidWorldController(android_env_instance)
    env = interface.AsyncAndroidEnv(controller)
    env_launcher.setup_env(env, emulator_setup=False, freeze_datetime=True)
    return env


def _make_suite(task_names: list[str], seed: int, env: Any) -> suite_utils.Suite:
    task_registry = registry.TaskRegistry()
    aw_registry = task_registry.get_registry(task_registry.ANDROID_WORLD_FAMILY)
    suite = suite_utils.create_suite(
        aw_registry,
        n_task_combinations=1,
        seed=seed,
        tasks=task_names,
        use_identical_params=False,
        env=env,
    )
    suite.suite_family = task_registry.ANDROID_WORLD_FAMILY
    return suite


def _iter_suite_instances(suite: suite_utils.Suite) -> list[Any]:
    instances: list[Any] = []
    for _, task_instances in suite.items():
        instances.extend(task_instances)
    return instances


def _sum_usage(usage: dict[str, Any] | None, into: dict[str, int]) -> None:
    if not isinstance(usage, dict):
        return
    for key, value in usage.items():
        try:
            into[key] = into.get(key, 0) + int(value or 0)
        except (TypeError, ValueError):
            continue


def _trace_metrics(trace_path: Path | None) -> dict[str, Any]:
    metrics = {
        "step_count": 0,
        "agent_step_count": 0,
        "skill_step_count": 0,
        "token_usage": {},
        "duration_sum_s": 0.0,
        "latency_per_step_s": 0.0,
    }
    if trace_path is None or not trace_path.exists():
        return metrics
    total_usage: dict[str, int] = {}
    duration_sum = 0.0
    step_count = 0
    agent_steps = 0
    skill_steps = 0
    with trace_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            if not raw_line.strip():
                continue
            event = json.loads(raw_line)
            if event.get("type") != "step":
                continue
            step_count += 1
            phase = event.get("phase")
            if phase == "skill":
                skill_steps += 1
            elif phase == "agent":
                agent_steps += 1
            _sum_usage(event.get("token_usage"), total_usage)
            try:
                duration_sum += float(event.get("duration_s") or 0.0)
            except (TypeError, ValueError):
                pass
    metrics["step_count"] = step_count
    metrics["agent_step_count"] = agent_steps
    metrics["skill_step_count"] = skill_steps
    metrics["token_usage"] = total_usage
    metrics["duration_sum_s"] = round(duration_sum, 3)
    metrics["latency_per_step_s"] = round(duration_sum / step_count, 3) if step_count else 0.0
    return metrics


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)[:80]


async def _build_installed_apps(backend: AdbBackend) -> list[str] | None:
    try:
        return await backend.list_apps()
    except Exception:
        return None


def _build_skill_executor(
    *,
    backend: AdbBackend,
    provider: OpenAICompatibleLLMProvider,
    model: str,
    artifacts_root: Path,
    agent_profile: str,
    image_scale_ratio: float,
) -> SkillExecutor:
    state_validator = LLMStateValidator(provider, image_scale_ratio=image_scale_ratio)
    return SkillExecutor(
        backend=backend,
        state_validator=state_validator,
        action_grounder=_AgentActionGrounder(
            llm=provider,
            model=model,
            agent_profile=agent_profile,
            image_scale_ratio=image_scale_ratio,
        ),
        subgoal_runner=_AgentSubgoalRunner(
            llm=provider,
            backend=backend,
            state_validator=state_validator,
            model=model,
            artifacts_root=artifacts_root,
            agent_profile=agent_profile,
            step_timeout=30.0,
            image_scale_ratio=image_scale_ratio,
        ),
        screenshot_provider=_AgentScreenshotProvider(
            backend=backend,
            artifacts_root=artifacts_root,
        ),
    )


async def _run_one_task(
    *,
    phase: str,
    index: int,
    task: Any,
    env: Any,
    backend: AdbBackend,
    runtime_provider: OpenAICompatibleLLMProvider,
    extraction_provider: OpenAICompatibleLLMProvider,
    reuser_provider: OpenAICompatibleLLMProvider,
    embedding_provider: OpenAICompatibleEmbeddingProvider | None,
    embedding_signature: str | None,
    installed_apps: list[str] | None,
    run_root: Path,
    skill_root: Path,
    model: str,
    reuser_model: str,
    max_steps: int,
    agent_profile: str,
    image_scale_ratio: float,
    enable_reuse: bool,
    enable_extraction: bool,
) -> dict[str, Any]:
    run_dir = run_root / f"{index:02d}_{_safe_name(task.name)}"
    run_dir.mkdir(parents=True, exist_ok=True)
    task_record_path = run_dir / "task_result.json"
    if task_record_path.exists():
        return json.loads(task_record_path.read_text(encoding="utf-8"))

    started = time.time()
    try:
        env.reset(go_home=True)
        task.initialize_task(env)
    except Exception as exc:
        record = {
            "phase": phase,
            "index": index,
            "task_name": task.name,
            "goal": getattr(task, "goal", ""),
            "seed": task.params.get(constants.EpisodeConstants.SEED),
            "android_world_success": False,
            "agent_self_success": False,
            "agent_error": f"initialize_error={type(exc).__name__}: {exc}",
            "steps_taken": 0,
            "trace_path": None,
            "wall_time_s": round(time.time() - started, 3),
            "step_count": 0,
            "agent_step_count": 0,
            "skill_step_count": 0,
            "token_usage": {},
            "duration_sum_s": 0.0,
            "latency_per_step_s": 0.0,
        }
        task_record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return record

    recorder = TrajectoryRecorder(output_dir=run_dir, task=task.goal, platform="android")
    skill_library = None
    skill_executor = None
    skill_reuser = None
    if enable_reuse:
        skill_library = CodeSkillLibrary(
            store_dir=skill_root,
            embedding_provider=embedding_provider,
            merge_llm=runtime_provider,
            embedding_signature=embedding_signature,
            legacy_fallback=False,
        )
        skill_executor = _build_skill_executor(
            backend=backend,
            provider=runtime_provider,
            model=model,
            artifacts_root=run_dir,
            agent_profile=agent_profile,
            image_scale_ratio=image_scale_ratio,
        )
        skill_executor.trajectory_recorder = recorder
        if getattr(skill_executor, "subgoal_runner", None) is not None:
            skill_executor.subgoal_runner._trajectory_recorder = recorder
        skill_reuser = SkillReuser(reuser_provider, threshold=0.6)

    agent = GuiAgent(
        llm=runtime_provider,
        backend=backend,
        trajectory_recorder=recorder,
        model=model,
        artifacts_root=run_dir,
        max_steps=max_steps,
        installed_apps=installed_apps,
        skill_library=skill_library,
        skill_executor=skill_executor,
        skill_reuser=skill_reuser,
        agent_profile=agent_profile,
        image_scale_ratio=image_scale_ratio,
        stagnation_limit=0,
        graph_session_cursor=GraphSessionCursor(),
    )

    agent_error = None
    agent_result = None
    try:
        agent_result = await agent.run(task.goal, max_retries=1)
    except Exception as exc:
        agent_error = f"{type(exc).__name__}: {exc}"
    try:
        aw_success = float(task.is_successful(env)) > 0.5
    except Exception as exc:
        aw_success = False
        agent_error = f"{agent_error}; eval_error={type(exc).__name__}: {exc}" if agent_error else f"eval_error={type(exc).__name__}: {exc}"
    try:
        task.tear_down(env)
    except Exception:
        pass

    trace_path = recorder.path
    if enable_extraction and trace_path is not None and trace_path.exists():
        postprocessor = NoSummaryPostRunProcessor(
            llm=extraction_provider,
            merge_llm=extraction_provider,
            embedding_provider=embedding_provider,
            embedding_signature=embedding_signature,
            skill_store_root=skill_root,
            enable_skill_extraction=True,
            enable_deeplink_skill_extraction=True,
            deeplink_probe_backend=backend,
            evaluation=EvaluationConfig(enabled=False),
        )
        postprocessor.schedule(trace_path, is_success=aw_success, platform="android", task=task.goal)
        await postprocessor.drain()

    metrics = _trace_metrics(trace_path)
    record = {
        "phase": phase,
        "index": index,
        "task_name": task.name,
        "goal": task.goal,
        "seed": task.params.get(constants.EpisodeConstants.SEED),
        "android_world_success": aw_success,
        "agent_self_success": bool(getattr(agent_result, "success", False)) if agent_result is not None else False,
        "agent_error": agent_error or getattr(agent_result, "error", None),
        "steps_taken": int(getattr(agent_result, "steps_taken", 0) or 0) if agent_result is not None else 0,
        "trace_path": str(trace_path) if trace_path is not None else None,
        "wall_time_s": round(time.time() - started, 3),
        **metrics,
    }
    task_record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _method_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    successes = sum(1 for item in records if item.get("android_world_success"))
    token_total = sum(int(item.get("token_usage", {}).get("total_tokens") or 0) for item in records)
    prompt_total = sum(int(item.get("token_usage", {}).get("prompt_tokens") or 0) for item in records)
    completion_total = sum(int(item.get("token_usage", {}).get("completion_tokens") or 0) for item in records)
    step_total = sum(int(item.get("step_count") or 0) for item in records)
    duration_total = sum(float(item.get("duration_sum_s") or 0.0) for item in records)
    return {
        "success_tasks": f"{successes}/{total}",
        "success_rate": successes / total if total else 0.0,
        "avg_total_tokens": token_total / total if total else 0.0,
        "avg_prompt_tokens": prompt_total / total if total else 0.0,
        "avg_completion_tokens": completion_total / total if total else 0.0,
        "latency_per_step_s": duration_total / step_total if step_total else 0.0,
        "total_steps": step_total,
    }


def _write_summary(exp_root: Path, raw_records: list[dict[str, Any]], reuse_records: list[dict[str, Any]]) -> None:
    summary = {
        "raw agent": _method_summary(raw_records),
        "agent with skills": _method_summary(reuse_records),
    }
    (exp_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    csv_path = exp_root / "per_task_metrics.csv"
    fieldnames = [
        "phase",
        "index",
        "task_name",
        "android_world_success",
        "agent_self_success",
        "step_count",
        "agent_step_count",
        "skill_step_count",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "latency_per_step_s",
        "duration_sum_s",
        "wall_time_s",
        "trace_path",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in [*raw_records, *reuse_records]:
            usage = record.get("token_usage") or {}
            writer.writerow({
                **{key: record.get(key) for key in fieldnames},
                "total_tokens": usage.get("total_tokens", 0),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            })

    lines = [
        "| method | success tasks | success rate | token usage(avg)(k) | latency per step(avg)(s) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for method, item in summary.items():
        lines.append(
            "| {method} | {success_tasks} | {rate:.2%} | {tokens:.2f}k | {latency:.3f} |".format(
                method=method,
                success_tasks=item["success_tasks"],
                rate=item["success_rate"],
                tokens=item["avg_total_tokens"] / 1000.0,
                latency=item["latency_per_step_s"],
            )
        )
    (exp_root / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _main(args: argparse.Namespace) -> None:
    exp_root = Path(args.experiment_root).expanduser()
    raw_root = exp_root / "gui_runs"
    reuse_root = exp_root / "gui_runs_reuse"
    skill_root = exp_root / "gui_skills"
    exp_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    reuse_root.mkdir(parents=True, exist_ok=True)
    skill_root.mkdir(parents=True, exist_ok=True)

    base_url, api_key = _provider_config(Path(args.config).expanduser())
    embedding_cfg = _embedding_config(Path(args.config).expanduser())
    embedding_provider = None
    embedding_signature = None
    if embedding_cfg is not None:
        emb_base_url, emb_model, emb_api_key = embedding_cfg
        embedding_provider = OpenAICompatibleEmbeddingProvider(
            base_url=emb_base_url,
            model=emb_model,
            api_key=emb_api_key,
        )
        embedding_signature = emb_model

    runtime_provider = OpenAICompatibleLLMProvider(
        base_url=base_url,
        model=args.agent_model,
        api_key=api_key,
    )
    extraction_provider = OpenAICompatibleLLMProvider(
        base_url=base_url,
        model=args.extract_model,
        api_key=api_key,
    )
    reuser_provider = OpenAICompatibleLLMProvider(
        base_url=base_url,
        model=args.reuser_model,
        api_key=api_key,
    )
    adb_path = _resolve_adb_path(args.adb_path)
    os.environ["ANDROID_ADB_SERVER_PORT"] = str(args.adb_server_port)
    backend = AdbBackend(
        serial=args.serial,
        adb_path=adb_path,
        collect_ui_tree=True,
        collect_ui_tree_nodes=True,
    )
    installed_apps = await _build_installed_apps(backend)

    env = _load_and_setup_env(
        console_port=args.console_port,
        adb_path=adb_path,
        grpc_port=args.grpc_port,
        adb_server_port=args.adb_server_port,
    )
    task_names = args.tasks or _default_tasks(args.task_count)
    manifest = {
        "experiment_root": str(exp_root),
        "android_world_root": str(ANDROID_WORLD_ROOT),
        "task_seed": args.task_seed,
        "tasks": task_names,
        "agent_model": args.agent_model,
        "extract_model": args.extract_model,
        "reuser_model": args.reuser_model,
        "agent_profile": args.agent_profile,
        "max_steps": args.max_steps,
        "serial": args.serial,
        "adb_path": adb_path,
        "adb_server_port": args.adb_server_port,
    }
    (exp_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    try:
        raw_suite = _make_suite(task_names, args.task_seed, env)
        raw_records = []
        for index, task in enumerate(_iter_suite_instances(raw_suite), start=1):
            print(f"[raw {index:02d}/{len(task_names)}] {task.name}: {task.goal}", flush=True)
            raw_records.append(await _run_one_task(
                phase="raw",
                index=index,
                task=task,
                env=env,
                backend=backend,
                runtime_provider=runtime_provider,
                extraction_provider=extraction_provider,
                reuser_provider=reuser_provider,
                embedding_provider=embedding_provider,
                embedding_signature=embedding_signature,
                installed_apps=installed_apps,
                run_root=raw_root,
                skill_root=skill_root,
                model=args.agent_model,
                reuser_model=args.reuser_model,
                max_steps=args.max_steps,
                agent_profile=args.agent_profile,
                image_scale_ratio=args.image_scale_ratio,
                enable_reuse=False,
                enable_extraction=True,
            ))
            _write_jsonl(exp_root / "raw_results.jsonl", raw_records)

        reuse_suite = _make_suite(task_names, args.task_seed, env)
        reuse_records = []
        for index, task in enumerate(_iter_suite_instances(reuse_suite), start=1):
            print(f"[reuse {index:02d}/{len(task_names)}] {task.name}: {task.goal}", flush=True)
            reuse_records.append(await _run_one_task(
                phase="reuse",
                index=index,
                task=task,
                env=env,
                backend=backend,
                runtime_provider=runtime_provider,
                extraction_provider=extraction_provider,
                reuser_provider=reuser_provider,
                embedding_provider=embedding_provider,
                embedding_signature=embedding_signature,
                installed_apps=installed_apps,
                run_root=reuse_root,
                skill_root=skill_root,
                model=args.agent_model,
                reuser_model=args.reuser_model,
                max_steps=args.max_steps,
                agent_profile=args.agent_profile,
                image_scale_ratio=args.image_scale_ratio,
                enable_reuse=True,
                enable_extraction=False,
            ))
            _write_jsonl(exp_root / "reuse_results.jsonl", reuse_records)

        _write_summary(exp_root, raw_records, reuse_records)
    finally:
        env.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-root", default=str(DEFAULT_EXPERIMENT_ROOT))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--task-count", type=int, default=DEFAULT_TASK_COUNT)
    parser.add_argument("--tasks", nargs="*", default=None)
    parser.add_argument("--task-seed", type=int, default=DEFAULT_TASK_SEED)
    parser.add_argument("--agent-model", default=DEFAULT_AGENT_MODEL)
    parser.add_argument("--extract-model", default=DEFAULT_EXTRACT_MODEL)
    parser.add_argument("--reuser-model", default=DEFAULT_REUSER_MODEL)
    parser.add_argument("--agent-profile", default=DEFAULT_AGENT_PROFILE)
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    parser.add_argument("--image-scale-ratio", type=float, default=0.5)
    parser.add_argument("--adb-path", default=None)
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--console-port", type=int, default=5554)
    parser.add_argument("--grpc-port", type=int, default=8554)
    parser.add_argument("--adb-server-port", type=int, default=DEFAULT_ADB_SERVER_PORT)
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(_main(parse_args()))
