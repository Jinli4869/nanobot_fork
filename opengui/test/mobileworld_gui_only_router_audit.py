#!/usr/bin/env python3
"""Audit gui_task workflow planning on MobileWorld GUI-only tasks.

The script statically reads MobileWorld task definitions, filters the same
GUI-only set used by MobileWorld evaluation, then feeds each original task
``goal`` directly into nanobot's ``GuiWorkflowRunner`` planner. It does not
execute GUI actions on a device.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import json
import shutil
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

NANOBOT_ROOT = Path(__file__).resolve().parents[2]
if str(NANOBOT_ROOT) not in sys.path:
    sys.path.insert(0, str(NANOBOT_ROOT))

from nanobot.agent.gui_adapter import NanobotLLMAdapter  # noqa: E402
from nanobot.agent.tools.gui import (  # noqa: E402
    GuiRouterContext,
    GuiRouterMemoryEvidence,
    GuiRouterMemoryRetriever,
    GuiWorkflowPlan,
    GuiWorkflowRunner,
)
from nanobot.config.loader import load_config, resolve_config_env_vars  # noqa: E402
from nanobot.providers.factory import (  # noqa: E402
    build_gui_provider_snapshot,
    build_provider_snapshot,
)
from opengui.skills.normalization import normalize_app_identifier  # noqa: E402

DEFAULT_MOBILEWORLD_ROOT = Path("/Users/jinli/Documents/Project/MobileWorld")
DEFAULT_WORKSPACE = Path.home() / ".nanobot" / "workspace"
LOW_LEVEL_UI_TERMS = {
    "tap",
    "click",
    "swipe",
    "scroll",
    "button",
    "menu",
    "search bar",
    "输入框",
    "点击",
    "滑动",
    "按钮",
    "菜单",
    "搜索框",
}
MOBILEWORLD_APP_DESCRIPTIONS = {
    "Calendar": "calendar events, availability, dates, and scheduling",
    "Camera": "taking photos or videos",
    "Chrome": "web browsing, website lookup, and web search",
    "Clock": "alarms, timers, and time",
    "Contacts": "creating, editing, and reading contacts",
    "Docreader": "opening and reading PDF or document files",
    "Files": "Downloads, local files, folders, and file picking",
    "Gallery": "photos, albums, image editing, and media selection",
    "Mail": "email search, reading, composing, sending, and attachments",
    "Maps": "map search, place details, routes, and walking time",
    "Mastodon": "Mastodon posts, profiles, polls, invites, and social actions",
    "Mattermost": "Mattermost channels, messages, and workspace collaboration",
    "Messages": "SMS and text messages",
    "Settings": "Android system settings and wallpaper",
    "Taodian": "shopping and product/order tasks",
}


@dataclass(frozen=True)
class MobileWorldTaskSpec:
    name: str
    goal: str
    app_names: tuple[str, ...]
    tags: tuple[str, ...]
    source: str

    @property
    def expected_mode(self) -> str:
        return "multi_app" if len(self.app_names) > 1 else "single"

    @property
    def expected_apps(self) -> tuple[str, ...]:
        return tuple(normalize_mobileworld_app(app) for app in self.app_names)


@dataclass(frozen=True)
class MobileWorldAppSpec:
    name: str
    package: str
    description: str


@dataclass(frozen=True)
class PlanSummary:
    mode: str
    subtasks: list[dict[str, Any]]

    @property
    def app_hints(self) -> tuple[str, ...]:
        apps: list[str] = []
        for subtask in self.subtasks:
            app_hint = subtask.get("app_hint")
            if isinstance(app_hint, str) and app_hint and app_hint not in apps:
                apps.append(app_hint)
        return tuple(apps)


@dataclass(frozen=True)
class AuditResult:
    task_name: str
    expected_mode: str
    actual_mode: str
    expected_apps: tuple[str, ...]
    actual_apps: tuple[str, ...]
    passed: bool
    reasons: tuple[str, ...]
    goal: str
    app_names: tuple[str, ...]
    tags: tuple[str, ...]
    source: str
    plan: PlanSummary
    router_context: dict[str, Any]
    requirement_analysis: str
    repair_attempt: dict[str, Any] | None = None


def normalize_mobileworld_app(app_name: str) -> str:
    return normalize_app_identifier("android", app_name)


def load_gui_only_tasks(mobileworld_root: Path) -> tuple[list[MobileWorldTaskSpec], list[dict[str, str]]]:
    task_root = mobileworld_root / "src" / "mobile_world" / "tasks" / "definitions"
    tasks: list[MobileWorldTaskSpec] = []
    skipped: list[dict[str, str]] = []
    seen_names: set[str] = set()

    for path in sorted(task_root.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            skipped.append({"source": str(path), "reason": f"syntax_error: {exc}"})
            continue

        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not _inherits_base_task(node):
                continue
            goal = _class_value(node, "goal")
            app_names = _class_value(node, "app_names")
            tags = _class_value(node, "task_tags") or set()
            if not isinstance(goal, str):
                skipped.append({"source": str(path), "reason": f"{node.name}: non_literal_goal"})
                continue
            if not isinstance(app_names, set) or not all(isinstance(app, str) for app in app_names):
                skipped.append({"source": str(path), "reason": f"{node.name}: non_literal_app_names"})
                continue
            if "agent-mcp" in tags or "agent-user-interaction" in tags:
                continue
            if node.name in seen_names:
                skipped.append({"source": str(path), "reason": f"{node.name}: duplicate_task_name"})
                continue
            seen_names.add(node.name)
            tasks.append(
                MobileWorldTaskSpec(
                    name=node.name,
                    goal=" ".join(goal.split()),
                    app_names=tuple(sorted(app_names)),
                    tags=tuple(sorted(str(tag) for tag in tags)),
                    source=str(path.relative_to(mobileworld_root)),
                )
            )
    return tasks, skipped


def build_mobileworld_app_catalog(tasks: list[MobileWorldTaskSpec]) -> tuple[MobileWorldAppSpec, ...]:
    specs: list[MobileWorldAppSpec] = []
    for app_name in sorted({app for task in tasks for app in task.app_names}):
        package = normalize_mobileworld_app(app_name)
        specs.append(
            MobileWorldAppSpec(
                name=app_name,
                package=package,
                description=MOBILEWORLD_APP_DESCRIPTIONS.get(app_name, "MobileWorld GUI app"),
            )
        )
    return tuple(specs)


def _inherits_base_task(node: ast.ClassDef) -> bool:
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id == "BaseTask":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "BaseTask":
            return True
    return False


def _class_value(node: ast.ClassDef, name: str) -> Any:
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return _literal_value(stmt.value)
        if isinstance(stmt, ast.FunctionDef) and stmt.name == name and _is_property(stmt):
            for inner in stmt.body:
                if isinstance(inner, ast.Return):
                    return _literal_value(inner.value)
    return None


def _is_property(node: ast.FunctionDef) -> bool:
    return any(isinstance(decorator, ast.Name) and decorator.id == "property" for decorator in node.decorator_list)


def _literal_value(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (SyntaxError, ValueError):
        return None


def select_tasks(
    tasks: list[MobileWorldTaskSpec],
    *,
    names: list[str],
    limit: int | None,
    offset: int,
) -> list[MobileWorldTaskSpec]:
    if names:
        wanted = set(names)
        selected = [task for task in tasks if task.name in wanted]
        missing = sorted(wanted - {task.name for task in selected})
        if missing:
            raise SystemExit(f"Unknown task(s): {', '.join(missing)}")
    else:
        selected = tasks
    if offset:
        selected = selected[offset:]
    if limit is not None:
        selected = selected[:limit]
    return selected


async def _unused_run_task(*_args: Any, **_kwargs: Any) -> str:
    raise RuntimeError("This audit only calls workflow planning; GUI execution is disabled.")


def build_runner(args: argparse.Namespace) -> GuiWorkflowRunner:
    config = resolve_config_env_vars(load_config(Path(args.config).expanduser() if args.config else None))
    if args.model or args.provider:
        model = args.model or (config.gui.model if config.gui and config.gui.model else config.agents.defaults.model)
        provider_override = args.provider or (config.gui.provider if config.gui else None)
        snapshot = build_provider_snapshot(
            config,
            model_override=model,
            provider_override=provider_override,
        )
    else:
        snapshot = build_gui_provider_snapshot(config) or build_provider_snapshot(config)

    return GuiWorkflowRunner(
        llm=NanobotLLMAdapter(snapshot.provider, snapshot.model),
        run_task=_unused_run_task,
        load_latest_step_event=lambda _path: {},
    )


async def plan_task(
    runner: GuiWorkflowRunner,
    task: MobileWorldTaskSpec,
    *,
    workspace: Path,
    context_mode: str,
    app_catalog: tuple[MobileWorldAppSpec, ...],
) -> tuple[GuiWorkflowPlan, GuiRouterContext | None]:
    router_context = build_router_context(
        task,
        workspace=workspace,
        context_mode=context_mode,
        app_catalog=app_catalog,
    )
    plan = await runner._plan_workflow(task.goal, router_context=router_context)
    return runner._normalize_plan_app_hints(plan, platform="android"), router_context


def build_router_context(
    task: MobileWorldTaskSpec,
    *,
    workspace: Path,
    context_mode: str,
    app_catalog: tuple[MobileWorldAppSpec, ...],
) -> GuiRouterContext | None:
    raw_context = GuiRouterMemoryRetriever(workspace).retrieve(task.goal, platform="android")
    if context_mode == "raw":
        return raw_context if raw_context.has_context() else None

    if context_mode == "catalog":
        evidence = (
            GuiRouterMemoryEvidence(
                source="mobileworld_app_catalog",
                text=mobileworld_app_catalog_text(app_catalog),
            ),
            *raw_context.evidence,
        )
        return GuiRouterContext(
            app_candidates=tuple(unique_packages(app.package for app in app_catalog)),
            evidence=evidence,
        )

    if context_mode == "oracle":
        evidence = (
            GuiRouterMemoryEvidence(
                source=f"mobileworld_task_oracle:{task.name}",
                text=mobileworld_oracle_text(task),
            ),
            *raw_context.evidence,
        )
        return GuiRouterContext(
            app_candidates=tuple(unique_packages(task.expected_apps)),
            evidence=evidence,
        )

    raise ValueError(f"Unknown router context mode: {context_mode}")


def mobileworld_app_catalog_text(app_catalog: tuple[MobileWorldAppSpec, ...]) -> str:
    entries = [
        f"{app.name} -> {app.package}: {app.description}"
        for app in app_catalog
        if app.package and app.package != "unknown"
    ]
    return (
        "MobileWorld GUI app catalog for this benchmark run. These are allowed app hints; "
        "choose only the apps required by the current task and do not use every app: "
        + "; ".join(entries)
    )


def mobileworld_oracle_text(task: MobileWorldTaskSpec) -> str:
    entries = [
        f"{name} -> {package}"
        for name, package in zip(task.app_names, task.expected_apps, strict=False)
    ]
    return (
        "MobileWorld task app scope. Use these app hints if the task is split, and do not add "
        "apps outside this scope: "
        + "; ".join(entries)
    )


def unique_packages(packages: Any) -> list[str]:
    result: list[str] = []
    for package in packages:
        if not isinstance(package, str):
            continue
        cleaned = package.strip()
        if not cleaned or cleaned == "unknown" or cleaned in result:
            continue
        result.append(cleaned)
    return result


def summarize_plan(plan: GuiWorkflowPlan) -> PlanSummary:
    return PlanSummary(
        mode=plan.mode,
        subtasks=[
            {
                "app_hint": subtask.app_hint,
                "task": subtask.task,
                "inputs": list(subtask.inputs),
                "outputs": list(subtask.outputs),
            }
            for subtask in plan.subtasks
        ],
    )


def evaluate_plan(task: MobileWorldTaskSpec, plan: GuiWorkflowPlan, context: GuiRouterContext | None) -> AuditResult:
    summary = summarize_plan(plan)
    reasons: list[str] = []
    expected_apps = task.expected_apps
    actual_apps = summary.app_hints

    if task.expected_mode == "single":
        if plan.mode == "multi_app" and len(plan.subtasks) >= 2:
            reasons.append("expected_single_app_but_split")
    else:
        if plan.mode != "multi_app" or len(plan.subtasks) < 2:
            reasons.append("expected_multi_app_but_single")
        missing = [app for app in expected_apps if app not in actual_apps]
        extra = [app for app in actual_apps if app not in expected_apps]
        if missing:
            reasons.append("missing_expected_app_hints:" + ",".join(missing))
        if extra:
            reasons.append("hallucinated_or_unexpected_app_hints:" + ",".join(extra))

    low_level = [
        subtask.task
        for subtask in plan.subtasks
        if any(term in subtask.task.casefold() for term in LOW_LEVEL_UI_TERMS)
    ]
    if low_level:
        reasons.append("subtask_contains_low_level_ui_path")

    return AuditResult(
        task_name=task.name,
        expected_mode=task.expected_mode,
        actual_mode=plan.mode,
        expected_apps=expected_apps,
        actual_apps=actual_apps,
        passed=not reasons,
        reasons=tuple(reasons),
        goal=task.goal,
        app_names=task.app_names,
        tags=task.tags,
        source=task.source,
        plan=summary,
        router_context=format_router_context(context),
        requirement_analysis=analyze_requirement(task),
    )


def analyze_requirement(task: MobileWorldTaskSpec) -> str:
    apps = ", ".join(task.app_names) or "unknown"
    if task.expected_mode == "single":
        return (
            f"MobileWorld declares one GUI app ({apps}); the router should keep this as a "
            "single gui_task even if the goal contains several UI steps."
        )
    return (
        f"MobileWorld declares multiple GUI apps ({apps}); the router should split into "
        "ordered app-scoped subtasks, use these app hints, and avoid adding apps not declared by the task."
    )


def format_router_context(context: GuiRouterContext | None) -> dict[str, Any]:
    if context is None:
        return {"app_candidates": [], "evidence": []}
    return {
        "app_candidates": list(context.app_candidates),
        "evidence": [{"source": item.source, "text": item.text} for item in context.evidence],
    }


async def audit_tasks(
    runner: GuiWorkflowRunner,
    tasks: list[MobileWorldTaskSpec],
    *,
    workspace: Path,
    context_mode: str,
    app_catalog: tuple[MobileWorldAppSpec, ...],
) -> list[AuditResult]:
    results: list[AuditResult] = []
    for index, task in enumerate(tasks, start=1):
        print(f"[{index}/{len(tasks)}] planning {task.name} ({task.expected_mode})", flush=True)
        try:
            plan, context = await plan_task(
                runner,
                task,
                workspace=workspace,
                context_mode=context_mode,
                app_catalog=app_catalog,
            )
            result = evaluate_plan(task, plan, context)
        except Exception as exc:
            result = AuditResult(
                task_name=task.name,
                expected_mode=task.expected_mode,
                actual_mode="planner_error",
                expected_apps=task.expected_apps,
                actual_apps=(),
                passed=False,
                reasons=(f"planner_error:{type(exc).__name__}:{exc}",),
                goal=task.goal,
                app_names=task.app_names,
                tags=task.tags,
                source=task.source,
                plan=PlanSummary(mode="planner_error", subtasks=[]),
                router_context={"app_candidates": [], "evidence": []},
                requirement_analysis=analyze_requirement(task),
            )
        print("  " + ("PASS" if result.passed else "FAIL " + "; ".join(result.reasons)), flush=True)
        results.append(result)
    return results


async def repair_failures(
    runner: GuiWorkflowRunner,
    failures: list[AuditResult],
    task_by_name: dict[str, MobileWorldTaskSpec],
    *,
    base_workspace: Path,
    mode: str,
    context_mode: str,
    app_catalog: tuple[MobileWorldAppSpec, ...],
) -> tuple[Path | None, dict[str, AuditResult]]:
    if not failures or mode == "none":
        return None, {}
    repair_workspace = prepare_repair_workspace(base_workspace, failures, mode=mode)
    repaired: dict[str, AuditResult] = {}
    for failure in failures:
        task = task_by_name[failure.task_name]
        plan, context = await plan_task(
            runner,
            task,
            workspace=repair_workspace,
            context_mode=context_mode,
            app_catalog=app_catalog,
        )
        repaired[failure.task_name] = evaluate_plan(task, plan, context)
    return repair_workspace, repaired


def prepare_repair_workspace(base_workspace: Path, failures: list[AuditResult], *, mode: str) -> Path:
    if mode == "temp":
        target = Path(tempfile.mkdtemp(prefix="mobileworld_router_memory_"))
        for relative in ("memory", "android_deeplinks.md", "adb_app_commands.md"):
            source_path = base_workspace / relative
            target_path = target / relative
            if source_path.is_dir():
                shutil.copytree(source_path, target_path, dirs_exist_ok=True)
            elif source_path.exists():
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)
    elif mode == "in-place":
        target = base_workspace
    else:
        raise ValueError(f"Unknown repair mode: {mode}")

    append_router_memory_entries(target, failures)
    return target


def append_router_memory_entries(workspace: Path, failures: list[AuditResult]) -> None:
    memory_dir = workspace / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)
    history_path = memory_dir / "history.jsonl"
    next_cursor = read_last_cursor(history_path) + 1
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    with history_path.open("a", encoding="utf-8") as handle:
        for offset, failure in enumerate(failures):
            entry = {
                "cursor": next_cursor + offset,
                "timestamp": timestamp,
                "content": repair_memory_text(failure),
            }
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_last_cursor(path: Path) -> int:
    if not path.exists():
        return 0
    last = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        cursor = payload.get("cursor")
        if isinstance(cursor, int):
            last = max(last, cursor)
    return last


def repair_memory_text(failure: AuditResult) -> str:
    if failure.expected_mode == "single":
        policy = (
            "This is a single-app GUI-only task. Do not split it into multiple gui_task subtasks; "
            f"route it as one high-level task for {', '.join(failure.app_names)}."
        )
    else:
        policy = (
            "This is a multi-app GUI-only task. Split only into high-level app-scoped subtasks for "
            f"{', '.join(failure.app_names)}. Do not add unrelated apps or low-level click/tap paths."
        )
    return (
        f"MobileWorld gui_task router correction for {failure.task_name}: {policy} "
        f"Original goal: {failure.goal}"
    )


def attach_repair_results(
    results: list[AuditResult],
    repaired: dict[str, AuditResult],
) -> list[AuditResult]:
    out: list[AuditResult] = []
    for result in results:
        if result.task_name not in repaired:
            out.append(result)
            continue
        after = repaired[result.task_name]
        out.append(
            AuditResult(
                **{
                    **asdict(result),
                    "plan": result.plan,
                    "repair_attempt": {
                        "passed": after.passed,
                        "reasons": list(after.reasons),
                        "actual_mode": after.actual_mode,
                        "actual_apps": list(after.actual_apps),
                        "plan": asdict(after.plan),
                        "router_context": after.router_context,
                    },
                }
            )
        )
    return out


def summarize(results: list[AuditResult]) -> dict[str, Any]:
    failures = [result for result in results if not result.passed]
    return {
        "total": len(results),
        "passed": len(results) - len(failures),
        "failed": len(failures),
        "expected_mode_counts": dict(Counter(result.expected_mode for result in results)),
        "actual_mode_counts": dict(Counter(result.actual_mode for result in results)),
        "failure_reason_counts": dict(Counter(reason for result in failures for reason in result.reasons)),
    }


def write_outputs(
    *,
    output: Path,
    mobileworld_root: Path,
    workspace: Path,
    repair_workspace: Path | None,
    context_mode: str,
    app_catalog: tuple[MobileWorldAppSpec, ...],
    selected: list[MobileWorldTaskSpec],
    skipped: list[dict[str, str]],
    results: list[AuditResult],
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mobileworld_root": str(mobileworld_root),
        "workspace": str(workspace),
        "repair_workspace": str(repair_workspace) if repair_workspace else None,
        "router_context_mode": context_mode,
        "mobileworld_app_catalog": [asdict(app) for app in app_catalog],
        "summary": summarize(results),
        "selected_task_count": len(selected),
        "skipped_static_tasks": skipped,
        "results": [result_to_json(result) for result in results],
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def result_to_json(result: AuditResult) -> dict[str, Any]:
    data = asdict(result)
    data["plan"] = asdict(result.plan)
    return data


def print_summary(results: list[AuditResult], *, output: Path) -> None:
    summary = summarize(results)
    print("\nSummary")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    failures = [result for result in results if not result.passed]
    if failures:
        print("\nFailures")
        for result in failures[:20]:
            print(f"- {result.task_name}: {', '.join(result.reasons)}")
            print(f"  requirement: {result.requirement_analysis}")
            if result.repair_attempt:
                status = "PASS" if result.repair_attempt["passed"] else "FAIL"
                print(f"  repair: {status} {result.repair_attempt['reasons']}")
    print(f"\nWrote report: {output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit nanobot gui_task workflow planning for MobileWorld GUI-only tasks.",
    )
    parser.add_argument("--mobileworld-root", type=Path, default=DEFAULT_MOBILEWORLD_ROOT)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--provider", type=str, default=None)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--tasks", nargs="*", default=[])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true", help="Only list selected GUI-only tasks.")
    parser.add_argument(
        "--router-context-mode",
        choices=("raw", "catalog", "oracle"),
        default="raw",
        help=(
            "raw uses the production memory retriever; catalog also provides the MobileWorld app catalog; "
            "oracle provides the task's declared MobileWorld apps."
        ),
    )
    parser.add_argument(
        "--repair-mode",
        choices=("none", "temp", "in-place"),
        default="none",
        help="After first-pass failures, append router correction entries and re-run failed tasks.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/private/tmp/mobileworld_gui_only_router_audit.json"),
    )
    return parser.parse_args()


async def main_async(args: argparse.Namespace) -> None:
    mobileworld_root = args.mobileworld_root.expanduser().resolve()
    workspace = args.workspace.expanduser().resolve()
    tasks, skipped = load_gui_only_tasks(mobileworld_root)
    app_catalog = build_mobileworld_app_catalog(tasks)
    selected = select_tasks(tasks, names=args.tasks, limit=args.limit, offset=args.offset)

    print(f"MobileWorld GUI-only tasks discovered: {len(tasks)}")
    print(f"Selected tasks: {len(selected)}")
    print(f"Router context mode: {args.router_context_mode}")
    if args.dry_run:
        for task in selected:
            print(f"{task.name}\t{task.expected_mode}\t{','.join(task.app_names)}\t{task.goal}")
        return

    runner = build_runner(args)
    results = await audit_tasks(
        runner,
        selected,
        workspace=workspace,
        context_mode=args.router_context_mode,
        app_catalog=app_catalog,
    )
    failures = [result for result in results if not result.passed]
    repair_workspace, repaired = await repair_failures(
        runner,
        failures,
        {task.name: task for task in selected},
        base_workspace=workspace,
        mode=args.repair_mode,
        context_mode=args.router_context_mode,
        app_catalog=app_catalog,
    )
    if repaired:
        results = attach_repair_results(results, repaired)

    write_outputs(
        output=args.output.expanduser().resolve(),
        mobileworld_root=mobileworld_root,
        workspace=workspace,
        repair_workspace=repair_workspace,
        context_mode=args.router_context_mode,
        app_catalog=app_catalog,
        selected=selected,
        skipped=skipped,
        results=results,
    )
    print_summary(results, output=args.output.expanduser().resolve())


def main() -> None:
    asyncio.run(main_async(parse_args()))


if __name__ == "__main__":
    main()
