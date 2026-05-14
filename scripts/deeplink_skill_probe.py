from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from opengui.action import Action
from opengui.backends.adb import AdbBackend
from opengui.observation import Observation
from opengui.skills.code_graph import compile_code_skills
from opengui.skills.data import Skill, SkillStep
from opengui.skills.executor import ExecutionState, SkillExecutor
from opengui.skills.state_contract import evaluate_state_contract, normalize_state_contract
from opengui.trajectory.recorder import ExecutionPhase, TrajectoryRecorder


@dataclass(frozen=True)
class DeeplinkCandidate:
    candidate_id: str
    app: str
    description: str
    uri: str
    expected_texts: tuple[str, ...]
    component: str | None = None
    package: str | None = None


CANDIDATES: tuple[DeeplinkCandidate, ...] = (
    DeeplinkCandidate(
        "ctrip_hotel_hangzhou_west_lake",
        "ctrip.android.view",
        "Ctrip hotel prefix for Hangzhou West Lake Cultural Square nearby hotels.",
        "ctrip://hotelSearch/?city=%E6%9D%AD%E5%B7%9E&keyword="
        "%E8%A5%BF%E6%B9%96%E6%96%87%E5%8C%96%E5%B9%BF%E5%9C%BA",
        ("酒店", "目的地", "搜索"),
        component="ctrip.android.view/.view.CtripBootActivity",
    ),
    DeeplinkCandidate(
        "ctrip_homestay_xian_bell_tower",
        "ctrip.android.view",
        "Ctrip hotel prefix for Xi'an Bell Tower homestay search.",
        "ctrip://hotelSearch/?city=%E8%A5%BF%E5%AE%89&keyword="
        "%E9%92%9F%E6%A5%BC%20%E6%B0%91%E5%AE%BF",
        ("酒店", "民宿", "目的地", "搜索"),
        component="ctrip.android.view/.view.CtripBootActivity",
    ),
    DeeplinkCandidate(
        "ctrip_budget_hotel_nanjing_fuzimiao",
        "ctrip.android.view",
        "Ctrip hotel prefix for Nanjing Fuzimiao economy chain hotel search.",
        "ctrip://hotelSearch/?city=%E5%8D%97%E4%BA%AC&keyword="
        "%E5%A4%AB%E5%AD%90%E5%BA%99%20%E6%B1%89%E5%BA%AD%20%E5%A6%82%E5%AE%B6",
        ("酒店", "夫子庙", "目的地", "搜索"),
        component="ctrip.android.view/.view.CtripBootActivity",
    ),
    DeeplinkCandidate(
        "ctrip_train_search",
        "ctrip.android.view",
        "Ctrip train ticket search prefix.",
        "ctrip://trainSearch/",
        ("火车票", "出发", "到达", "查询"),
        component="ctrip.android.view/.view.CtripBootActivity",
    ),
    DeeplinkCandidate(
        "ctrip_vacation_search",
        "ctrip.android.view",
        "Ctrip vacation package search prefix.",
        "ctrip://vacationSearch/",
        ("旅游", "度假", "搜索"),
        component="ctrip.android.view/.view.CtripBootActivity",
    ),
    DeeplinkCandidate(
        "zhihu_search_reinforcement_learning",
        "com.zhihu.android",
        "Zhihu search prefix for reinforcement learning.",
        "zhihu://search?q=%E5%BC%BA%E5%8C%96%E5%AD%A6%E4%B9%A0",
        ("强化学习", "搜索", "知乎"),
        component="com.zhihu.android/.app.ui.activity.RouterPortalActivity",
    ),
    DeeplinkCandidate(
        "zhihu_search_macbook_review",
        "com.zhihu.android",
        "Zhihu search prefix for MacBook Pro review articles.",
        "https://www.zhihu.com/search?q=MacBook%20Pro%E6%B5%8B%E8%AF%84&type=content",
        ("MacBook", "搜索", "知乎"),
        package="com.zhihu.android",
    ),
    DeeplinkCandidate(
        "zhihu_hot",
        "com.zhihu.android",
        "Zhihu hot ranking prefix.",
        "https://www.zhihu.com/hot",
        ("热榜", "知乎"),
        package="com.zhihu.android",
    ),
    DeeplinkCandidate(
        "zhihu_question_entry",
        "com.zhihu.android",
        "Zhihu question detail prefix.",
        "https://www.zhihu.com/question/19550228",
        ("知乎", "问题", "回答"),
        package="com.zhihu.android",
    ),
    DeeplinkCandidate(
        "gmail_compose_en",
        "com.google.android.gm",
        "Gmail compose prefix with recipient, subject, and body.",
        "mailto:test@example.com?subject=OpenGUI%20Smoke&body=hello",
        ("Compose", "To", "Subject", "撰写", "收件人", "主题"),
        component="com.google.android.gm/.ComposeActivityGmailExternal",
    ),
    DeeplinkCandidate(
        "gmail_compose_cn",
        "com.google.android.gm",
        "Gmail compose prefix with Chinese subject and body.",
        "mailto:test@example.com?subject=%E6%B5%8B%E8%AF%95&body=%E6%B7%B1%E9%93%BE%E6%8E%A5",
        ("Compose", "To", "Subject", "撰写", "收件人", "主题"),
        component="com.google.android.gm/.ComposeActivityGmailExternal",
    ),
    DeeplinkCandidate(
        "gmail_inbox_label",
        "com.google.android.gm",
        "Gmail inbox label prefix.",
        "gmail://label/Inbox",
        ("Inbox", "Primary", "Gmail", "收件箱"),
        component="com.google.android.gm/.browse.PublicLabelDeepLinkV2",
    ),
    DeeplinkCandidate(
        "calendar_create_event",
        "com.google.android.calendar",
        "Google Calendar create-event prefix from web app link.",
        "https://calendar.google.com/calendar/render?action=TEMPLATE&text=OpenGUI%20Smoke",
        ("Calendar", "Save", "Event", "日历", "保存", "活动"),
        package="com.google.android.calendar",
    ),
    DeeplinkCandidate(
        "calendar_day_view",
        "com.google.android.calendar",
        "Google Calendar day-view prefix.",
        "https://calendar.google.com/calendar/u/0/r/day",
        ("Calendar", "Today", "日历", "今天"),
        package="com.google.android.calendar",
    ),
    DeeplinkCandidate(
        "clock_root",
        "com.google.android.deskclock",
        "Clock app root prefix.",
        "clock-app://com.google.android.deskclock",
        ("Alarm", "Clock", "Timer", "闹钟", "时钟", "计时器"),
        component="com.google.android.deskclock/com.android.deskclock.HandleUris",
    ),
)


