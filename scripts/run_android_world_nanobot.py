from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import shlex
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Literal


DEFAULT_ANDROID_WORLD_ROOT = Path("~/Documents/Project/android_world_v3.5").expanduser()
DEFAULT_RUN_ROOT = Path.home() / ".nanobot" / "experiment" / "android_world_nanobot"
DEFAULT_NANOBOT_CONFIG = Path.home() / ".nanobot" / "config.json"
DEFAULT_ADB = Path.home() / "Library" / "Android" / "sdk" / "platform-tools" / "adb"
DEFAULT_ADB_SERVER_PORT = 5038

Route = Literal["adb", "info", "gui"]

ROUTES: tuple[Route, ...] = ("adb", "info", "gui")

ADB_ROUTE_TASKS = frozenset(
    {
        "OpenAppTaskEval",
        "SystemBluetoothTurnOff",
        "SystemBluetoothTurnOffVerify",
        "SystemBluetoothTurnOn",
        "SystemBluetoothTurnOnVerify",
        "SystemBrightnessMax",
        "SystemBrightnessMaxVerify",
        "SystemBrightnessMin",
        "SystemBrightnessMinVerify",
        "SystemCopyToClipboard",
        "SystemWifiTurnOff",
        "SystemWifiTurnOffVerify",
        "SystemWifiTurnOn",
        "SystemWifiTurnOnVerify",
        "TurnOffWifiAndTurnOnBluetooth",
        "TurnOnWifiAndOpenApp",
    }
)


@dataclass(slots=True)
class RegistryItem:
    name: str
    route: Route
    registry_family: str
    template: str = ""
    difficulty: str = ""
    tags: list[str] = field(default_factory=list)
    optimal_steps: int | None = None
    complexity: float | None = None
    app_names: list[str] = field(default_factory=list)


