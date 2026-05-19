"""
opengui.skills.deeplink
~~~~~~~~~~~~~~~~~~~~~~~
Post-run Android deeplink discovery for code-first skills.

The discovery path is deliberately conservative: a candidate URI becomes a
skill only after it is launched on the device, observed, and matched against a
state contract inferred from the completed task's final screen.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shlex
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlsplit, urlunsplit

from opengui.action import Action
from opengui.observation import Observation
from opengui.skills.code_first import CodeSkillRepository
from opengui.skills.state_contract import evaluate_state_contract, normalize_state_contract

_LAUNCHER_PACKAGES = frozenset({
    "com.android.launcher",
    "com.android.launcher3",
    "com.google.android.apps.nexuslauncher",
    "com.miui.home",
})
_AUTH_GATE_TERMS = (
    "login",
    "log in",
    "sign in",
    "add email address",
    "登录",
    "登陆",
    "注册",
    "验证码",
    "同意并继续",
)
_WEAK_ANCHOR_TEXTS = frozenset({
    "more options",
    "更多选项",
    "ok",
    "cancel",
    "取消",
    "back",
    "返回",
    "navigate up",
    "close",
    "done",
})
_TASK_PROFILES: dict[str, dict[str, Any]] = {
    "order": {
        "needles": ("order", "orders", "订单"),
        "paths": ("order", "orders", "mall/order", "shop/order", "my/order", "user/order"),
        "query_keys": ("tab", "type", "source"),
        "query_value": "all",
    },
    "search": {
        "needles": ("search", "find", "query", "keyword", "搜", "搜索", "检索", "查找"),
        "paths": ("search", "search/", "search/result", "search/results", "find"),
        "query_keys": ("q", "query", "keyword", "text", "search"),
        "query_value": "test",
    },
    "profile": {
        "needles": ("profile", "account", "user", "me", "我的", "个人", "账号"),
        "paths": ("profile", "user", "me", "mine", "account", "member"),
        "query_keys": ("id", "uid", "user_id"),
        "query_value": "test",
    },
    "generic": {
        "needles": (),
        "paths": ("", "open", "home", "main"),
        "query_keys": ("target", "source"),
        "query_value": "opengui",
    },
}
_CONTACT_INTENT_PACKAGES = frozenset({
    "com.google.android.contacts",
    "com.android.contacts",
})
_CONTACT_ENTRY_PACKAGES = _CONTACT_INTENT_PACKAGES | frozenset({
    "com.google.android.dialer",
    "com.android.dialer",
})
_CLOCK_PACKAGES = frozenset({
    "com.google.android.deskclock",
    "com.android.deskclock",
})
_INTERNAL_URI_KINDS = frozenset({
    "internal_uri_intent",
})
_PROBE_UI_XML_PATH = "/sdcard/opengui-deeplink-probe.xml"


@dataclass(frozen=True)
class DeeplinkCandidate:
    uri: str
    kind: str
    package: str
    component: str | None = None
    source: str = "generated"
    confidence: float = 0.0
    action: str = "android.intent.action.VIEW"
    mime_type: str | None = None
    categories: tuple[str, ...] = ()
    extras: tuple[tuple[str, Any], ...] = ()
    flags: str | None = None
    raw_capture: tuple[tuple[str, Any], ...] = ()
    verified_component: str | None = None
    verified_package: str | None = None
    verified_action_type: str | None = None
    verified_launch_variant: str | None = None


@dataclass(frozen=True)
class ManifestIntentFilter:
    component: str
    actions: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    schemes: tuple[str, ...] = ()
    authorities: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapturedIntentSpec:
    action: str | None
    data_uri: str | None
    component: str | None
    categories: tuple[str, ...] = ()
    extras: tuple[tuple[str, Any], ...] = ()
    flags: str | None = None
    raw_intent_line: str = ""
    source: str = "dumpsys_activity"
    raw_capture_source: str = ""
    has_extras_marker: bool = False
    sample_count: int = 1


@dataclass(frozen=True)
class DeeplinkProbeRecord:
    uri: str
    kind: str
    status: str
    action: str = "android.intent.action.VIEW"
    matched: bool = False
    error: str | None = None
    component: str | None = None
    source: str | None = None
    confidence: float | None = None
    mime_type: str | None = None
    categories: tuple[str, ...] = ()
    extras: tuple[tuple[str, Any], ...] = ()
    launch_error_type: str | None = None
    foreground_app: str | None = None
    screenshot_path: str | None = None
    contract_eval: bool | None = None
    visible_text: tuple[str, ...] = ()
    content_desc: tuple[str, ...] = ()
    resource_ids: tuple[str, ...] = ()
    probe_plan: tuple[dict[str, Any], ...] = ()
    raw_capture: tuple[tuple[str, Any], ...] = ()
    pre_state: dict[str, Any] | None = None
    post_state: dict[str, Any] | None = None
    launch_variant: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "kind": self.kind,
            "status": self.status,
            "action": self.action,
            "matched": self.matched,
            "error": self.error,
            "component": self.component,
            "source": self.source,
            "confidence": self.confidence,
            "mime_type": self.mime_type,
            "categories": list(self.categories),
            "extras": dict(self.extras),
            "launch_error_type": self.launch_error_type,
            "foreground_app": self.foreground_app,
            "screenshot_path": self.screenshot_path,
            "contract_eval": self.contract_eval,
            "visible_text": list(self.visible_text),
            "content_desc": list(self.content_desc),
            "resource_ids": list(self.resource_ids),
            "probe_plan": list(self.probe_plan),
            "raw_capture": dict(self.raw_capture),
            "pre_state": self.pre_state,
            "post_state": self.post_state,
            "launch_variant": self.launch_variant,
        }


@dataclass(frozen=True)
class DeeplinkDiscoveryResult:
    status: str
    reason: str | None = None
    app: str | None = None
    contract: dict[str, Any] | None = None
    contract_source: str | None = None
    candidates: tuple[DeeplinkProbeRecord, ...] = ()
    updated_functions: tuple[str, ...] = ()
    compiled_skill_ids: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "app": self.app,
            "contract": self.contract,
            "contract_source": self.contract_source,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "updated_functions": list(self.updated_functions),
            "compiled_skill_ids": list(self.compiled_skill_ids),
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class DeeplinkDiscoveryConfig:
    max_candidates: int = 8
    max_verified: int = 1
    settle_seconds: float = 2.5
    screenshot_dir_name: str = "deeplink_probe"


async def discover_deeplink_skills_from_trace(
    trace_path: Path,
    *,
    backend: Any,
    task: str | None,
    platform: str,
    is_success: bool,
    store_root: Path,
    config: DeeplinkDiscoveryConfig | None = None,
) -> DeeplinkDiscoveryResult:
    """Probe Android deeplinks for a completed trace and store verified skills."""
    current = config or DeeplinkDiscoveryConfig()
    if not is_success:
        return _write_deeplink_result(
            trace_path,
            DeeplinkDiscoveryResult(status="skipped", reason="task_not_successful"),
        )
    if platform != "android" or getattr(backend, "platform", None) != "android":
        return _write_deeplink_result(
            trace_path,
            DeeplinkDiscoveryResult(status="skipped", reason="non_android_backend"),
        )

    events = _load_events(trace_path)
    final_observation = _latest_app_observation(events)
    if final_observation is None:
        return _write_deeplink_result(
            trace_path,
            DeeplinkDiscoveryResult(status="no_candidate", reason="missing_final_observation"),
        )

    app = _clean_app(final_observation.get("foreground_app") or final_observation.get("app"))
    if not app:
        return _write_deeplink_result(
            trace_path,
            DeeplinkDiscoveryResult(status="no_candidate", reason="missing_target_app"),
        )

    contract = _contract_from_observation(final_observation, app=app, task=task)
    contract_source = "final_observation" if contract else None
    if not contract:
        done_text = _latest_done_text(events)
        contract = _contract_from_text_summary(done_text, app=app, task=task)
        if contract:
            contract_source = "done_action_text"
    if not contract:
        return _write_deeplink_result(
            trace_path,
            DeeplinkDiscoveryResult(
                status="no_candidate",
                reason="weak_final_state_contract",
                app=app,
                contract_source="none",
            ),
        )

    candidates = await _build_candidates(
        backend,
        app=app,
        task=task,
        final_observation=final_observation,
        limit=current.max_candidates,
    )
    if not candidates:
        return _write_deeplink_result(
            trace_path,
            DeeplinkDiscoveryResult(
                status="no_candidate",
                reason="no_deeplink_candidates",
                app=app,
                contract=contract,
                contract_source=contract_source,
            ),
        )

    screenshot_dir = trace_path.parent / current.screenshot_dir_name
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    records: list[DeeplinkProbeRecord] = []
    verified: list[DeeplinkCandidate] = []
    for index, candidate in enumerate(candidates, start=1):
        if _candidate_requires_privileged_activity_start(candidate):
            records.append(_privileged_activity_probe_record(candidate))
            continue
        record = await _probe_candidate(
            backend,
            candidate,
            contract=contract,
            screenshot_path=screenshot_dir / f"deeplink_{index:02d}.png",
            settle_seconds=current.settle_seconds,
        )
        records.append(record)
        if record.matched:
            verified.append(_candidate_for_probe_record(candidate, record))
        if len(verified) >= current.max_verified:
            break

    if not verified:
        return _write_deeplink_result(
            trace_path,
            DeeplinkDiscoveryResult(
                status="no_candidate",
                reason="no_verified_deeplink",
                app=app,
                contract=contract,
                contract_source=contract_source,
                candidates=tuple(records),
            ),
        )

    result_contract = _verification_contract_for_candidate(verified[0], default_contract=contract)
    source = _code_for_verified_candidates(
        verified,
        app=app,
        task=task,
        contract=contract,
    )
    update = CodeSkillRepository(store_root).add_code(source, description_hint=task)
    updated_function_names = set(update.updated_functions)
    result = DeeplinkDiscoveryResult(
        status="processed_deeplink_code" if not update.errors else "code_compile_error",
        reason=None if not update.errors else "code_compile_error",
        app=app,
        contract=result_contract,
        contract_source=contract_source,
        candidates=tuple(records),
        updated_functions=tuple(update.updated_functions),
        compiled_skill_ids=tuple(
            skill.skill_id
            for skill in update.skills
            if skill.skill_id and (not updated_function_names or skill.name in updated_function_names)
        ),
        errors=tuple(update.errors),
    )
    return _write_deeplink_result(trace_path, result)


def _write_deeplink_result(trace_path: Path, result: DeeplinkDiscoveryResult) -> DeeplinkDiscoveryResult:
    try:
        (trace_path.parent / "deeplink_result.json").write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return result


def _load_events(trace_path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        with trace_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
    except OSError:
        return []
    return events


def _latest_app_observation(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        observation = event.get("observation")
        if not isinstance(observation, dict):
            continue
        app = _clean_app(observation.get("foreground_app") or observation.get("app"))
        if app and app not in _LAUNCHER_PACKAGES:
            return observation
    return None


def _latest_done_text(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        action = event.get("action")
        if not isinstance(action, dict):
            continue
        if action.get("action_type") != "done":
            continue
        text = str(action.get("text") or "").strip()
        if text:
            return text
    return None


def _clean_app(value: Any) -> str:
    return str(value or "").strip()


def _contract_from_observation(
    observation: dict[str, Any],
    *,
    app: str,
    task: str | None,
) -> dict[str, Any] | None:
    extra = observation.get("extra") if isinstance(observation.get("extra"), dict) else {}
    scored_elements: list[tuple[int, dict[str, Any]]] = []
    task_terms = _task_terms(task)

    ui_tree = extra.get("ui_tree")
    if isinstance(ui_tree, list):
        for node in ui_tree:
            if not isinstance(node, dict):
                continue
            resource_id = str(node.get("resource_id") or "").strip()
            content_desc = str(node.get("content_desc") or "").strip()
            text = str(node.get("text") or "").strip()
            if resource_id and not resource_id.startswith("android:id/"):
                scored_elements.append((
                    90 + _selector_task_score(resource_id, task_terms),
                    {"selector": {"resource_id": resource_id}, "state": ["visible"]},
                ))
            if content_desc and not _weak_anchor_text(content_desc):
                scored_elements.append((
                    70 + _selector_task_score(content_desc, task_terms),
                    {"selector": {"content_desc": content_desc}, "state": ["visible"]},
                ))
            if text and not _weak_anchor_text(text):
                scored_elements.append((
                    55 + _selector_task_score(text, task_terms),
                    {"selector": {"text": text}, "state": ["visible"]},
                ))

    for key, selector_key in (("visible_text", "text"), ("content_desc", "content_desc")):
        for value in _string_list(extra.get(key)):
            if _weak_anchor_text(value):
                continue
            if task_terms and not any(term in value.lower() for term in task_terms):
                continue
            scored_elements.append((
                65 + _selector_task_score(value, task_terms),
                {"selector": {selector_key: value}, "state": ["visible"]},
            ))
            break
        if scored_elements:
            break

    if not scored_elements:
        for key, selector_key in (("content_desc", "content_desc"), ("visible_text", "text")):
            for value in _string_list(extra.get(key)):
                if not _weak_anchor_text(value):
                    scored_elements.append((
                        40 + _selector_task_score(value, task_terms),
                        {"selector": {selector_key: value}, "state": ["visible"]},
                    ))
                    break
            if scored_elements:
                break

    if not scored_elements:
        for resource_id in _string_list(extra.get("resource_ids")):
            if resource_id.startswith("android:id/"):
                continue
            scored_elements.append((
                80 + _selector_task_score(resource_id, task_terms),
                {"selector": {"resource_id": resource_id}, "state": ["visible"]},
            ))
            break

    if not scored_elements:
        return None
    scored_elements.sort(key=lambda item: item[0], reverse=True)
    elements = _dedupe_contract_elements([element for _, element in scored_elements])
    if not elements:
        return None
    return normalize_state_contract({
        "anchor": {"app_package": app},
        "signature": {"required": elements[:2], "forbidden": []},
    })


def _contract_from_text_summary(
    summary: str | None,
    *,
    app: str,
    task: str | None,
) -> dict[str, Any] | None:
    anchors = _summary_contract_anchors(summary, task=task)
    if not anchors:
        return None
    return normalize_state_contract({
        "anchor": {"app_package": app},
        "signature": {
            "required": [
                {"selector": {"text": anchor}, "state": ["visible"]}
                for anchor in anchors[:2]
            ],
            "forbidden": [],
        },
    })


def _summary_contract_anchors(summary: str | None, *, task: str | None) -> tuple[str, ...]:
    text = str(summary or "").strip()
    if not text:
        return ()
    anchors: list[str] = []

    def add(value: str) -> None:
        cleaned = str(value or "").strip(" \t\r\n'\"“”‘’，。,.：:;；")
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"^(?:the|current|opened)\s+", "", cleaned, flags=re.IGNORECASE)
        if not cleaned or len(cleaned) > 40:
            return
        if _weak_anchor_text(cleaned):
            return
        lowered = cleaned.casefold()
        if lowered in {"task completed", "successfully completed the task"}:
            return
        anchors.append(cleaned)

    for quoted in re.findall(r"[\"'“”‘’]([^\"'“”‘’]{2,40})[\"'“”‘’]", text):
        add(quoted)

    for pattern in (
        r"\b(?:the|current)\s+([A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*){0,3})\s+page\b",
        r"\b([A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*){0,3})\s+page\b",
    ):
        for match in re.findall(pattern, text):
            add(match)

    for pattern in (
        r"(?:当前页面为|页面为|打开了|进入了|进入|显示了)[\"“']?([^\"'“”。，,.]{2,24})[\"”']?(?:页面|页|列表)?",
        r"([^\"'“”。，,.]{2,24})(?:页面|页|列表)(?:已经|已|现在)?(?:显示|打开|展示)",
    ):
        for match in re.findall(pattern, text):
            add(match)

    task_terms = _task_terms(task)
    for term in task_terms:
        if len(term) < 4 or term not in text.casefold():
            continue
        for token in re.findall(r"[A-Za-z][A-Za-z0-9]*(?:\s+[A-Za-z][A-Za-z0-9]*){0,2}", text):
            if term in token.casefold():
                add(token)

    return tuple(_dedupe(anchors))


def _weak_anchor_text(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    lowered = text.casefold()
    if lowered in _WEAK_ANCHOR_TEXTS:
        return True
    if _dynamic_text(text):
        return True
    return bool(re.fullmatch(r"[\W_]+|\d{1,4}", text))


def _selector_task_score(value: str, task_terms: tuple[str, ...]) -> int:
    lowered = str(value or "").casefold()
    return 20 if any(term and term in lowered for term in task_terms) else 0


def _dedupe_contract_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for element in elements:
        key = json.dumps(element.get("selector") or {}, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        result.append(element)
    return result


async def _build_candidates(
    backend: Any,
    *,
    app: str,
    task: str | None,
    final_observation: dict[str, Any] | None = None,
    limit: int,
) -> list[DeeplinkCandidate]:
    activity_hint = _activity_from_observation(final_observation)
    captured_specs = await _capture_current_intent_specs(backend, app=app, activity=activity_hint)

    candidates: list[DeeplinkCandidate] = []
    privileged_captures: list[DeeplinkCandidate] = []
    for spec in captured_specs:
        if not spec.data_uri:
            if spec.component:
                privileged_captures.append(DeeplinkCandidate(
                    uri="",
                    kind="captured_privileged_activity",
                    package=app,
                    component=spec.component,
                    source=spec.source,
                    confidence=0.05,
                    action=spec.action or "android.intent.action.VIEW",
                    categories=spec.categories,
                    extras=spec.extras,
                    flags=spec.flags,
                    raw_capture=_raw_capture_for_spec(spec),
                ))
            continue
        if not _usable_data_uri(spec.data_uri):
            continue
        # ``cmp=`` in dumpsys is useful provenance, but passing it back to
        # ``am start -n`` often fails for non-exported router activities.  Let
        # Android resolve the captured URI inside the target package first.
        candidates.append(DeeplinkCandidate(
            uri=spec.data_uri,
            kind="captured_intent",
            package=app,
            component=spec.component,
            source=spec.source,
            confidence=_captured_intent_confidence(spec, task=task),
            action=spec.action or "android.intent.action.VIEW",
            categories=spec.categories,
            extras=spec.extras,
            flags=spec.flags,
            raw_capture=_raw_capture_for_spec(spec),
        ))

    shortcut_candidates = _shortcut_intent_candidates(app=app, task=task)
    candidates.extend(shortcut_candidates)
    candidates.extend(privileged_captures)

    uri_candidates = [candidate for candidate in candidates if candidate.uri and _usable_data_uri(candidate.uri)]
    probeable_candidates = [candidate for candidate in uri_candidates if _candidate_is_probeable(candidate)]
    if (not uri_candidates or not probeable_candidates) and not shortcut_candidates:
        candidates.extend(await _manifest_inferred_candidates(
            backend,
            app=app,
            task=task,
            captured_specs=captured_specs,
        ))

    candidates = await _expand_resolved_candidates(backend, candidates, app=app)
    return _dedupe_candidates(candidates, limit=limit)


async def _package_profile(backend: Any, app: str) -> dict[str, Any]:
    run = getattr(backend, "_run", None)
    if not callable(run):
        return {"schemes": (), "hosts": (), "filters": (), "catch_all_router_components": {}}
    try:
        output = await run("shell", "dumpsys", "package", app, timeout=10.0)
    except Exception:
        return {"schemes": (), "hosts": (), "filters": (), "catch_all_router_components": {}}
    filters = _extract_manifest_intent_filters(output, app=app)
    return {
        "schemes": tuple(_dedupe([
            *(_extract_unique(r"scheme(?:=|:)\s*\"?([A-Za-z][A-Za-z0-9+.-]*)\"?", output)),
            *(scheme for item in filters for scheme in item.schemes),
        ])),
        "hosts": tuple(_dedupe([
            *(_extract_unique(r"(?:host|authority)(?:=|:)\s*\"?([A-Za-z0-9._-]+)\"?", output)),
            *(authority for item in filters for authority in item.authorities),
        ])),
        "filters": filters,
        "catch_all_router_components": _extract_catch_all_router_components(output, app=app),
    }


def _extract_manifest_intent_filters(output: str, *, app: str) -> tuple[ManifestIntentFilter, ...]:
    component_pattern = re.compile(rf"\s*[0-9a-fA-F]+\s+({re.escape(app)}/\S+)\s+filter\b")
    filters: list[ManifestIntentFilter] = []
    current_component: str | None = None
    current_block: list[str] = []

    def flush() -> None:
        if not current_component:
            return
        block = "\n".join(current_block)
        filters.append(ManifestIntentFilter(
            component=current_component,
            actions=tuple(_extract_unique(r"Action(?:=|:)\s*\"?([A-Za-z][A-Za-z0-9_.]*)\"?", block)),
            categories=tuple(_extract_unique(r"Category(?:=|:)\s*\"?([A-Za-z][A-Za-z0-9_.]*)\"?", block)),
            schemes=tuple(_extract_unique(r"Scheme(?:=|:)\s*\"?([A-Za-z][A-Za-z0-9+.-]*)\"?", block)),
            authorities=tuple(_extract_unique(r"(?:Authority|Host)(?:=|:)\s*\"?([A-Za-z0-9._-]+)\"?", block)),
            paths=tuple(_extract_manifest_paths(block)),
        ))

    for line in output.splitlines():
        match = component_pattern.match(line)
        if match:
            flush()
            current_component = match.group(1)
            current_block = [line.strip()]
            continue
        if current_component:
            current_block.append(line.strip())
    flush()
    return tuple(filters)


def _extract_manifest_paths(block: str) -> list[str]:
    values: list[str] = []
    for match in re.findall(r"Path(?:=|:).*?PatternMatcher\{[^:}]+:\s*([^}]+)}", block, flags=re.IGNORECASE):
        value = str(match).strip().strip('"')
        if value:
            values.append(value)
    for match in re.findall(r"Path(?:=|:)\s*\"?(/[^\"\s}]*)\"?", block, flags=re.IGNORECASE):
        value = str(match).strip().strip('"')
        if value and value not in values:
            values.append(value)
    return _dedupe(values)


def _shortcut_intent_candidates(*, app: str, task: str | None) -> list[DeeplinkCandidate]:
    lowered = (task or "").casefold()
    candidates: list[DeeplinkCandidate] = []
    if (
        app == "com.google.android.documentsui"
        and any(term in lowered for term in ("download", "downloads", "下载"))
    ):
        candidates.append(DeeplinkCandidate(
            uri="",
            kind="shortcut_intent",
            package=app,
            action="android.provider.action.VIEW_DOWNLOADS",
            source="shortcut_profile_downloads",
            confidence=0.82,
        ))
    if (
        app in _CLOCK_PACKAGES
        and any(term in lowered for term in ("timer", "timers", "计时器", "倒计时"))
    ):
        candidates.append(DeeplinkCandidate(
            uri="",
            kind="shortcut_intent",
            package=app,
            action="android.intent.action.SHOW_TIMERS",
            source="shortcut_profile_clock_show_timers",
            confidence=0.84,
        ))
    if (
        app in _CONTACT_ENTRY_PACKAGES
        and any(term in lowered for term in ("contact", "contacts", "联系人"))
        and any(term in lowered for term in ("create", "add", "new", "insert", "新建", "添加"))
    ):
        intent_package = app if app in _CONTACT_INTENT_PACKAGES else "com.google.android.contacts"
        candidates.append(DeeplinkCandidate(
            uri="",
            kind="shortcut_intent",
            package=intent_package,
            action="android.intent.action.INSERT",
            mime_type="vnd.android.cursor.dir/contact",
            source="shortcut_profile_contact_insert",
            confidence=0.8,
        ))
    return candidates


async def _manifest_inferred_candidates(
    backend: Any,
    *,
    app: str,
    task: str | None,
    captured_specs: tuple[CapturedIntentSpec, ...],
) -> list[DeeplinkCandidate]:
    profile: dict[str, Any] = {
        "schemes": (),
        "hosts": (),
        "filters": (),
        "catch_all_router_components": {},
    }
    try:
        profile = await _package_profile(backend, app=app)
    except Exception:
        pass

    filters: tuple[ManifestIntentFilter, ...] = tuple(profile.get("filters") or ())
    schemes: tuple[str, ...] = tuple(profile.get("schemes") or ())
    hosts: tuple[str, ...] = tuple(profile.get("hosts") or ())
    catch_all_router_components = dict(profile.get("catch_all_router_components") or {})

    task_profile = _profile_for_task(task)
    task_paths = tuple(
        path.strip()
        for path in task_profile["paths"]
        if str(path).strip()
    )
    route_paths = _router_paths_from_captured_specs(
        captured_specs,
        paths=tuple(f"/{path.lstrip('/')}" if path else "" for path in task_paths),
    )
    if not route_paths:
        route_paths = tuple(
            f"/{path.strip('/')}" for path in task_paths if path.strip()
        )

    candidates: list[DeeplinkCandidate] = []

    def mk_capture_data(*, generation_method: str) -> tuple[tuple[str, Any], ...]:
        return (
            ("manifest_source", "package_dumpsys"),
            ("manifest_schemes", schemes),
            ("manifest_hosts", hosts),
            ("generation_method", generation_method),
        )

    def add_candidate(
        *,
        uri: str,
        kind: str,
        confidence: float,
        generation_method: str,
        scheme: str | None = None,
    ) -> None:
        if not uri or not _usable_data_uri(uri):
            return
        candidate_kind = kind
        normalized_scheme = (scheme or "").casefold()
        if candidate_kind in {"manifest_exact_scheme_host_path", "manifest_scheme_host_path_guess"}:
            if normalized_scheme in {"content", "android-app", "internal"}:
                candidate_kind = "internal_uri_intent"
        candidates.append(DeeplinkCandidate(
            uri=uri,
            kind=candidate_kind,
            package=app,
            source=f"package_manifest_{kind}",
            confidence=confidence,
            action="android.intent.action.VIEW",
            raw_capture=mk_capture_data(generation_method=generation_method),
        ))

    def normalize_manifest_path(path: str) -> str:
        clean = str(path or "").strip()
        if not clean:
            return ""
        return clean if clean.startswith("/") else f"/{clean}"

    def normalize_task_path(path: str) -> str:
        clean = str(path or "").strip().strip("/")
        return clean

    if catch_all_router_components and route_paths:
        for scheme in _dedupe(sorted(catch_all_router_components.keys())):
            for route_path in route_paths:
                add_candidate(
                    uri=_open_router_path_uri(scheme, route_path),
                    kind="manifest_router",
                    confidence=0.65,
                    generation_method="router_path",
                )

    for manifest_filter in filters:
        for scheme in manifest_filter.schemes:
            for authority in manifest_filter.authorities:
                if not scheme or not authority:
                    continue
                if not manifest_filter.paths:
                    add_candidate(
                        uri=f"{scheme}://{authority}",
                        kind="manifest_exact_scheme_host_path",
                        confidence=0.60,
                        generation_method="scheme_host_path",
                        scheme=scheme,
                    )
                    continue
                for path in manifest_filter.paths:
                    normalized_path = normalize_manifest_path(path)
                    if not normalized_path:
                        add_candidate(
                            uri=f"{scheme}://{authority}",
                            kind="manifest_exact_scheme_host_path",
                            confidence=0.60,
                            generation_method="scheme_host_path",
                            scheme=scheme,
                        )
                        continue
                    add_candidate(
                        uri=f"{scheme}://{authority}{normalized_path}",
                        kind="manifest_exact_scheme_host_path",
                        confidence=0.60,
                        generation_method="scheme_host_path",
                        scheme=scheme,
                    )

    for manifest_filter in filters:
        candidate_schemes = tuple(_dedupe([
            *manifest_filter.schemes,
            *schemes,
        ]))
        for scheme in candidate_schemes:
            filter_authorities = tuple(_dedupe(manifest_filter.authorities))
            use_authorities = filter_authorities or tuple(_dedupe(hosts))
            if not use_authorities:
                for task_path in task_paths:
                    normalized_path = normalize_task_path(task_path)
                    if not normalized_path:
                        continue
                    add_candidate(
                        uri=f"{scheme}://{normalized_path}",
                        kind="manifest_scheme_host_path_guess",
                        confidence=0.50,
                        generation_method="scheme_host_path",
                        scheme=scheme,
                    )
                continue
            for authority in use_authorities:
                for task_path in task_paths:
                    normalized_path = normalize_task_path(task_path)
                    if not normalized_path:
                        continue
                    add_candidate(
                        uri=f"{scheme}://{authority}/{normalized_path}"
                        if authority
                        else f"{scheme}://{normalized_path}",
                        kind="manifest_scheme_host_path_guess",
                        confidence=0.50,
                        generation_method="scheme_host_path",
                        scheme=scheme,
                    )
    for scheme in schemes:
        for task_path in task_paths:
            normalized_path = normalize_task_path(task_path)
            if not normalized_path:
                continue
            add_candidate(
                uri=f"{scheme}://{normalized_path}",
                kind="manifest_scheme_host_path_guess",
                confidence=0.50,
                generation_method="scheme_host_path",
                scheme=scheme,
            )

    for scheme in _guess_schemes(app):
        if not scheme:
            continue
        for task_path in task_paths:
            normalized_path = normalize_task_path(task_path)
            if not normalized_path:
                continue
            add_candidate(
                uri=f"{scheme}://{normalized_path}",
                kind="manifest_guess_scheme_path",
                confidence=0.38,
                generation_method="guess_scheme",
                scheme=scheme,
            )

    return candidates



async def _expand_resolved_candidates(
    backend: Any,
    candidates: list[DeeplinkCandidate],
    *,
    app: str,
) -> list[DeeplinkCandidate]:
    expanded: list[DeeplinkCandidate] = []
    seen_resolved: set[tuple[str, str, str]] = set()
    for candidate in candidates:
        if candidate.kind == "captured_intent" or candidate.component:
            expanded.append(candidate)
            continue
        component = await _resolve_candidate_component(backend, candidate, app=candidate.package or app)
        if component:
            key = (candidate.action, candidate.uri, component)
            if key not in seen_resolved:
                seen_resolved.add(key)
                expanded.append(replace(
                    candidate,
                    component=component,
                    source=f"{candidate.source}_resolved",
                    confidence=min(candidate.confidence + 0.08, 0.99),
                ))
        expanded.append(candidate)
    return expanded


async def _resolve_candidate_component(
    backend: Any,
    candidate: DeeplinkCandidate,
    *,
    app: str,
) -> str | None:
    run = getattr(backend, "_run", None)
    if not callable(run):
        return None
    command = _resolve_activity_command(candidate)
    try:
        output = await run("shell", command, timeout=10.0)
    except Exception:
        return None
    return _parse_resolved_component(output, app=app)


def _resolve_activity_command(candidate: DeeplinkCandidate) -> str:
    args = ["cmd", "package", "resolve-activity", "--brief", "-a", candidate.action]
    if candidate.uri:
        args.extend(["-d", candidate.uri])
    if candidate.mime_type:
        args.extend(["-t", candidate.mime_type])
    for category in candidate.categories:
        args.extend(["-c", category])
    if candidate.package:
        args.extend(["-p", candidate.package])
    return " ".join(shlex.quote(arg) for arg in args)


def _parse_resolved_component(output: str, *, app: str) -> str | None:
    for line in output.splitlines():
        text = line.strip()
        if not text or "No activity found" in text:
            continue
        match = re.search(rf"({re.escape(app)}/[A-Za-z0-9_.$]+)", text)
        if match:
            return match.group(1)
    return None


def _extract_catch_all_router_components(output: str, *, app: str) -> dict[str, tuple[str, ...]]:
    component_pattern = re.compile(rf"\s*[0-9a-fA-F]+\s+({re.escape(app)}/\S+)\s+filter\b")
    components_by_scheme: dict[str, list[str]] = {}
    current_component: str | None = None
    current_block: list[str] = []

    def flush() -> None:
        if not current_component or "RouterActivity" not in current_component:
            return
        block = "\n".join(current_block)
        if "android.intent.action.VIEW" not in block or "android.intent.category.BROWSABLE" not in block:
            return
        if re.search(r"\b(?:Authority|Host|Path)(?:=|:)", block):
            return
        for scheme in _extract_unique(r"Scheme(?:=|:)\s*\"?([A-Za-z][A-Za-z0-9+.-]*)\"?", block):
            components_by_scheme.setdefault(scheme, []).append(current_component)

    for line in output.splitlines():
        match = component_pattern.match(line)
        if match:
            flush()
            current_component = match.group(1)
            current_block = [line.strip()]
            continue
        if current_component:
            current_block.append(line.strip())
    flush()

    return {
        scheme: tuple(_dedupe(components))
        for scheme, components in components_by_scheme.items()
    }


def _router_paths_from_captured_specs(
    specs: tuple[CapturedIntentSpec, ...],
    *,
    paths: tuple[str, ...],
) -> tuple[str, ...]:
    route_paths: list[str] = []
    normalized_paths = tuple(sorted(
        (
            f"/{path.strip('/')}"
            for path in paths
            if path and path.strip("/")
        ),
        key=len,
        reverse=True,
    ))
    for spec in specs:
        decoded = unquote(spec.data_uri or "")
        if not decoded:
            continue
        for path in normalized_paths:
            if path in decoded:
                route_paths.append(path)
    return tuple(_dedupe(route_paths))


def _open_router_path_uri(scheme: str, route_path: str) -> str:
    payload = json.dumps(
        {"protocol_type": "openRouterPath", "path": route_path},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"{scheme}://{quote(payload, safe='')}"


def _activity_from_observation(observation: dict[str, Any] | None) -> str | None:
    if not isinstance(observation, dict):
        return None
    for key in ("activity_class", "foreground_activity", "activity"):
        value = _clean_app(observation.get(key))
        if value:
            return value
    extra = observation.get("extra")
    if isinstance(extra, dict):
        for key in ("activity_class", "foreground_activity", "activity"):
            value = _clean_app(extra.get(key))
            if value:
                return value
    return None


async def _capture_current_intent_specs(
    backend: Any,
    *,
    app: str,
    activity: str | None,
) -> tuple[CapturedIntentSpec, ...]:
    run = getattr(backend, "_run", None)
    run_as_root = getattr(backend, "run_as_root", None)
    if not callable(run) and not callable(run_as_root):
        return ()

    specs: list[CapturedIntentSpec] = []
    seen: dict[tuple[str | None, str | None, str, str | None, tuple[tuple[str, Any], ...]], int] = {}

    def add_spec(spec: CapturedIntentSpec) -> None:
        key = (spec.data_uri, spec.component, spec.raw_intent_line, spec.flags, spec.extras)
        existing_index = seen.get(key)
        if existing_index is not None:
            existing = specs[existing_index]
            source = existing.source
            raw_capture_source = existing.raw_capture_source
            if str(spec.raw_capture_source or spec.source).startswith("root_"):
                source = spec.source
                raw_capture_source = spec.raw_capture_source or spec.source
            specs[existing_index] = replace(
                existing,
                source=source,
                raw_capture_source=raw_capture_source,
                sample_count=existing.sample_count + 1,
            )
            return
        seen[key] = len(specs)
        specs.append(spec)

    commands = _activity_capture_commands(app=app, activity=activity)
    if callable(run):
        for source, command in commands:
            try:
                output = await run("shell", command, timeout=10.0)
            except Exception:
                continue
            for spec in _parse_dumpsys_intent_specs(output, app=app, activity=activity, source=source):
                add_spec(spec)

    if callable(run_as_root):
        for source, command in commands:
            root_source = f"root_{source}"
            try:
                output = await run_as_root(command, timeout=10.0)
            except TypeError:
                try:
                    output = await run_as_root(command)
                except Exception:
                    continue
            except Exception:
                continue
            for spec in _parse_dumpsys_intent_specs(output, app=app, activity=activity, source=root_source):
                add_spec(replace(spec, source=root_source, raw_capture_source=root_source))
    return tuple(specs)


def _activity_capture_commands(app: str, activity: str | None) -> tuple[tuple[str, str], ...]:
    commands: list[tuple[str, str]] = []
    short_activity = activity.rsplit(".", 1)[-1] if activity else ""
    if _safe_shell_token(short_activity):
        commands.append((
            "dumpsys_activity_activity_grep",
            "dumpsys activity activities | "
            f"grep -F -B 2 -A 60 {shlex.quote(short_activity)} | head -80",
        ))
    if _safe_shell_token(app):
        commands.append((
            "dumpsys_activity_package_grep",
            "dumpsys activity activities | "
            f"grep -F -B 2 -A 60 {shlex.quote(app)} | head -120",
        ))
    commands.append(("dumpsys_activity_full", "dumpsys activity activities"))
    return tuple(commands)


def _safe_shell_token(value: str) -> bool:
    return bool(value and re.fullmatch(r"[A-Za-z0-9_.$/-]+", value))


def _parse_dumpsys_intent_specs(
    output: str,
    *,
    app: str,
    activity: str | None,
    source: str,
) -> tuple[CapturedIntentSpec, ...]:
    if not output:
        return ()

    lines = output.splitlines()
    intent_indices: set[int] = set()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("Intent {") and _intent_line_is_relevant(stripped, app=app, activity=activity):
            intent_indices.add(index)
        if _line_mentions_target(stripped, app=app, activity=activity):
            for nearby in range(index + 1, min(index + 12, len(lines))):
                if lines[nearby].strip().startswith("Intent {"):
                    intent_indices.add(nearby)
                    break

    specs: list[CapturedIntentSpec] = []
    for index in sorted(intent_indices):
        spec = _parse_intent_at(lines, index, source=source)
        if spec is not None:
            specs.append(spec)
    return tuple(specs)


def _intent_line_is_relevant(line: str, *, app: str, activity: str | None) -> bool:
    if app and app in line:
        return True
    if activity and activity in line:
        return True
    component = _extract_intent_field(line, "cmp")
    if component and component.startswith(f"{app}/"):
        return True
    return False


def _line_mentions_target(line: str, *, app: str, activity: str | None) -> bool:
    if app and app in line:
        return True
    if activity and activity in line:
        return True
    if activity:
        short_activity = activity.rsplit(".", 1)[-1]
        return bool(short_activity and short_activity in line)
    return False


def _parse_intent_at(lines: list[str], index: int, *, source: str) -> CapturedIntentSpec | None:
    intent_line = lines[index].strip()
    if not intent_line.startswith("Intent {"):
        return None
    categories = _parse_intent_categories(intent_line)
    block = lines[index:min(index + 50, len(lines))]
    extras = _parse_intent_extras(block)
    has_extras_marker = "(has extras)" in intent_line or _block_has_extras_marker(block)
    return CapturedIntentSpec(
        action=_extract_intent_field(intent_line, "act"),
        data_uri=_extract_intent_field(intent_line, "dat"),
        component=_extract_intent_field(intent_line, "cmp"),
        categories=categories,
        extras=extras,
        flags=_extract_intent_field(intent_line, "flg"),
        raw_intent_line=intent_line,
        source=source,
        raw_capture_source=source,
        has_extras_marker=has_extras_marker,
    )


def _extract_intent_field(line: str, field: str) -> str | None:
    match = re.search(rf"(?:^|\s){re.escape(field)}=([^\s}}]+)", line)
    if not match:
        return None
    value = match.group(1).strip().strip(",")
    return value or None


def _parse_intent_extras(block: list[str]) -> tuple[tuple[str, Any], ...]:
    full_text = "\n".join(block)
    extras: dict[str, Any] = {}
    bundle_content = _extract_bundle_content(full_text)
    if bundle_content is not None:
        _parse_bundle_content(bundle_content, extras)
    _parse_line_extras(block, extras)
    return tuple(extras.items())


def _block_has_extras_marker(block: list[str]) -> bool:
    return any(
        line.strip().casefold().startswith(("extras:", "extras={", "bundle[{"))
        for line in block
    )


def _extract_bundle_content(text: str) -> str | None:
    marker = re.search(r"\bbundle\s*:\s*\[?\{", text, flags=re.IGNORECASE)
    if marker:
        start = marker.end() - 1
        return _extract_delimited_block(text, start)

    marker = re.search(r"\bextras\s*:", text, flags=re.IGNORECASE)
    if not marker:
        return None
    open_brace = text.find("{", marker.end())
    if open_brace < 0:
        return None
    return _extract_delimited_block(text, open_brace)


def _extract_delimited_block(text: str, start: int) -> str | None:
    if start < 0 or start >= len(text):
        return None
    opener = text[start]
    closers = {"{": "}", "[": "]", "(": ")"}
    if opener not in closers:
        return None
    stack = [closers[opener]]
    cursor = start + 1
    while cursor < len(text):
        char = text[cursor]
        if char in "{[(":
            stack.append({"{": "}", "[": "]", "(": ")"}[char])
        elif stack and char == stack[-1]:
            stack.pop()
            if not stack:
                return text[start + 1:cursor]
        cursor += 1
    return None


def _parse_bundle_content(content: str, extras: dict[str, Any]) -> None:
    for pair in _split_top_level(content, ","):
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        clean_key = key.strip()
        if not clean_key or _is_intent_metadata_field(clean_key):
            continue
        extras.setdefault(clean_key, _coerce_extra_value(value))


def _parse_intent_categories(intent_line: str) -> tuple[str, ...]:
    raw = _extract_intent_field(intent_line, "cat")
    if not raw:
        return ()
    cleaned = raw.strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]
    parts = _split_top_level(cleaned, ",")
    return tuple(_dedupe([part.strip() for part in parts if part.strip()]))


def _split_top_level(text: str, separator: str) -> list[str]:
    parts: list[str] = []
    stack: list[str] = []
    current: list[str] = []
    pairs = {"{": "}", "[": "]", "(": ")"}
    for char in text:
        if char in pairs:
            stack.append(pairs[char])
            current.append(char)
            continue
        if stack and char == stack[-1]:
            stack.pop()
            current.append(char)
            continue
        if char == separator and not stack:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        if char != "\n":
            current.append(char)
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def _parse_line_extras(block: list[str], extras: dict[str, Any]) -> None:
    in_extras = False
    for line in block:
        trimmed = line.strip()
        if not trimmed:
            if in_extras:
                break
            continue
        lowered = trimmed.casefold()
        if lowered.startswith(("extras:", "extras={")) or trimmed == "extras:Bundle[{":
            in_extras = True
            continue
        if not in_extras:
            continue
        if (
            trimmed.startswith(("}", "]", "*"))
            or trimmed.startswith(("TASK", "ACTIVITY"))
            or trimmed.startswith("Hist #")
            or trimmed.startswith("Intent {")
        ):
            break
        bundle = _extract_bundle_content(trimmed)
        if bundle is not None:
            _parse_bundle_content(bundle, extras)
            continue
        _parse_extra_line(trimmed, extras)


def _parse_extra_line(line: str, extras: dict[str, Any]) -> None:
    typed_match = re.match(r"^([A-Za-z_][\w.]*)\s+\((\w+)\)\s*=\s*(.+)$", line)
    if typed_match is not None:
        key = typed_match.group(1).strip()
        _set_extra_value(extras, key, typed_match.group(3), declared_type=typed_match.group(2))
        return
    if "=" not in line:
        return
    key, value = line.split("=", 1)
    _set_extra_value(extras, key, value)


def _set_extra_value(
    extras: dict[str, Any],
    key: str,
    value: Any,
    *,
    declared_type: str | None = None,
) -> None:
    clean_key = key.strip()
    if not clean_key or _is_intent_metadata_field(clean_key):
        return
    if not re.fullmatch(r"[A-Za-z_][\w.]*", clean_key):
        return
    extras.setdefault(clean_key, _coerce_extra_value(value, declared_type=declared_type))


def _coerce_extra_value(value: Any, *, declared_type: str | None = None) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip().strip('"')
    declared = (declared_type or "").casefold()
    if declared in {"string", "charsequence"}:
        return text
    if declared in {"boolean", "bool"}:
        return text.casefold() == "true"
    if declared in {"integer", "int", "long"}:
        try:
            return int(text)
        except ValueError:
            return text
    if declared in {"float", "double"}:
        try:
            return float(text)
        except ValueError:
            return text
    lowered = text.casefold()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.fullmatch(r"[-+]?\d+", text):
        try:
            return int(text)
        except ValueError:
            return text
    if re.fullmatch(r"[-+]?(?:(?:\d+\.\d*)|(?:\.\d+))(?:[eE][-+]?\d+)?", text) or re.fullmatch(
        r"[-+]?\d+[eE][-+]?\d+",
        text,
    ):
        try:
            return float(text)
        except ValueError:
            return text
    return text


def _is_intent_metadata_field(key: str) -> bool:
    return key in {
        "act",
        "dat",
        "cmp",
        "flg",
        "pkg",
        "cat",
        "clip",
        "bnds",
        "flags",
    }


def _usable_data_uri(uri: str) -> bool:
    try:
        return bool(urlparse(uri).scheme)
    except Exception:
        return False


def _captured_intent_confidence(spec: CapturedIntentSpec, *, task: str | None) -> float:
    confidence = 0.88
    if spec.component:
        confidence += 0.06
    if spec.extras:
        confidence += 0.03
    confidence += _uri_task_bonus(spec.data_uri or "", task)
    return min(confidence, 0.99)


def _am_start_command_for_intent(
    *,
    action: str | None,
    data_uri: str | None,
    categories: Iterable[str] = (),
    component: str | None = None,
    package: str | None = None,
    mime_type: str | None = None,
    extras: Iterable[tuple[str, Any]] = (),
) -> str:
    args = ["am", "start"]
    if action:
        args.extend(["-a", action])
    if data_uri:
        args.extend(["-d", data_uri])
    if mime_type:
        args.extend(["-t", mime_type])
    for category in categories:
        if category:
            args.extend(["-c", category])
    if component:
        args.extend(["-n", component])
    if package:
        args.extend(["-p", package])
    for key, value in extras:
        if not key:
            continue
        flag = _am_start_extra_flag(value)
        args.extend([flag, key, _am_start_extra_value(value)])
    return " ".join(shlex.quote(str(arg)) for arg in args)


def _am_start_extra_flag(value: Any) -> str:
    if isinstance(value, bool):
        return "--ez"
    if isinstance(value, int) and not isinstance(value, bool):
        if -2147483648 <= value <= 2147483647:
            return "--ei"
        return "--el"
    if isinstance(value, float):
        return "--ef"
    return "--es"


def _am_start_extra_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _raw_capture_for_spec(spec: CapturedIntentSpec) -> tuple[tuple[str, Any], ...]:
    source = spec.raw_capture_source or spec.source
    captured_via_root = str(source).startswith("root_")
    command = _am_start_command_for_intent(
        action=spec.action,
        data_uri=spec.data_uri,
        categories=spec.categories,
        component=spec.component,
        extras=spec.extras,
    )
    command_without_component = _am_start_command_for_intent(
        action=spec.action,
        data_uri=spec.data_uri,
        categories=spec.categories,
        component=None,
        extras=spec.extras,
    )
    typed_count = sum(1 for _, value in spec.extras if not isinstance(value, str))
    return (
        ("source", source),
        ("raw_intent_line", spec.raw_intent_line),
        ("raw_intent_fingerprint", _short_hash(spec.raw_intent_line)),
        ("sample_count", spec.sample_count),
        ("am_start_command", command),
        ("am_start_command_without_component", command_without_component),
        ("captured_via_root", captured_via_root),
        ("flags", spec.flags),
        ("has_extras_marker", spec.has_extras_marker),
        ("extras_count", len(spec.extras)),
        ("extras_typed_count", typed_count),
        ("requires_privileged_activity_start", bool(spec.component and not spec.data_uri)),
    )


def _uri_task_bonus(uri: str, task: str | None) -> float:
    lowered = uri.lower()
    matches = sum(1 for term in _task_terms(task) if term and term in lowered)
    return min(matches * 0.03, 0.09)


def _verification_contract_for_candidate(
    candidate: DeeplinkCandidate,
    *,
    default_contract: dict[str, Any],
) -> dict[str, Any]:
    if candidate.source.startswith("shortcut_profile_contact_insert"):
        return normalize_state_contract({
            "anchor": {"app_package": candidate.package},
            "signature": {
                "required": [
                    {
                        "selector": {
                            "resource_id": "com.google.android.contacts:id/contact_editor_fragment"
                        },
                        "state": ["visible"],
                    },
                    {"selector": {"text": "Create contact"}, "state": ["visible"]},
                ],
                "forbidden": [],
            },
        }) or default_contract
    if candidate.source.startswith("shortcut_profile_downloads"):
        return normalize_state_contract({
            "anchor": {"app_package": candidate.package},
            "signature": {
                "required": [
                    {"selector": {"text": "Downloads"}, "state": ["visible"]},
                ],
                "forbidden": [],
            },
        }) or default_contract
    if candidate.source.startswith("shortcut_profile_clock_show_timers"):
        return normalize_state_contract({
            "anchor": {"app_package": candidate.package},
            "signature": {
                "required": [
                    {"selector": {"text": "Timer"}, "state": ["visible"]},
                    {"selector": {"text": "00h 00m 00s"}, "state": ["visible"]},
                ],
                "forbidden": [],
            },
        }) or default_contract
    return default_contract


def _has_ui_evidence(extra: dict[str, Any]) -> bool:
    return any(
        _string_list(extra.get(key))
        for key in ("visible_text", "content_desc", "resource_ids")
    ) or bool(extra.get("ui_tree"))


async def _collect_probe_ui_extra(backend: Any) -> dict[str, Any]:
    run = getattr(backend, "_run", None)
    if not callable(run):
        return {}
    try:
        await run(
            "shell",
            "uiautomator",
            "dump",
            "--compressed",
            _PROBE_UI_XML_PATH,
            timeout=6.0,
        )
        xml_text = await run("shell", "cat", _PROBE_UI_XML_PATH, timeout=6.0)
    except Exception:
        return {}
    return _parse_probe_ui_tree_xml(xml_text)


async def _collect_probe_state(
    backend: Any,
    *,
    observation: Observation | None = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {}
    if observation is not None:
        state["foreground_app"] = _clean_app(observation.foreground_app)
        extra = observation.extra if isinstance(observation.extra, dict) else {}
        for key in ("top_activity", "top_activity_task", "activity", "activity_class"):
            value = _clean_app(extra.get(key))
            if value:
                state[key] = value
    run = getattr(backend, "_run", None)
    if callable(run):
        try:
            activity_output = await run("shell", "dumpsys", "activity", "activities", timeout=6.0)
            parsed_state = _parse_activity_state(activity_output)
            state.update(parsed_state)
        except Exception:
            pass
    return state


def _parse_activity_state(output: str) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for line in output.splitlines():
        if not line:
            continue
        if "mFocusedActivity" in line:
            for key in ("mFocusedActivity", "mFocusedActivity="):
                if key in line:
                    marker = line.split(key, 1)[-1]
                    parts = marker.split()
                    if parts:
                        for part in parts:
                            if "/" in part:
                                state.setdefault("top_activity", part.strip("{}"))
                                state.setdefault("foreground_app", _clean_app(part.split("/", 1)[0]))
                                break
                    break
        match = re.search(
            r"ActivityRecord\{[0-9A-Fa-f]+\s+(?:u\d+\s+)?([A-Za-z0-9_.$-]+/\S+)\s+t(\d+)",
            line,
        )
        if match and "top_activity" not in state:
            state["top_activity"] = match.group(1)
            state["top_activity_task"] = match.group(2)
            if "/" in match.group(1):
                state.setdefault("foreground_app", match.group(1).split("/", 1)[0])
        if "topActivity" in line and not state.get("top_activity"):
            if " " in line:
                for token in line.split():
                    if "/" in token:
                        state["top_activity"] = token.strip()
                        if "/" in token:
                            state.setdefault("foreground_app", token.split("/", 1)[0].strip())
                            break
    return state


def _activity_changed(pre_state: dict[str, Any], post_state: dict[str, Any]) -> bool:
    if not pre_state:
        return True
    pre_fg = pre_state.get("foreground_app")
    post_fg = post_state.get("foreground_app")
    if pre_fg and post_fg and post_fg != pre_fg:
        return True
    pre_top = pre_state.get("top_activity")
    post_top = post_state.get("top_activity")
    if pre_top and post_top and post_top != pre_top:
        return True
    return pre_fg != post_fg and bool(pre_fg and post_fg)


def _matches_expected_package(
    state: dict[str, Any],
    expected_app: str | None,
) -> bool:
    if not expected_app:
        return True
    top_activity = _clean_app(state.get("top_activity"))
    if top_activity:
        return top_activity.startswith(f"{expected_app}/")
    top_task = _clean_app(state.get("top_activity_task"))
    if top_task:
        return top_task.startswith(f"{expected_app}:")
    app = _clean_app(state.get("foreground_app"))
    return app == expected_app


def _build_probe_plan(candidate: DeeplinkCandidate, *, include_app_context: bool = False) -> list[dict[str, Any]]:
    entry_type = _entry_type(candidate)
    plans: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None, bool, str]] = set()

    def add_attempt(
        component: str | None,
        package: str | None,
        *,
        implicit_package: bool = False,
        transport: str = "adb",
    ) -> None:
        key = (component, package, implicit_package, transport)
        if key in seen:
            return
        seen.add(key)
        plans.append({
            "attempt": len(plans) + 1,
            "action_type": "open_deeplink" if entry_type == "deeplink" else "open_intent",
            "intent_action": None if entry_type == "deeplink" else candidate.action,
            "component": component,
            "package": package,
            "implicit_package": implicit_package,
            "no_wait": False,
            "transport": transport,
        })

    if entry_type == "deeplink":
        if candidate.package:
            add_attempt(component=None, package=candidate.package, implicit_package=False)
            if include_app_context:
                add_attempt(
                    component=None,
                    package=candidate.package,
                    implicit_package=False,
                    transport="app_context",
                )
            if candidate.component:
                add_attempt(component=candidate.component, package=candidate.package, implicit_package=False)
                if include_app_context:
                    add_attempt(
                        component=candidate.component,
                        package=candidate.package,
                        implicit_package=False,
                        transport="app_context",
                    )
            if candidate.package:
                add_attempt(component=None, package=None, implicit_package=True)
        elif candidate.component:
            add_attempt(component=candidate.component, package=None, implicit_package=True)
            if include_app_context:
                add_attempt(
                    component=candidate.component,
                    package=None,
                    implicit_package=True,
                    transport="app_context",
                )
        else:
            add_attempt(component=None, package=None, implicit_package=True)
    else:
        add_attempt(component=candidate.component, package=candidate.package, implicit_package=False)
        if include_app_context and (candidate.package or candidate.component):
            add_attempt(
                component=candidate.component,
                package=candidate.package,
                implicit_package=False,
                transport="app_context",
            )
        if candidate.component:
            add_attempt(component=None, package=candidate.package, implicit_package=False)
            if include_app_context and candidate.package:
                add_attempt(
                    component=None,
                    package=candidate.package,
                    implicit_package=False,
                    transport="app_context",
                )
        if candidate.package:
            add_attempt(component=None, package=None, implicit_package=True)

    return plans


def _build_probe_record_entry(
    *,
    attempt: int,
    action: Action,
    attempt_kind: str,
    pre_state: dict[str, Any],
    post_state: dict[str, Any],
    status: str,
    error: str | None = None,
    launch_variant: str | None = None,
    transport: str = "adb",
) -> dict[str, Any]:
    transport = "app_context" if launch_variant == "app_context" else transport
    actual_package = (
        None
        if launch_variant and launch_variant.startswith("browser_redirect")
        else action.package
    )
    return {
        "attempt": attempt,
        "action_type": action.action_type,
        "intent_action": attempt_kind,
        "package": actual_package,
        "requested_package": action.package,
        "component": action.component,
        "implicit_package": actual_package is None,
        "no_wait": False,
        "transport": transport,
        "status": status,
        "error": error,
        "launch_variant": launch_variant,
        "pre_state": pre_state,
        "post_state": post_state,
    }


def _candidate_requires_privileged_activity_start(candidate: DeeplinkCandidate) -> bool:
    raw_capture = dict(candidate.raw_capture)
    return (
        not candidate.uri
        and bool(candidate.component)
        and (
            candidate.kind == "captured_privileged_activity"
            or bool(raw_capture.get("requires_privileged_activity_start"))
        )
    )


def _privileged_activity_probe_record(candidate: DeeplinkCandidate) -> DeeplinkProbeRecord:
    return DeeplinkProbeRecord(
        uri=candidate.uri,
        kind=candidate.kind,
        status="requires_privileged_activity_start",
        action=candidate.action,
        matched=False,
        error="component-only captured Activity requires privileged replay; skipped",
        component=candidate.component,
        source=candidate.source,
        confidence=candidate.confidence,
        mime_type=candidate.mime_type,
        categories=candidate.categories,
        extras=candidate.extras,
        launch_error_type="requires_privileged_activity_start",
        probe_plan=({
            "attempt": 1,
            "action_type": "root_replay",
            "intent_action": candidate.action,
            "package": candidate.package,
            "component": candidate.component,
            "status": "skipped",
            "requires_privileged_activity_start": True,
        },),
        raw_capture=candidate.raw_capture,
    )


def _collect_probe_observation_text(extra: dict[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(_string_list(extra.get("visible_text"))[:30]),
        tuple(_string_list(extra.get("content_desc"))[:30]),
        tuple(_string_list(extra.get("resource_ids"))[:30]),
    )


def _first_verified_probe_attempt(plan: tuple[dict[str, Any], ...]) -> dict[str, Any] | None:
    for attempt in reversed(plan):
        if attempt.get("status") == "target_verified":
            return attempt
    return None


def _build_attempt_status(
    *,
    expected_app: str | None,
    pre_state: dict[str, Any],
    post_state: dict[str, Any],
    contract_eval: bool | None,
    visible_text: tuple[str, ...],
    content_desc: tuple[str, ...],
) -> str:
    if not post_state:
        return "no_observation"
    if expected_app and not _matches_expected_package(post_state, expected_app):
        return "wrong_app"
    if _is_auth_gate((*visible_text, *content_desc)):
        return "auth_gate"
    if contract_eval is True:
        if _activity_changed(pre_state, post_state) or not pre_state:
            return "target_verified"
        return "no_navigation"
    if contract_eval is False:
        return "contract_mismatch"
    return "unverified"


def _parse_probe_ui_tree_xml(xml_text: str) -> dict[str, Any]:
    try:
        root = ET.fromstring(str(xml_text or "").strip())
    except ET.ParseError:
        return {}
    visible_text: list[str] = []
    content_desc: list[str] = []
    resource_ids: list[str] = []
    ui_tree: list[dict[str, Any]] = []
    node_count = 0
    for element in root.iter("node"):
        node_count += 1
        text = _clean_xml_attr(element.get("text"))
        desc = _clean_xml_attr(element.get("content-desc"))
        resource_id = _clean_xml_attr(element.get("resource-id"))
        class_name = _clean_xml_attr(element.get("class"))
        clickable = element.get("clickable") == "true"
        enabled = element.get("enabled") == "true"
        focused = element.get("focused") == "true"
        scrollable = element.get("scrollable") == "true"
        if text:
            visible_text.append(text)
        if desc:
            content_desc.append(desc)
        if resource_id:
            resource_ids.append(resource_id)
        if len(ui_tree) < 80 and (text or desc or resource_id or class_name):
            node: dict[str, Any] = {}
            if text:
                node["text"] = text
            if desc:
                node["content_desc"] = desc
            if resource_id:
                node["resource_id"] = resource_id
            if class_name:
                node["class"] = class_name
            if clickable:
                node["clickable"] = True
            if enabled:
                node["enabled"] = True
            if focused:
                node["focused"] = True
            if scrollable:
                node["scrollable"] = True
            ui_tree.append(node)
    result: dict[str, Any] = {
        "ui_tree_node_count": node_count,
        "ui_tree_probe_fallback": True,
    }
    if visible_text:
        result["visible_text"] = _dedupe(visible_text)[:80]
    if content_desc:
        result["content_desc"] = _dedupe(content_desc)[:80]
    if resource_ids:
        result["resource_ids"] = _dedupe(resource_ids)[:80]
    if ui_tree:
        result["ui_tree"] = ui_tree
    return result


def _clean_xml_attr(value: Any) -> str:
    return str(value or "").strip()


def _backend_supports_app_context_launcher(backend: Any) -> bool:
    supports = getattr(backend, "supports_app_context_launcher", None)
    if callable(supports):
        try:
            return bool(supports())
        except Exception:
            return False
    return bool(
        callable(getattr(backend, "open_deeplink_app_context", None))
        or callable(getattr(backend, "open_intent_app_context", None))
    )


async def _execute_probe_launch(
    backend: Any,
    action: Action,
    attempt_spec: dict[str, Any],
    *,
    timeout: float,
) -> str:
    if attempt_spec.get("transport") != "app_context":
        return await backend.execute(action, timeout=timeout)

    if action.action_type == "open_deeplink":
        launcher = getattr(backend, "open_deeplink_app_context", None)
    else:
        launcher = getattr(backend, "open_intent_app_context", None)
    if not callable(launcher):
        raise RuntimeError("app-context launcher is not available for this backend")
    return await launcher(action, timeout=timeout)


async def _probe_candidate(
    backend: Any,
    candidate: DeeplinkCandidate,
    *,
    contract: dict[str, Any],
    screenshot_path: Path,
    settle_seconds: float,
) -> DeeplinkProbeRecord:
    error: str | None = None
    verification_contract = _verification_contract_for_candidate(candidate, default_contract=contract)
    expected_app = _clean_app(
        verification_contract.get("anchor", {}).get("app_package")
        if isinstance(verification_contract.get("anchor"), dict)
        else None
    ) or candidate.package
    try:
        await backend.execute(Action(action_type="home"), timeout=5.0)
    except Exception:
        pass
    try:
        await backend.execute(Action(action_type="close_app", text=candidate.package), timeout=5.0)
    except Exception:
        pass

    probe_plan: list[dict[str, Any]] = []
    final_status = "no_attempt"
    final_pre_state: dict[str, Any] | None = None
    final_post_state: dict[str, Any] | None = None
    final_visible_text: tuple[str, ...] = ()
    final_content_desc: tuple[str, ...] = ()
    final_resource_ids: tuple[str, ...] = ()
    final_contract_eval: bool | None = None
    final_launch_variant: str | None = None

    include_app_context = _backend_supports_app_context_launcher(backend)
    for attempt_spec in _build_probe_plan(candidate, include_app_context=include_app_context):
        action = _action_for_candidate(
            candidate,
            component=attempt_spec["component"],
            package=attempt_spec["package"],
        )
        pre_state = await _collect_probe_state(backend)
        if final_pre_state is None:
            final_pre_state = pre_state
        attempt_error: str | None = None
        observation: Observation | None = None
        post_state: dict[str, Any] | None = None
        visible_text: tuple[str, ...] = ()
        content_desc: tuple[str, ...] = ()
        resource_ids: tuple[str, ...] = ()
        contract_eval: bool | None = None
        launch_variant: str | None = None
        status: str

        try:
            launch_output = await _execute_probe_launch(backend, action, attempt_spec, timeout=10.0)
            launch_variant = (
                _extract_launch_variant(launch_output)
                or str(attempt_spec.get("transport") or "primary")
            )
            await asyncio.sleep(settle_seconds)
            observation = await backend.observe(screenshot_path, timeout=8.0)
            extra = observation.extra or {}
            if not _has_ui_evidence(extra):
                fallback_extra = await _collect_probe_ui_extra(backend)
                if fallback_extra:
                    extra = {**extra, **fallback_extra}
                    observation.extra = extra
            visible_text, content_desc, resource_ids = _collect_probe_observation_text(extra)
            contract_eval = evaluate_state_contract(verification_contract, observation=observation)
            post_state = await _collect_probe_state(backend, observation=observation)
            status = _build_attempt_status(
                expected_app=expected_app,
                pre_state=pre_state,
                post_state=post_state,
                contract_eval=contract_eval,
                visible_text=visible_text,
                content_desc=content_desc,
            )
            if status == "unverified" and launch_variant == "browser_redirect":
                status = "redirect_unverified"
        except Exception as exc:
            error = error or str(exc)
            attempt_error = str(exc)
            launch_variant = _extract_launch_variant(attempt_error)
            status = _classify_launch_error(attempt_error)
            if attempt_error:
                post_state = await _collect_probe_state(backend)

        attempt_entry = _build_probe_record_entry(
            attempt=attempt_spec["attempt"],
            action=action,
            attempt_kind=attempt_spec["intent_action"] or _entry_type(candidate),
            pre_state=pre_state,
            post_state=post_state or {},
            status=status,
            error=attempt_error,
            launch_variant=launch_variant,
            transport=str(attempt_spec.get("transport") or "adb"),
        )
        probe_plan.append(attempt_entry)
        final_post_state = post_state
        final_visible_text = visible_text
        final_content_desc = content_desc
        final_resource_ids = resource_ids
        final_contract_eval = contract_eval
        final_launch_variant = launch_variant
        final_status = status
        if status == "target_verified":
            break

    matched_attempt = _first_verified_probe_attempt(tuple(probe_plan))
    matched_component = matched_attempt["component"] if matched_attempt else None
    matched_package = matched_attempt["package"] if matched_attempt else None
    matched_launch_variant = matched_attempt.get("launch_variant") if matched_attempt else None
    matched_foreground_app = (
        _clean_app(
            final_post_state.get("foreground_app")
            if isinstance(final_post_state, dict)
            else None
        )
        if final_post_state is not None
        else None
    )
    return DeeplinkProbeRecord(
        uri=candidate.uri,
        kind=candidate.kind,
        status=final_status,
        action=candidate.action,
        matched=final_status == "target_verified",
        component=matched_component,
        source=candidate.source,
        confidence=candidate.confidence,
        mime_type=candidate.mime_type,
        categories=candidate.categories,
        extras=candidate.extras,
        launch_error_type=final_status if final_status.startswith("launch_error") else None,
        foreground_app=matched_foreground_app,
        screenshot_path=str(screenshot_path),
        contract_eval=final_contract_eval,
        visible_text=final_visible_text,
        content_desc=final_content_desc,
        resource_ids=final_resource_ids,
        probe_plan=tuple(probe_plan),
        raw_capture=candidate.raw_capture,
        pre_state=final_pre_state,
        post_state=final_post_state,
        launch_variant=matched_launch_variant or final_launch_variant,
        error=error,
    )


def _action_for_candidate(
    candidate: DeeplinkCandidate,
    *,
    component: str | None,
    package: str | None,
) -> Action:
    if _entry_type(candidate) == "deeplink":
        return Action(
            action_type="open_deeplink",
            text=candidate.uri,
            component=component,
            package=package,
        )
    return Action(
        action_type="open_intent",
        text=candidate.uri or None,
        intent_action=candidate.action,
        mime_type=candidate.mime_type,
        component=component,
        package=package,
        categories=candidate.categories,
        extras=candidate.extras,
    )


def _classify_launch_error(error: str) -> str:
    lowered = error.lower()
    if "securityexception" in lowered or "permission denial" in lowered or "permission" in lowered:
        return "launch_error_security"
    if "timeout" in lowered or "timed out" in lowered:
        return "launch_error_timeout"
    if (
        "activitynotfound" in lowered
        or "unable to resolve intent" in lowered
        or "no activity found" in lowered
        or "activity not started" in lowered
    ):
        return "launch_error_activity_not_found"
    if "parse" in lowered:
        return "launch_error_parse_fail"
    return "launch_error_unknown"


def _extract_launch_variant(output: Any) -> str | None:
    match = re.search(r"\[opengui_launch_variant=([A-Za-z0-9_:-]+)\]", str(output or ""))
    if not match:
        return None
    return match.group(1)


def _entry_type(candidate: DeeplinkCandidate) -> str:
    if candidate.kind in _INTERNAL_URI_KINDS:
        return "internal_uri_intent"
    if candidate.kind == "captured_intent":
        scheme = urlparse(candidate.uri or "").scheme.casefold()
        if scheme in {"content", "android-app"}:
            return "internal_uri_intent"
    if candidate.action == "android.intent.action.VIEW" and candidate.uri:
        return "deeplink"
    return "intent"


def _profile_for_task(task: str | None) -> dict[str, Any]:
    lowered = (task or "").lower()
    for profile in _TASK_PROFILES.values():
        if any(needle and needle in lowered for needle in profile["needles"]):
            return profile
    return _TASK_PROFILES["generic"]


def _task_terms(task: str | None) -> tuple[str, ...]:
    lowered = (task or "").lower()
    terms = [
        token
        for token in re.split(r"[\s,，。:：/]+", lowered)
        if len(token) >= 2 and not token.isdigit()
    ]
    for profile in _TASK_PROFILES.values():
        if any(needle and needle in lowered for needle in profile["needles"]):
            terms.extend(str(needle).lower() for needle in profile["needles"] if needle)
    return tuple(_dedupe(terms))


def _guess_schemes(app: str) -> tuple[str, ...]:
    parts = [part for part in app.split(".") if part]
    guesses: list[str] = []
    if parts:
        guesses.append(parts[-1])
    if len(parts) >= 2:
        guesses.append("".join(parts[-2:]))
    normalized = re.sub(r"[^a-z0-9]+", "", app.lower())
    if normalized:
        guesses.append(normalized)
    return tuple(_dedupe(guesses))


def _candidate_for_probe_record(
    candidate: DeeplinkCandidate,
    record: DeeplinkProbeRecord,
) -> DeeplinkCandidate:
    if not record.matched:
        return candidate
    attempt = _first_verified_probe_attempt(record.probe_plan)
    if attempt is None:
        return candidate
    return replace(
        candidate,
        verified_component=attempt.get("component"),
        verified_package=attempt.get("package"),
        verified_action_type=attempt.get("action_type"),
        verified_launch_variant=attempt.get("launch_variant"),
    )


def _code_for_verified_candidates(
    candidates: list[DeeplinkCandidate],
    *,
    app: str,
    task: str | None,
    contract: dict[str, Any],
) -> str:
    lines = [
        "from __future__ import annotations",
        "",
        "from opengui.skills.code_graph import C, action, skill",
        "",
        "",
    ]
    for candidate in candidates:
        has_verified_variant = candidate.verified_action_type is not None
        skill_app = candidate.verified_package or candidate.package or app
        fixed_package = (
            candidate.verified_package
            if has_verified_variant
            else (candidate.package or app)
        )
        candidate_contract = _verification_contract_for_candidate(candidate, default_contract=contract)
        function_name = _function_name(skill_app, candidate)
        entry_type = _entry_type(candidate)
        candidate_component = (
            candidate.verified_component
            if has_verified_variant
            else candidate.component
        )
        action_type = candidate.verified_action_type or ("open_deeplink" if entry_type == "deeplink" else "open_intent")
        is_uri_deeplink = action_type == "open_deeplink"
        skill_prefix = entry_type
        skill_id = f"{skill_prefix}:{skill_app}:{_short_hash(_candidate_identity(candidate))}"
        if is_uri_deeplink:
            fixed_values: dict[str, Any] = {"text": candidate.uri}
        else:
            fixed_values = {}
        if fixed_package:
            fixed_values["package"] = fixed_package
        if not is_uri_deeplink:
            fixed_values["intent_action"] = candidate.action
            if candidate.uri:
                fixed_values["text"] = candidate.uri
            if candidate.mime_type:
                fixed_values["mime_type"] = candidate.mime_type
            if candidate.categories:
                fixed_values["categories"] = list(candidate.categories)
            if candidate.extras:
                fixed_values["extras"] = dict(candidate.extras)
        if candidate_component:
            fixed_values["component"] = candidate_component
        provenance = {
            "behavior_intent": task or app,
            "launch_mode": entry_type,
            "source": candidate.source,
            "component": candidate_component,
            "verified_action_type": action_type,
            "verified_launch_variant": candidate.verified_launch_variant,
            "confidence": round(candidate.confidence, 3),
        }
        tag_head = entry_type
        description = f"Open verified {tag_head} start for: {task or app}; provenance={json.dumps(provenance, sort_keys=True)}"
        lines.extend([
            "@skill(",
            f"    app={skill_app!r},",
            "    platform='android',",
            f"    tags={tuple(dict.fromkeys((tag_head, 'verified', candidate.source)))!r},",
            f"    skill_id={skill_id!r},",
            f"    description={description!r},",
            ")",
            f"async def {function_name}(device):",
            "    await action(",
            f"        {action_type!r},",
            f"        target={('verified ' + tag_head + ' start for ' + (task or app))!r},",
            "        fixed=True,",
            f"        fixed_values={fixed_values!r},",
            f"        state_contract=C.from_dict({candidate_contract!r}),",
            "    )",
            "",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"


def _function_name(app: str, candidate: DeeplinkCandidate) -> str:
    entry_type = _entry_type(candidate)
    if entry_type == "deeplink":
        prefix = "open_deeplink"
    elif entry_type == "internal_uri_intent":
        prefix = "open_internal_uri_intent"
    else:
        prefix = "open_intent"
    slug = re.sub(
        r"[^a-zA-Z0-9_]+",
        "_",
        f"{app}_{_short_hash(_candidate_identity(candidate))}",
    ).strip("_").lower()
    return f"{prefix}_{slug}"


def _candidate_identity(candidate: DeeplinkCandidate) -> str:
    has_verified_variant = candidate.verified_action_type is not None
    return json.dumps({
        "action": candidate.action,
        "uri": _normalize_candidate_uri(candidate.uri),
        "package": candidate.verified_package if has_verified_variant else candidate.package,
        "verified_component": candidate.verified_component if has_verified_variant else candidate.component,
        "verified_action_type": candidate.verified_action_type or "",
        "verified_launch_variant": candidate.verified_launch_variant or "",
        "mime_type": candidate.mime_type,
        "categories": tuple(sorted(candidate.categories)),
        "extras": tuple((str(key), _normalize_extra_value(value)) for key, value in candidate.extras),
    }, sort_keys=True, ensure_ascii=False)


def _short_hash(value: str) -> str:
    import hashlib

    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def _extract_unique(pattern: str, text: str) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for match in re.findall(pattern, text, flags=re.IGNORECASE):
        value = match if isinstance(match, str) else match[0]
        cleaned = value.strip().strip(",")
        if cleaned and cleaned not in seen and cleaned.lower() not in {"http", "https"}:
            seen.add(cleaned)
            values.append(cleaned)
    return values


def _dedupe(items: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = str(item).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _dedupe_candidates(candidates: list[DeeplinkCandidate], *, limit: int) -> list[DeeplinkCandidate]:
    key_to_index: dict[tuple[Any, ...], int] = {}
    result: list[DeeplinkCandidate] = []
    for candidate in candidates:
        if not _candidate_is_probeable(candidate):
            continue
        key = _candidate_probe_key(candidate)
        normalized_uri = _normalize_candidate_uri(candidate.uri)
        if normalized_uri:
            candidate = replace(candidate, uri=normalized_uri)
        if key in key_to_index:
            existing_index = key_to_index[key]
            if candidate.confidence > result[existing_index].confidence:
                result[existing_index] = candidate
            continue
        key_to_index[key] = len(result)
        result.append(candidate)
        if len(result) >= limit:
            break
    return result


def _candidate_is_probeable(candidate: DeeplinkCandidate) -> bool:
    entry_type = _entry_type(candidate)
    if entry_type == "intent":
        return bool(candidate.action)
    if not _usable_data_uri(candidate.uri):
        return False
    if candidate.kind in {"web_link", "web_link_query"}:
        return candidate.source.endswith("_resolved")
    if candidate.kind in _INTERNAL_URI_KINDS:
        return (
            candidate.source.startswith("dumpsys_activity")
            or candidate.source.startswith("dumpsys_activity_")
            or candidate.source.endswith("_resolved")
        )
    return True


def _candidate_probe_key(candidate: DeeplinkCandidate) -> tuple[Any, ...]:
    return (
        candidate.action,
        _normalize_candidate_uri(candidate.uri),
        candidate.mime_type or "",
        candidate.component or "",
    )


def _normalize_candidate_uri(uri: str | None) -> str:
    text = str(uri or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except Exception:
        return text.rstrip("/")
    if not parts.scheme:
        return text.rstrip("/")
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=False)
        if key or value
    ]
    normalized_query = urlencode(sorted(query_pairs), doseq=True)
    path = unquote(parts.path or "")
    if path != "/":
        path = path.rstrip("/")
    netloc = unquote(parts.netloc or "").casefold()
    return urlunsplit((
        parts.scheme.casefold(),
        netloc,
        path,
        normalized_query,
        "",
    ))


def _normalize_extra_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _string_sequence(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _dynamic_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) > 36:
        return True
    if re.fullmatch(r"[\d:./年月日,\- ]+", stripped):
        return True
    if re.search(r"[￥$]\s*\d|\d+%", stripped):
        return True
    return False


def _is_auth_gate(values: tuple[str, ...]) -> bool:
    blob = "\n".join(values).lower()
    return any(term.lower() in blob for term in _AUTH_GATE_TERMS)