class BackendObservationProvider:
    def __init__(self, backend: AdbBackend, screenshot_dir: Path) -> None:
        self._backend = backend
        self._screenshot_dir = screenshot_dir
        self._counter = 0

    async def get_observation(self) -> Observation:
        self._counter += 1
        path = self._screenshot_dir / f"executor_{self._counter:03d}.png"
        return await self._backend.observe(path, timeout=8.0)

    async def get_screenshot(self) -> Path | None:
        observation = await self.get_observation()
        return Path(observation.screenshot_path) if observation.screenshot_path else None


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    return text or "deeplink"


def _extra_lists(observation: Observation) -> dict[str, list[str]]:
    extra = observation.extra or {}
    return {
        "visible_text": [str(v) for v in extra.get("visible_text", [])],
        "content_desc": [str(v) for v in extra.get("content_desc", [])],
        "resource_ids": [str(v) for v in extra.get("resource_ids", [])],
    }


def _flatten_text(extra: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("visible_text", "content_desc", "resource_ids"):
        values = extra.get(key, [])
        if isinstance(values, list):
            parts.extend(str(value) for value in values)
    return "\n".join(parts)


def _fingerprint(observation: Observation) -> str:
    extra = _extra_lists(observation)
    payload = {
        "app": observation.foreground_app,
        "visible_text": extra["visible_text"][:40],
        "content_desc": extra["content_desc"][:40],
        "resource_ids": extra["resource_ids"][:60],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _is_dynamic_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped) > 28:
        return True
    if re.fullmatch(r"[\d:./年月日,\- ]+", stripped):
        return True
    if re.search(r"[￥$]\s*\d|\d+%", stripped):
        return True
    return False


def _select_contract_element(
    candidate: DeeplinkCandidate,
    observation: Observation,
) -> dict[str, Any] | None:
    extra = _extra_lists(observation)
    visible_text = extra["visible_text"]
    content_desc = extra["content_desc"]
    resource_ids = extra["resource_ids"]

    for expected in candidate.expected_texts:
        for text in visible_text:
            if expected and expected.lower() in text.lower():
                return {"selector": {"text": text}, "state": ["visible"]}
        for desc in content_desc:
            if expected and expected.lower() in desc.lower():
                return {"selector": {"content_desc": desc}, "state": ["visible"]}

    for text in visible_text:
        if not _is_dynamic_text(text):
            return {"selector": {"text": text}, "state": ["visible"]}

    for desc in content_desc:
        if not _is_dynamic_text(desc):
            return {"selector": {"content_desc": desc}, "state": ["visible"]}

    for resource_id in resource_ids:
        if resource_id.startswith("android:id/"):
            continue
        if ":" not in resource_id:
            continue
        return {"selector": {"resource_id": resource_id}, "state": ["visible"]}

    return None


def _build_contract(candidate: DeeplinkCandidate, observation: Observation) -> dict[str, Any] | None:
    element = _select_contract_element(candidate, observation)
    if not element:
        return None
    return normalize_state_contract({
        "anchor": {"app_package": candidate.app},
        "signature": {"required": [element], "forbidden": []},
    })


def _classify(
    candidate: DeeplinkCandidate,
    *,
    output: str,
    error: str | None,
    observation: Observation | None,
    contract: dict[str, Any] | None,
) -> tuple[str, bool, str | None]:
    if error:
        lowered = error.lower()
        if "unable to resolve" in lowered or "activity not started" in lowered:
            return "resolver_error", False, error
        return "launch_error", False, error
    if observation is None:
        return "no_observation", False, "missing post-launch observation"
    if observation.foreground_app != candidate.app:
        return "wrong_app", False, f"foreground_app={observation.foreground_app}"

    text_blob = _flatten_text(observation.extra or {})
    target_verified = any(expected and expected in text_blob for expected in candidate.expected_texts)
    auth_gate = any(token in text_blob for token in (
        "登录", "Sign in", "SIGN IN", "Add email address", "添加电子邮件地址",
    ))
    contract_ok = (
        evaluate_state_contract(contract, observation=observation)
        if contract is not None
        else None
    )
    if auth_gate:
        return "auth_gate", False, "foreground app opened but login/account gate is shown"
    if target_verified and contract_ok:
        return "target_verified", True, None
    if contract_ok:
        return "app_reached_weak_contract", False, "target text absent; derived page contract only"
    return "unverified", False, output[:300] if output else None


async def _reset_device(backend: AdbBackend, packages: tuple[str, ...]) -> None:
    for package in packages:
        try:
            await backend._run("shell", "am", "force-stop", package, timeout=5.0)
        except Exception:
            pass
    await backend._run("shell", "input", "keyevent", "HOME", timeout=5.0)
    await asyncio.sleep(0.6)


async def _installed(backend: AdbBackend, package: str) -> bool:
    try:
        output = await backend._run("shell", "pm", "path", package, timeout=5.0)
    except Exception:
        return False
    return bool(output.strip())


async def _current_activity(backend: AdbBackend) -> str:
    try:
        output = await backend._run("shell", "dumpsys", "window", "windows", timeout=5.0)
    except Exception as exc:
        return f"activity_probe_error:{exc}"
    for line in output.splitlines():
        if "mCurrentFocus" in line or "mFocusedApp" in line:
            return line.strip()
    return ""


async def _probe_candidate(
    backend: AdbBackend,
    recorder: TrajectoryRecorder,
    candidate: DeeplinkCandidate,
    *,
    screenshot_dir: Path,
    packages_to_reset: tuple[str, ...],
    index: int,
) -> dict[str, Any]:
    await _reset_device(backend, packages_to_reset)
    screenshot_path = screenshot_dir / f"{index:02d}_{candidate.candidate_id}.png"
    pre_activity = await _current_activity(backend)
    output = ""
    error: str | None = None
    observation: Observation | None = None

    start = time.monotonic()
    try:
        output = await backend.execute(Action(
            action_type="open_deeplink",
            text=candidate.uri,
            component=candidate.component,
            package=candidate.package,
        ), timeout=10.0)
        await asyncio.sleep(2.5)
    except Exception as exc:
        error = str(exc)
    try:
        observation = await backend.observe(screenshot_path, timeout=8.0)
    except Exception as exc:
        if error:
            error = f"{error}; observe_error={exc}"
        else:
            error = f"observe_error={exc}"
    duration_s = time.monotonic() - start
    post_activity = await _current_activity(backend)
    contract = _build_contract(candidate, observation) if observation is not None else None
    status, reusable, reason = _classify(
        candidate,
        output=output,
        error=error,
        observation=observation,
        contract=contract,
    )

    extra = observation.extra if observation is not None else {}
    recorder.record_step(
        action={
            "action_type": "open_deeplink",
            "text": candidate.uri,
            "component": candidate.component,
            "package": candidate.package,
        },
        model_output=f"deeplink probe: {candidate.description}",
        screenshot_path=str(screenshot_path),
        foreground_app=observation.foreground_app if observation else None,
        screen_width=observation.screen_width if observation else None,
        screen_height=observation.screen_height if observation else None,
        platform="android",
        observation_extra=extra if isinstance(extra, dict) else {},
        phase=ExecutionPhase.SKILL,
        duration_s=duration_s,
    )

    result = {
        "candidate": asdict(candidate),
        "status": status,
        "reusable_as_skill_start": reusable,
        "reason": reason,
        "am_start_output": output,
        "error": error,
        "duration_s": round(duration_s, 3),
        "pre_activity": pre_activity,
        "post_activity": post_activity,
        "foreground_app": observation.foreground_app if observation else None,
        "fingerprint": _fingerprint(observation) if observation else "",
        "screenshot_path": str(screenshot_path),
        "contract": contract,
        "contract_eval": (
            evaluate_state_contract(contract, observation=observation)
            if contract is not None and observation is not None
            else None
        ),
        "visible_text": _extra_lists(observation)["visible_text"][:30] if observation else [],
        "content_desc": _extra_lists(observation)["content_desc"][:30] if observation else [],
        "resource_ids": _extra_lists(observation)["resource_ids"][:30] if observation else [],
    }
    recorder.record_event("deeplink_probe_result", **result)
    return result


def _quote_py(value: str) -> str:
    return repr(value)


def _selector_to_r(selector: dict[str, Any], state: list[str]) -> str:
    parts: list[str] = []
    for key in ("text", "content_desc", "resource_id", "class", "xpath"):
        if selector.get(key):
            py_key = "class_" if key == "class" else key
            parts.append(f"{py_key}={_quote_py(str(selector[key]))}")
    for flag in ("visible", "clickable", "enabled", "focused", "scrollable"):
        if flag in state:
            parts.append(f"{flag}=True")
    return f"R({', '.join(parts)})"


def _contract_to_c(contract: dict[str, Any]) -> str:
    anchor = contract.get("anchor", {})
    required = contract.get("signature", {}).get("required", [])
    r_calls: list[str] = []
    for element in required:
        selector = element.get("selector", {})
        state = element.get("state", [])
        if isinstance(selector, dict) and isinstance(state, list):
            r_calls.append(_selector_to_r(selector, state))
    app = anchor.get("app_package")
    return f"C(app={_quote_py(str(app))}, required=[{', '.join(r_calls)}])"


def _generate_skill_code(results: list[dict[str, Any]]) -> str:
    lines = [
        "from __future__ import annotations",
        "",
        "from opengui.skills.code_graph import C, R, action, skill",
        "",
        "",
    ]
    for result in results:
        contract = result.get("contract")
        if not result.get("reusable_as_skill_start") or not isinstance(contract, dict):
            continue
        candidate = result["candidate"]
        function_name = f"open_{_slug(candidate['candidate_id'])}"
        fixed_values = {"text": candidate["uri"]}
        if candidate.get("component"):
            fixed_values["component"] = candidate["component"]
        if candidate.get("package"):
            fixed_values["package"] = candidate["package"]
        lines.extend([
            "@skill(",
            f"    app={_quote_py(candidate['app'])},",
            "    platform='android',",
            "    tags=('deeplink', 'probe'),",
            f"    skill_id='deeplink:{candidate['candidate_id']}',",
            f"    description={_quote_py(candidate['description'])},",
            ")",
            f"async def {function_name}(device):",
            "    await action(",
            "        'open_deeplink',",
            f"        target={_quote_py(candidate['description'])},",
            "        fixed=True,",
            f"        fixed_values={fixed_values!r},",
            f"        state_contract={_contract_to_c(contract)},",
            "    )",
            "",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


async def _execute_compiled_skills(
    backend: AdbBackend,
    skills: tuple[Skill, ...],
    *,
    screenshot_dir: Path,
    packages_to_reset: tuple[str, ...],
) -> list[dict[str, Any]]:
    provider = BackendObservationProvider(backend, screenshot_dir)
    executor = SkillExecutor(
        backend=backend,
        screenshot_provider=provider,
        stop_on_failure=True,
    )
    outcomes: list[dict[str, Any]] = []
    for skill_obj in skills:
        await _reset_device(backend, packages_to_reset)
        start = time.monotonic()
        result = await executor.execute(skill_obj, timeout=10.0)
        outcomes.append({
            "skill_id": skill_obj.skill_id,
            "name": skill_obj.name,
            "state": result.state.value if isinstance(result.state, ExecutionState) else str(result.state),
            "success": result.state == ExecutionState.SUCCEEDED,
            "error": result.error,
            "duration_s": round(time.monotonic() - start, 3),
            "step_results": [
                {
                    "index": step.step_index,
                    "state": step.state.value,
                    "valid_state_check": step.valid_state_check,
                    "error": step.error,
                    "action_summary": step.action_summary,
                }
                for step in result.step_results
            ],
        })
    return outcomes


async def _execute_optional_fallback_smoke(
    backend: AdbBackend,
    *,
    screenshot_dir: Path,
    packages_to_reset: tuple[str, ...],
) -> dict[str, Any]:
    contract = normalize_state_contract({
        "anchor": {"app_package": "com.google.android.deskclock"},
        "signature": {
            "required": [{"selector": {"text": "DefinitelyMissingForFallback"}, "state": ["visible"]}],
            "forbidden": [],
        },
    })
    valid_contract = normalize_state_contract({
        "anchor": {"app_package": "com.google.android.deskclock"},
        "signature": {"required": [], "forbidden": []},
    })
    skill_obj = Skill(
        skill_id="deeplink:fallback_smoke",
        name="deeplink_optional_fallback_smoke",
        description="Optional failing deeplink followed by a valid deeplink fallback.",
        app="com.google.android.deskclock",
        platform="android",
        tags=("deeplink", "fallback"),
        steps=(
            SkillStep(
                action_type="open_deeplink",
                target="bad clock deeplink",
                parameters={"optional": True},
                state_contract=contract,
                fixed=True,
                fixed_values={
                    "text": "clock-app://com.google.android.deskclock",
                    "component": "com.google.android.deskclock/com.android.deskclock.HandleUris",
                },
            ),
            SkillStep(
                action_type="open_deeplink",
                target="clock fallback deeplink",
                state_contract=valid_contract,
                fixed=True,
                fixed_values={
                    "text": "clock-app://com.google.android.deskclock",
                    "component": "com.google.android.deskclock/com.android.deskclock.HandleUris",
                },
            ),
        ),
    )
    await _reset_device(backend, packages_to_reset)
    provider = BackendObservationProvider(backend, screenshot_dir)
    executor = SkillExecutor(
        backend=backend,
        screenshot_provider=provider,
        stop_on_failure=True,
    )
    start = time.monotonic()
    result = await executor.execute(skill_obj, timeout=10.0)
    return {
        "skill_id": skill_obj.skill_id,
        "state": result.state.value,
        "success": result.state == ExecutionState.SUCCEEDED,
        "error": result.error,
        "duration_s": round(time.monotonic() - start, 3),
        "step_results": [
            {
                "index": step.step_index,
                "state": step.state.value,
                "valid_state_check": step.valid_state_check,
                "error": step.error,
                "action_summary": step.action_summary,
            }
            for step in result.step_results
        ],
    }


def _write_report(
    output_dir: Path,
    results: list[dict[str, Any]],
    compile_errors: list[str],
    executor_results: list[dict[str, Any]],
    fallback_result: dict[str, Any],
) -> None:
    status_counts: dict[str, int] = {}
    for result in results:
        status = str(result["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    lines = [
        "# Deeplink + Skill Probe Report",
        "",
        f"- candidates: {len(results)}",
        f"- reusable target-verified skill starts: {sum(1 for r in results if r['reusable_as_skill_start'])}",
        f"- compiled skill errors: {len(compile_errors)}",
        f"- executor skill runs: {len(executor_results)}",
        f"- executor successes: {sum(1 for r in executor_results if r['success'])}",
        f"- optional fallback success: {fallback_result.get('success')}",
        f"- status counts: {status_counts}",
        "",
        "## Candidate Results",
        "",
        "| id | app | status | reusable | foreground | contract | reason |",
        "|---|---|---|---:|---|---|---|",
    ]
    for result in results:
        candidate = result["candidate"]
        lines.append(
            f"| {candidate['candidate_id']} | {candidate['app']} | {result['status']} | "
            f"{result['reusable_as_skill_start']} | {result['foreground_app']} | "
            f"{result['contract_eval']} | {str(result['reason'] or '')[:90]} |"
        )
    if compile_errors:
        lines.extend(["", "## Compile Errors", ""])
        lines.extend(f"- {error}" for error in compile_errors)
    lines.extend(["", "## Executor Results", ""])
    for result in executor_results:
        lines.append(
            f"- {result['skill_id']}: success={result['success']} "
            f"state={result['state']} error={result['error']}"
        )
    lines.extend(["", "## Optional Fallback Smoke", ""])
    lines.append(json.dumps(fallback_result, ensure_ascii=False, indent=2))
    (output_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/Users/jinli/.nanobot/workspace/deeplink_skill_experiment"),
    )
    parser.add_argument("--serial", default=None)
    args = parser.parse_args()

    output_dir = args.output_dir
    screenshot_dir = output_dir / "screenshots"
    executor_screenshot_dir = output_dir / "executor_screenshots"
    trajectory_dir = output_dir / "trajectory"
    for path in (screenshot_dir, executor_screenshot_dir, trajectory_dir):
        path.mkdir(parents=True, exist_ok=True)

    backend = AdbBackend(
        serial=args.serial,
        use_scrcpy=False,
        collect_ui_tree=True,
        collect_ui_tree_nodes=True,
    )
    await backend.preflight()
    packages_to_reset = tuple(dict.fromkeys(candidate.app for candidate in CANDIDATES))
    installed = {
        package: await _installed(backend, package)
        for package in packages_to_reset
    }

    recorder = TrajectoryRecorder(
        output_dir=trajectory_dir,
        task="deeplink skill feasibility probe across Ctrip, Zhihu, Gmail, Clock, Calendar",
        platform="android",
    )
    recorder.start(phase=ExecutionPhase.SKILL)
    recorder.record_event("deeplink_probe_start", installed_packages=installed)

    results: list[dict[str, Any]] = []
    for index, candidate in enumerate(CANDIDATES, start=1):
        if not installed.get(candidate.app):
            skipped = {
                "candidate": asdict(candidate),
                "status": "package_missing",
                "reusable_as_skill_start": False,
                "reason": f"package not installed: {candidate.app}",
                "foreground_app": None,
                "contract_eval": None,
            }
            recorder.record_event("deeplink_probe_result", **skipped)
            results.append(skipped)
            continue
        results.append(await _probe_candidate(
            backend,
            recorder,
            candidate,
            screenshot_dir=screenshot_dir,
            packages_to_reset=packages_to_reset,
            index=index,
        ))

    skill_code = _generate_skill_code(results)
    code_path = output_dir / "deeplink_skill_graph_code.py"
    code_path.write_text(skill_code, encoding="utf-8")
    compiled = compile_code_skills(skill_code)
    compile_errors = compiled.errors
    executor_results: list[dict[str, Any]] = []
    if not compile_errors and compiled.skills:
        executor_results = await _execute_compiled_skills(
            backend,
            compiled.skills,
            screenshot_dir=executor_screenshot_dir,
            packages_to_reset=packages_to_reset,
        )

    fallback_result = await _execute_optional_fallback_smoke(
        backend,
        screenshot_dir=executor_screenshot_dir,
        packages_to_reset=packages_to_reset,
    )

    payload = {
        "generated_at": time.time(),
        "installed_packages": installed,
        "results": results,
        "compiled_skill_count": len(compiled.skills),
        "compile_errors": compile_errors,
        "executor_results": executor_results,
        "fallback_result": fallback_result,
        "skill_code_path": str(code_path),
        "trajectory_path": str(recorder.path),
    }
    (output_dir / "deeplink_probe_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_report(output_dir, results, compile_errors, executor_results, fallback_result)
    recorder.record_event(
        "deeplink_probe_complete",
        compiled_skill_count=len(compiled.skills),
        compile_errors=compile_errors,
        executor_successes=sum(1 for result in executor_results if result["success"]),
    )
    recorder.finish(success=not compile_errors)


if __name__ == "__main__":
    asyncio.run(main())