def _load_mapping(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        payload = json.loads(text)
    else:
        import yaml

        payload = yaml.safe_load(text) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    return payload


def _nested(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    value = mapping.get(key)
    return value if isinstance(value, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [str(item) for item in value if str(item).strip()]
    return []


def _route_overrides(config: dict[str, Any]) -> dict[str, Route]:
    overrides: dict[str, Route] = {}
    route_config = _nested(config, "routes")
    for route in ROUTES:
        for name in _as_str_list(route_config.get(route)):
            overrides[name] = route
    task_routes = config.get("task_routes")
    if isinstance(task_routes, dict):
        for name, route in task_routes.items():
            route_text = str(route).strip()
            if route_text in ROUTES:
                overrides[str(name)] = route_text  # type: ignore[assignment]
    return overrides


def _metadata(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "android_world" / "task_metadata.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(item["task_name"]): item
        for item in payload
        if isinstance(item, dict) and item.get("task_name")
    }


def _information_retrieval_names(root: Path) -> set[str]:
    path = (
        root
        / "android_world"
        / "task_evals"
        / "information_retrieval"
        / "proto"
        / "tasks.textproto"
    )
    if not path.exists():
        return set()
    return set(re.findall(r'^\s*name:\s*"([^"]+)"', path.read_text(encoding="utf-8"), re.MULTILINE))


def _clean_tags(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(tag) for tag in raw if str(tag).strip()]


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _classify_route(
    name: str,
    *,
    registry_family: str,
    overrides: dict[str, Route] | None = None,
) -> Route:
    if overrides and name in overrides:
        return overrides[name]
    if registry_family == "information_retrieval":
        return "gui"
    if name in ADB_ROUTE_TASKS:
        return "adb"
    return "gui"


def _add_android_world_to_path(root: Path) -> None:
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)


def _load_registry_items(
    root: Path,
    *,
    family: str,
    overrides: dict[str, Route] | None = None,
) -> list[RegistryItem]:
    metadata = _metadata(root)
    info_names = _information_retrieval_names(root)
    _add_android_world_to_path(root)
    try:
        from android_world import registry as aw_registry
    except Exception:
        return _metadata_registry_items(metadata, info_names, family=family, overrides=overrides)

    task_registry = aw_registry.TaskRegistry()
    selected = task_registry.get_registry(family)
    android_names = set(task_registry.get_registry(task_registry.ANDROID_FAMILY))
    info_registry_names = set(task_registry.get_registry(task_registry.INFORMATION_RETRIEVAL_FAMILY))
    items: list[RegistryItem] = []
    for name, task_class in sorted(selected.items()):
        item = metadata.get(name, {})
        registry_family = "information_retrieval" if name in info_registry_names else "android"
        if family == task_registry.ANDROID_FAMILY and name not in android_names:
            continue
        if family == task_registry.INFORMATION_RETRIEVAL_FAMILY and name not in info_registry_names:
            continue
        complexity = _float_or_none(getattr(task_class, "complexity", None))
        app_names = getattr(task_class, "app_names", ())
        if not isinstance(app_names, tuple | list):
            app_names = ()
        items.append(
            RegistryItem(
                name=name,
                route=_classify_route(name, registry_family=registry_family, overrides=overrides),
                registry_family=registry_family,
                template=str(item.get("task_template") or getattr(task_class, "template", "") or ""),
                difficulty=str(item.get("difficulty") or ""),
                tags=_clean_tags(item.get("tags")),
                optimal_steps=_int_or_none(item.get("optimal_steps")),
                complexity=complexity,
                app_names=[str(app) for app in app_names if app],
            )
        )
    return items


def _metadata_registry_items(
    metadata: dict[str, dict[str, Any]],
    info_names: set[str],
    *,
    family: str,
    overrides: dict[str, Route] | None,
) -> list[RegistryItem]:
    items: list[RegistryItem] = []
    for name, item in sorted(metadata.items()):
        registry_family = "information_retrieval" if name in info_names else "android"
        if family == "android" and registry_family != "android":
            continue
        if family == "information_retrieval" and registry_family != "information_retrieval":
            continue
        items.append(
            RegistryItem(
                name=name,
                route=_classify_route(name, registry_family=registry_family, overrides=overrides),
                registry_family=registry_family,
                template=str(item.get("task_template") or ""),
                difficulty=str(item.get("difficulty") or ""),
                tags=_clean_tags(item.get("tags")),
                optimal_steps=_int_or_none(item.get("optimal_steps")),
            )
        )
    return items


def _write_registry(items: list[RegistryItem], path: Path) -> None:
    grouped = {
        route: [asdict(item) for item in items if item.route == route]
        for route in ROUTES
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(grouped, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _print_registry(items: list[RegistryItem]) -> None:
    for route in ROUTES:
        route_items = [item for item in items if item.route == route]
        print(f"\n[{route}] {len(route_items)} tasks")
        for item in route_items:
            steps = f", optimal_steps={item.optimal_steps}" if item.optimal_steps is not None else ""
            complexity = f", complexity={item.complexity:g}" if item.complexity is not None else ""
            print(f"  - {item.name} ({item.registry_family}{steps}{complexity})")


def _resolve_adb_path(value: str | None) -> str:
    if value:
        return str(Path(value).expanduser())
    if DEFAULT_ADB.is_file():
        return str(DEFAULT_ADB)
    found = shutil.which("adb")
    if found:
        return found
    raise FileNotFoundError("adb not found; pass --adb-path")


def _adb_command_prefix(adb_path: str, serial: str | None) -> str:
    parts = [shlex.quote(adb_path)]
    if serial:
        parts.extend(["-s", shlex.quote(serial)])
    return " ".join(parts)


def _selected_task_names(
    items: list[RegistryItem],
    *,
    tasks: list[str] | None,
    task_file: Path | None,
    task_type: str,
    task_count: int | None,
) -> list[str]:
    names = [item.name for item in items]
    requested: list[str] = []
    if task_file is not None:
        requested.extend(
            line.strip()
            for line in task_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    if tasks:
        requested.extend(tasks)
    if requested:
        missing = [name for name in requested if name not in names]
        if missing:
            raise ValueError(f"Task(s) not in selected registry: {', '.join(missing)}")
        names = requested
    if task_type != "auto":
        names = [item.name for item in items if item.name in names and item.route == task_type]
    if task_count is not None:
        names = names[: max(task_count, 0)]
    return names


def _max_steps_for_task(
    task: Any,
    item: RegistryItem | None,
    *,
    mode: str,
    steps_per_complexity: int,
    optimal_multiplier: float,
    override: int | None,
) -> int:
    if override is not None:
        return max(1, override)
    if mode == "optimal" and item and item.optimal_steps:
        return max(1, int(round(item.optimal_steps * optimal_multiplier)))
    complexity = _float_or_none(getattr(task, "complexity", None))
    if complexity is None and item is not None:
        complexity = item.complexity
    if complexity is None:
        return max(1, steps_per_complexity)
    return max(1, int(round(complexity * steps_per_complexity)))


def _apply_runner_config(config: Any, args: argparse.Namespace, runner_config: dict[str, Any]) -> Any:
    from nanobot.config.schema import GuiConfig

    main = _nested(runner_config, "main")
    gui = _nested(runner_config, "gui")

    main_provider = args.main_provider or main.get("provider")
    main_model = args.main_model or main.get("model")
    if main_provider:
        config.agents.defaults.provider = str(main_provider)
    if main_model:
        config.agents.defaults.model = str(main_model)

    if args.workspace:
        config.agents.defaults.workspace = str(Path(args.workspace).expanduser())

    if config.gui is None:
        config.gui = GuiConfig()
    config.gui.backend = "adb"
    config.gui.artifacts_dir = str(Path(args.trajectory_dir).expanduser()) if args.trajectory_dir else str(
        Path(args.run_root).expanduser() / "gui_runs"
    )
    config.gui.max_steps = max(1, int(args.gui_max_steps or gui.get("max_steps") or config.gui.max_steps))
    config.gui.provider = args.gui_provider or gui.get("provider") or config.gui.provider
    config.gui.model = args.gui_model or gui.get("model") or config.gui.model
    config.gui.validator_model = args.validator_model or gui.get("validator_model") or config.gui.validator_model
    config.gui.grounder_model = args.grounder_model or gui.get("grounder_model") or config.gui.grounder_model
    config.gui.reuser_model = args.reuser_model or gui.get("reuser_model") or config.gui.reuser_model
    config.gui.embedding_model = args.embedding_model or gui.get("embedding_model") or config.gui.embedding_model
    config.gui.embedding_api_key = args.embedding_api_key or gui.get("embedding_api_key") or config.gui.embedding_api_key
    config.gui.embedding_api_base = args.embedding_api_base or gui.get("embedding_api_base") or config.gui.embedding_api_base
    config.gui.agent_profile = args.gui_agent_profile or gui.get("agent_profile") or config.gui.agent_profile
    config.gui.skill_threshold = float(args.skill_threshold if args.skill_threshold is not None else gui.get("skill_threshold", config.gui.skill_threshold))
    if args.enable_skill_execution is not None:
        config.gui.enable_skill_execution = args.enable_skill_execution
    elif "enable_skill_execution" in gui:
        config.gui.enable_skill_execution = bool(gui["enable_skill_execution"])
    if args.enable_skill_extraction is not None:
        config.gui.enable_skill_extraction = args.enable_skill_extraction
    elif "enable_skill_extraction" in gui:
        config.gui.enable_skill_extraction = bool(gui["enable_skill_extraction"])
    if args.serial:
        config.gui.adb.serial = args.serial
    return config


def _load_nanobot_config(args: argparse.Namespace, runner_config: dict[str, Any]) -> Any:
    from nanobot.config.loader import load_config, resolve_config_env_vars

    config = resolve_config_env_vars(load_config(Path(args.nanobot_config).expanduser()))
    return _apply_runner_config(config, args, runner_config)


def _build_provider_snapshot(config: Any) -> Any:
    from nanobot.providers.factory import build_provider_snapshot

    return build_provider_snapshot(config)


def _build_gui_provider_snapshot(config: Any, main_snapshot: Any) -> Any:
    from nanobot.providers.factory import build_gui_provider_snapshot

    snapshot = build_gui_provider_snapshot(config)
    return snapshot or main_snapshot


def _build_agent_tools(route: Route, config: Any, *, adb_path: str, workspace: Path) -> Any:
    from nanobot.agent.tools.registry import ToolRegistry

    tools = ToolRegistry()
    if route == "adb":
        from nanobot.agent.tools.shell import ExecTool

        adb_dir = str(Path(adb_path).parent)
        tools.register(
            ExecTool(
                working_dir=str(workspace),
                timeout=config.tools.exec.timeout,
                path_append=adb_dir,
                allowed_env_keys=config.tools.exec.allowed_env_keys,
            )
        )
    elif route == "info":
        from nanobot.agent.tools.web import WebFetchTool, WebSearchTool

        tools.register(
            WebSearchTool(
                config=config.tools.web.search,
                proxy=config.tools.web.proxy,
                user_agent=config.tools.web.user_agent,
            )
        )
        tools.register(
            WebFetchTool(
                config=config.tools.web.fetch,
                proxy=config.tools.web.proxy,
                user_agent=config.tools.web.user_agent,
            )
        )
    else:
        raise ValueError(f"Agent tools are not used for route={route}")
    return tools


def _agent_messages(route: Route, *, goal: str, adb_prefix: str) -> list[dict[str, Any]]:
    if route == "adb":
        system = (
            "You are nanobot's main agent running an AndroidWorld task in ADB-only mode. "
            "Only use the exec tool. Complete the task with adb commands; do not use GUI automation. "
            f"Use this adb command prefix whenever you call adb: {adb_prefix}. "
            "The AndroidWorld task state has already been initialized. Verify the final state with adb when practical. "
            "In the final response, briefly state what adb command path completed the task."
        )
    elif route == "info":
        system = (
            "You are nanobot's main agent running an information-query task. "
            "Only web_search and web_fetch are available. Return the exact answer requested by the task, "
            "with no extra explanation unless the task asks for it."
        )
    else:
        raise ValueError(route)
    return [{"role": "system", "content": system}, {"role": "user", "content": goal}]


async def _run_agent_route(
    *,
    route: Route,
    goal: str,
    config: Any,
    provider_snapshot: Any,
    adb_prefix: str,
    adb_path: str,
    workspace: Path,
    session_key: str,
    max_iterations: int,
) -> Any:
    from nanobot.agent.runner import AgentRunner, AgentRunSpec

    tools = _build_agent_tools(route, config, adb_path=adb_path, workspace=workspace)
    runner = AgentRunner(provider_snapshot.provider)
    return await runner.run(
        AgentRunSpec(
            initial_messages=_agent_messages(route, goal=goal, adb_prefix=adb_prefix),
            tools=tools,
            model=provider_snapshot.model,
            max_iterations=max_iterations,
            max_tool_result_chars=config.agents.defaults.max_tool_result_chars,
            temperature=config.agents.defaults.temperature,
            max_tokens=config.agents.defaults.max_tokens,
            reasoning_effort=config.agents.defaults.reasoning_effort,
            workspace=workspace,
            session_key=session_key,
            context_window_tokens=provider_snapshot.context_window_tokens,
            provider_retry_mode=config.agents.defaults.provider_retry_mode,
            concurrent_tools=True,
        )
    )


async def _run_gui_route(
    *,
    goal: str,
    config: Any,
    gui_provider_snapshot: Any,
    workspace: Path,
    max_steps: int,
) -> dict[str, Any]:
    from nanobot.agent.tools.gui import GuiSubagentTool

    gui_config = config.gui.model_copy(deep=True, update={"max_steps": max_steps})
    tool = GuiSubagentTool(
        gui_config=gui_config,
        provider=gui_provider_snapshot.provider,
        model=gui_provider_snapshot.model,
        workspace=workspace,
    )
    raw = await tool.execute(task=goal, backend="adb")
    await tool._wait_for_pending_postprocessing()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"success": False, "summary": raw, "error": "invalid_gui_payload"}
    return payload if isinstance(payload, dict) else {"success": False, "summary": raw, "error": "invalid_gui_payload"}


def _load_android_world_runtime(root: Path) -> dict[str, Any]:
    _add_android_world_to_path(root)
    from android_env import loader
    from android_env.components import config_classes
    from android_world import constants, registry, suite_utils
    from android_world.env import android_world_controller, env_launcher, interface

    return {
        "loader": loader,
        "config_classes": config_classes,
        "constants": constants,
        "registry": registry,
        "suite_utils": suite_utils,
        "android_world_controller": android_world_controller,
        "env_launcher": env_launcher,
        "interface": interface,
    }


def _load_and_setup_env(
    aw: dict[str, Any],
    *,
    console_port: int,
    adb_path: str,
    grpc_port: int,
    adb_server_port: int,
    perform_emulator_setup: bool,
) -> Any:
    config_classes = aw["config_classes"]
    controller_mod = aw["android_world_controller"]
    config = config_classes.AndroidEnvConfig(
        task=config_classes.FilesystemTaskConfig(path=controller_mod._write_default_task_proto()),
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
    android_env_instance = aw["loader"].load(config)
    controller = controller_mod.AndroidWorldController(android_env_instance)
    env = aw["interface"].AsyncAndroidEnv(controller)
    aw["env_launcher"].setup_env(env, emulator_setup=perform_emulator_setup, freeze_datetime=True)
    return env


def _make_suite(aw: dict[str, Any], task_names: list[str], seed: int, env: Any) -> Any:
    task_registry = aw["registry"].TaskRegistry()
    task_classes = task_registry.get_registry(task_registry.ANDROID_WORLD_FAMILY)
    suite = aw["suite_utils"].create_suite(
        task_classes,
        n_task_combinations=1,
        seed=seed,
        tasks=task_names,
        use_identical_params=False,
        env=env,
    )
    suite.suite_family = task_registry.ANDROID_WORLD_FAMILY
    return suite


def _iter_suite(suite: Any) -> list[Any]:
    tasks: list[Any] = []
    for _, instances in suite.items():
        tasks.extend(instances)
    return tasks


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)[:80]


def _json_safe(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(_json_safe(record), ensure_ascii=False) + "\n")


async def _run_one_task(
    *,
    task: Any,
    item: RegistryItem,
    env: Any,
    config: Any,
    provider_snapshot: Any,
    gui_provider_snapshot: Any,
    workspace: Path,
    run_dir: Path,
    adb_path: str,
    adb_prefix: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    task_dir = run_dir / f"{_safe_name(task.name)}_{int(time.time() * 1000)}"
    task_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    max_steps = _max_steps_for_task(
        task,
        item,
        mode=args.max_steps_mode,
        steps_per_complexity=args.steps_per_complexity,
        optimal_multiplier=args.optimal_step_multiplier,
        override=args.gui_max_steps,
    )
    record: dict[str, Any] = {
        "task_name": task.name,
        "route": item.route,
        "goal": task.goal,
        "params": getattr(task, "params", {}),
        "complexity": _float_or_none(getattr(task, "complexity", None)),
        "max_steps": max_steps,
        "task_dir": str(task_dir),
    }
    try:
        env.reset(go_home=True)
        task.initialize_task(env)
    except Exception as exc:
        record.update(
            {
                "android_world_success": False,
                "android_world_score": 0.0,
                "error": f"initialize_error={type(exc).__name__}: {exc}",
                "wall_time_s": round(time.time() - started, 3),
            }
        )
        (task_dir / "task_result.json").write_text(json.dumps(_json_safe(record), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return record

    try:
        if item.route in {"adb", "info"}:
            result = await _run_agent_route(
                route=item.route,
                goal=task.goal,
                config=config,
                provider_snapshot=provider_snapshot,
                adb_prefix=adb_prefix,
                adb_path=adb_path,
                workspace=workspace,
                session_key=f"android_world:{task.name}",
                max_iterations=args.max_tool_iterations,
            )
            record.update(
                {
                    "nanobot_final": result.final_content,
                    "nanobot_stop_reason": result.stop_reason,
                    "nanobot_error": result.error,
                    "tools_used": result.tools_used,
                    "token_usage": result.usage,
                }
            )
            if item.route == "info":
                env.interaction_cache = result.final_content or ""
            (task_dir / "messages.json").write_text(json.dumps(result.messages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        else:
            payload = await _run_gui_route(
                goal=task.goal,
                config=config,
                gui_provider_snapshot=gui_provider_snapshot,
                workspace=workspace,
                max_steps=max_steps,
            )
            record.update(
                {
                    "gui_payload": payload,
                    "nanobot_final": payload.get("summary"),
                    "tools_used": ["gui_task"],
                    "trace_path": payload.get("trace_path"),
                    "token_usage": payload.get("total_token_usage") or payload.get("token_usage") or {},
                    "steps_taken": payload.get("steps_taken"),
                    "agent_self_success": payload.get("success"),
                    "agent_error": payload.get("error"),
                }
            )

        try:
            score = float(task.is_successful(env))
        except Exception as exc:
            score = 0.0
            record["eval_error"] = f"{type(exc).__name__}: {exc}"
        record["android_world_score"] = score
        record["android_world_success"] = score > 0.5
    finally:
        try:
            task.tear_down(env)
        except Exception as exc:
            record["tear_down_error"] = f"{type(exc).__name__}: {exc}"
        record["wall_time_s"] = round(time.time() - started, 3)
        (task_dir / "task_result.json").write_text(json.dumps(_json_safe(record), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def _write_summary(run_dir: Path, records: list[dict[str, Any]]) -> None:
    summary: dict[str, Any] = {"total": len(records), "routes": {}}
    for route in ROUTES:
        route_records = [record for record in records if record.get("route") == route]
        total = len(route_records)
        success = sum(1 for record in route_records if record.get("android_world_success"))
        summary["routes"][route] = {
            "total": total,
            "success": success,
            "success_rate": success / total if total else 0.0,
        }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    fieldnames = [
        "task_name",
        "route",
        "android_world_success",
        "android_world_score",
        "agent_self_success",
        "steps_taken",
        "wall_time_s",
        "trace_path",
        "task_dir",
    ]
    with (run_dir / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({key: record.get(key) for key in fieldnames})


async def _main(args: argparse.Namespace) -> None:
    android_world_root = Path(args.android_world_root).expanduser()
    runner_config = _load_mapping(Path(args.runner_config).expanduser() if args.runner_config else None)
    overrides = _route_overrides(runner_config)
    items = _load_registry_items(android_world_root, family=args.family, overrides=overrides)
    if args.registry_output:
        _write_registry(items, Path(args.registry_output).expanduser())
    if args.list_registry:
        _print_registry(items)
        return

    task_names = _selected_task_names(
        items,
        tasks=args.tasks,
        task_file=Path(args.tasks_file).expanduser() if args.tasks_file else None,
        task_type=args.task_type,
        task_count=args.task_count,
    )
    item_by_name = {item.name: item for item in items}
    selected_items = [item_by_name[name] for name in task_names]
    run_dir = Path(args.run_root).expanduser() / time.strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_registry(selected_items, run_dir / "registry_selected.json")
    if args.dry_run:
        _print_registry(selected_items)
        return

    if args.trajectory_dir is None:
        args.trajectory_dir = str(run_dir / "gui_runs")
    config = _load_nanobot_config(args, runner_config)
    workspace = config.workspace_path
    workspace.mkdir(parents=True, exist_ok=True)
    adb_path = _resolve_adb_path(args.adb_path)
    adb_dir = str(Path(adb_path).parent)
    os.environ["PATH"] = adb_dir + os.pathsep + os.environ.get("PATH", "")
    os.environ["ANDROID_ADB_SERVER_PORT"] = str(args.adb_server_port)
    adb_prefix = _adb_command_prefix(adb_path, args.serial)

    provider_snapshot = _build_provider_snapshot(config)
    gui_provider_snapshot = _build_gui_provider_snapshot(config, provider_snapshot)
    aw = _load_android_world_runtime(android_world_root)
    env = _load_and_setup_env(
        aw,
        console_port=args.console_port,
        adb_path=adb_path,
        grpc_port=args.grpc_port,
        adb_server_port=args.adb_server_port,
        perform_emulator_setup=args.perform_emulator_setup,
    )
    manifest = {
        "android_world_root": str(android_world_root),
        "run_dir": str(run_dir),
        "workspace": str(workspace),
        "trajectory_dir": str(config.gui.artifacts_dir if config.gui else ""),
        "task_seed": args.task_seed,
        "tasks": [asdict(item) for item in selected_items],
        "adb_path": adb_path,
        "adb_server_port": args.adb_server_port,
        "serial": args.serial,
        "main_model": provider_snapshot.model,
        "gui_model": gui_provider_snapshot.model,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    records: list[dict[str, Any]] = []
    try:
        suite = _make_suite(aw, task_names, args.task_seed, env)
        for index, task in enumerate(_iter_suite(suite), start=1):
            item = item_by_name[task.name]
            print(f"[{index:02d}/{len(task_names)}][{item.route}] {task.name}: {task.goal}", flush=True)
            records.append(
                await _run_one_task(
                    task=task,
                    item=item,
                    env=env,
                    config=config,
                    provider_snapshot=provider_snapshot,
                    gui_provider_snapshot=gui_provider_snapshot,
                    workspace=workspace,
                    run_dir=run_dir,
                    adb_path=adb_path,
                    adb_prefix=adb_prefix,
                    args=args,
                )
            )
            _write_jsonl(run_dir / "results.jsonl", records)
    finally:
        try:
            env.close()
        finally:
            _write_summary(run_dir, records)
    print(f"Results written to {run_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run selected AndroidWorld tasks through nanobot ADB/info/gui routes."
    )
    parser.add_argument("--android-world-root", default=str(DEFAULT_ANDROID_WORLD_ROOT))
    parser.add_argument("--nanobot-config", default=str(DEFAULT_NANOBOT_CONFIG))
    parser.add_argument("--runner-config", default=None, help="Optional JSON/YAML route/model override config.")
    parser.add_argument("--run-root", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument("--trajectory-dir", default=None, help="GUI trace directory. Defaults to <run-root>/gui_runs.")
    parser.add_argument("--workspace", default=None, help="Override nanobot workspace.")
    parser.add_argument("--family", default="android_world", choices=["android_world", "android", "information_retrieval"])
    parser.add_argument("--tasks", nargs="*", default=None)
    parser.add_argument("--tasks-file", default=None)
    parser.add_argument("--task-count", type=int, default=None)
    parser.add_argument("--task-type", default="auto", choices=["auto", *ROUTES])
    parser.add_argument("--task-seed", type=int, default=30)
    parser.add_argument("--list-registry", action="store_true")
    parser.add_argument("--registry-output", default=None)
    parser.add_argument("--dry-run", action="store_true")

    parser.add_argument("--main-provider", default=None)
    parser.add_argument("--main-model", default=None)
    parser.add_argument("--gui-provider", default=None)
    parser.add_argument("--gui-model", default=None)
    parser.add_argument("--gui-agent-profile", default=None)
    parser.add_argument("--validator-model", default=None)
    parser.add_argument("--grounder-model", default=None)
    parser.add_argument("--reuser-model", default=None)
    parser.add_argument("--embedding-model", default=None)
    parser.add_argument("--embedding-api-key", default=None)
    parser.add_argument("--embedding-api-base", default=None)
    parser.add_argument("--skill-threshold", type=float, default=None)
    parser.add_argument("--enable-skill-execution", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--enable-skill-extraction", action=argparse.BooleanOptionalAction, default=None)

    parser.add_argument("--max-tool-iterations", type=int, default=20)
    parser.add_argument("--gui-max-steps", type=int, default=None)
    parser.add_argument("--max-steps-mode", choices=["complexity", "optimal"], default="complexity")
    parser.add_argument("--steps-per-complexity", type=int, default=10)
    parser.add_argument("--optimal-step-multiplier", type=float, default=1.5)

    parser.add_argument("--adb-path", default=None)
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--console-port", type=int, default=5554)
    parser.add_argument("--grpc-port", type=int, default=8554)
    parser.add_argument("--adb-server-port", type=int, default=DEFAULT_ADB_SERVER_PORT)
    parser.add_argument("--perform-emulator-setup", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(_main(parse_args()))
