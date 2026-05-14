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
import json
import re
import shlex
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

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
    extras: tuple[tuple[str, str], ...] = ()
    raw_intent_line: str = ""
    source: str = "dumpsys_activity"


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
        }


@dataclass(frozen=True)
class DeeplinkDiscoveryResult:
    status: str
    reason: str | None = None
    app: str | None = None
    contract: dict[str, Any] | None = None
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
    if not contract:
        return _write_deeplink_result(
            trace_path,
            DeeplinkDiscoveryResult(status="no_candidate", reason="weak_final_state_contract", app=app),
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
            ),
        )

    screenshot_dir = trace_path.parent / current.screenshot_dir_name
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    records: list[DeeplinkProbeRecord] = []
    verified: list[DeeplinkCandidate] = []
    for index, candidate in enumerate(candidates, start=1):
        record = await _probe_candidate(
            backend,
            candidate,
            contract=contract,
            screenshot_path=screenshot_dir / f"deeplink_{index:02d}.png",
            settle_seconds=current.settle_seconds,
        )
        records.append(record)
        if record.matched:
            verified.append(candidate)
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
    result = DeeplinkDiscoveryResult(
        status="processed_deeplink_code" if not update.errors else "code_compile_error",
        reason=None if not update.errors else "code_compile_error",
        app=app,
        contract=result_contract,
        candidates=tuple(records),
        updated_functions=tuple(update.updated_functions),
        compiled_skill_ids=tuple(skill.skill_id for skill in update.skills if skill.skill_id),
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
    profile = _profile_for_task(task)
    activity_hint = _activity_from_observation(final_observation)
    captured_specs = await _capture_current_intent_specs(backend, app=app, activity=activity_hint)
    package_profile = await _package_profile(backend, app)
    package_schemes = _dedupe(package_profile.get("schemes", ()))
    manifest_filters = tuple(
        item for item in package_profile.get("filters", ())
        if isinstance(item, ManifestIntentFilter)
    )
    package_scheme_set = set(package_schemes)
    guessed_schemes = [
        scheme
        for scheme in _guess_schemes(app)
        if scheme not in package_scheme_set
    ]
    hosts = _dedupe(package_profile.get("hosts", ()))
    paths = tuple(profile["paths"])
    query_keys = tuple(profile["query_keys"])
    query_value = str(profile["query_value"])
    router_components = package_profile.get("catch_all_router_components", {})
    if not isinstance(router_components, dict):
        router_components = {}
    router_paths = _router_paths_from_captured_specs(captured_specs, paths=paths)

    candidates: list[DeeplinkCandidate] = []
    for spec in captured_specs:
        if not spec.data_uri or not _usable_data_uri(spec.data_uri):
            continue
        # ``cmp=`` in dumpsys is useful provenance, but passing it back to
        # ``am start -n`` often fails for non-exported router activities.  Let
        # Android resolve the captured URI inside the target package first.
        candidates.append(DeeplinkCandidate(
            uri=spec.data_uri,
            kind="captured_intent",
            package=app,
            source=spec.source,
            confidence=_captured_intent_confidence(spec, task=task),
            extras=spec.extras,
        ))

    candidates.extend(_shortcut_intent_candidates(app=app, task=task))

    for scheme in package_schemes:
        for component in _string_sequence(router_components.get(scheme)):
            for route_path in router_paths:
                uri = _open_router_path_uri(scheme, route_path)
                candidates.append(DeeplinkCandidate(
                    uri=uri,
                    kind="router_payload",
                    package=app,
                    component=component,
                    source="package_manifest_router",
                    confidence=0.9 + _uri_task_bonus(route_path, task),
                ))

    for manifest_filter in manifest_filters:
        if "android.intent.action.VIEW" not in manifest_filter.actions:
            continue
        if "android.intent.category.BROWSABLE" in manifest_filter.categories:
            continue
        for scheme in manifest_filter.schemes:
            for authority in manifest_filter.authorities:
                candidate_paths = manifest_filter.paths or ("",)
                for path in candidate_paths:
                    normalized_path = path if not path or path.startswith("/") else f"/{path}"
                    uri = f"{scheme}://{authority}{normalized_path}"
                    candidates.append(DeeplinkCandidate(
                        uri=uri,
                        kind="internal_uri_intent",
                        package=app,
                        source="package_manifest_internal_uri",
                        confidence=0.82 + _uri_task_bonus(uri, task),
                    ))

    for manifest_filter in manifest_filters:
        if "android.intent.action.VIEW" not in manifest_filter.actions:
            continue
        if "android.intent.category.BROWSABLE" not in manifest_filter.categories:
            continue
        for scheme in manifest_filter.schemes:
            for authority in manifest_filter.authorities:
                candidate_paths = manifest_filter.paths or tuple(
                    f"/{path.strip('/')}"
                    for path in paths
                    if path and path.strip("/")
                ) or ("",)
                for path in candidate_paths:
                    normalized_path = path if not path or path.startswith("/") else f"/{path}"
                    uri = f"{scheme}://{authority}{normalized_path}"
                    candidates.append(DeeplinkCandidate(
                        uri=uri,
                        kind="manifest_authority",
                        package=app,
                        source="package_manifest_authority",
                        confidence=0.78 + _uri_task_bonus(uri, task),
                    ))

    scheme_sources = [(scheme, "package_manifest", 0.64) for scheme in package_schemes]
    scheme_sources.extend((scheme, "package_name_guess", 0.34) for scheme in guessed_schemes)
    for scheme, source, confidence in scheme_sources:
        for path in paths:
            base_uri = f"{scheme}://{path}" if path else f"{scheme}://"
            candidates.append(DeeplinkCandidate(
                uri=base_uri,
                kind="custom_scheme",
                package=app,
                source=source,
                confidence=confidence + _uri_task_bonus(base_uri, task),
            ))
            for key in query_keys[:2]:
                uri = f"{base_uri}?{key}={quote(query_value)}"
                candidates.append(DeeplinkCandidate(
                    uri=uri,
                    kind="custom_scheme_query",
                    package=app,
                    source=source,
                    confidence=confidence + 0.02 + _uri_task_bonus(uri, task),
                ))
    for host in hosts[:4]:
        base_host = host if host.startswith(("http://", "https://")) else f"https://{host}"
        for path in paths[:3]:
            base_uri = f"{base_host}/{path}" if path else base_host
            candidates.append(DeeplinkCandidate(
                uri=base_uri,
                kind="web_link",
                package=app,
                source="package_manifest",
                confidence=0.54 + _uri_task_bonus(base_uri, task),
            ))
            for key in query_keys[:1]:
                uri = f"{base_uri}?{key}={quote(query_value)}"
                candidates.append(DeeplinkCandidate(
                    uri=uri,
                    kind="web_link_query",
                    package=app,
                    source="package_manifest",
                    confidence=0.56 + _uri_task_bonus(uri, task),
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
                expanded.append(DeeplinkCandidate(
                    uri=candidate.uri,
                    kind=candidate.kind,
                    package=candidate.package,
                    component=component,
                    source=f"{candidate.source}_resolved",
                    confidence=min(candidate.confidence + 0.08, 0.99),
                    action=candidate.action,
                    mime_type=candidate.mime_type,
                    categories=candidate.categories,
                    extras=candidate.extras,
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
    if not callable(run):
        return ()

    specs: list[CapturedIntentSpec] = []
    seen: set[tuple[str | None, str | None, str]] = set()
    for source, command in _activity_capture_commands(app=app, activity=activity):
        try:
            output = await run("shell", command, timeout=10.0)
        except Exception:
            continue
        for spec in _parse_dumpsys_intent_specs(output, app=app, activity=activity, source=source):
            key = (spec.data_uri, spec.component, spec.raw_intent_line)
            if key in seen:
                continue
            seen.add(key)
            specs.append(spec)
        if specs:
            break
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
    categories_match = re.search(r"cat=\[([^\]]+)]", intent_line)
    categories = tuple(
        part.strip()
        for part in (categories_match.group(1).split(",") if categories_match else ())
        if part.strip()
    )
    extras = _parse_intent_extras(lines[index:min(index + 50, len(lines))])
    return CapturedIntentSpec(
        action=_extract_intent_field(intent_line, "act"),
        data_uri=_extract_intent_field(intent_line, "dat"),
        component=_extract_intent_field(intent_line, "cmp"),
        categories=categories,
        extras=extras,
        raw_intent_line=intent_line,
        source=source,
    )


def _extract_intent_field(line: str, field: str) -> str | None:
    match = re.search(rf"(?:^|\s){re.escape(field)}=([^\s}}]+)", line)
    if not match:
        return None
    value = match.group(1).strip().strip(",")
    return value or None


def _parse_intent_extras(block: list[str]) -> tuple[tuple[str, str], ...]:
    full_text = "\n".join(block)
    bundle_match = re.search(r"Bundle\[\{(.+?)}]", full_text, flags=re.DOTALL)
    if not bundle_match:
        return ()
    extras: list[tuple[str, str]] = []
    for item in bundle_match.group(1).split(","):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        clean_key = key.strip()
        clean_value = value.strip()
        if clean_key:
            extras.append((clean_key, clean_value))
    return tuple(extras)


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


async def _probe_candidate(
    backend: Any,
    candidate: DeeplinkCandidate,
    *,
    contract: dict[str, Any],
    screenshot_path: Path,
    settle_seconds: float,
) -> DeeplinkProbeRecord:
    error: str | None = None
    observation: Observation | None = None
    launched_component = candidate.component
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
    try:
        await backend.execute(_action_for_candidate(candidate, component=launched_component), timeout=10.0)
        await asyncio.sleep(settle_seconds)
        observation = await backend.observe(screenshot_path, timeout=8.0)
    except Exception as exc:
        error = str(exc)
        status = _classify_launch_error(error)
        if launched_component and status == "launch_error_security":
            try:
                launched_component = None
                await backend.execute(_action_for_candidate(candidate, component=None), timeout=10.0)
                await asyncio.sleep(settle_seconds)
                observation = await backend.observe(screenshot_path, timeout=8.0)
                error = None
            except Exception as retry_exc:
                error = f"{error}\nretry_without_component: {retry_exc}"

    visible_text: tuple[str, ...] = ()
    content_desc: tuple[str, ...] = ()
    resource_ids: tuple[str, ...] = ()
    foreground_app: str | None = None
    contract_eval: bool | None = None
    if observation is not None:
        foreground_app = observation.foreground_app
        extra = observation.extra or {}
        if not _has_ui_evidence(extra):
            fallback_extra = await _collect_probe_ui_extra(backend)
            if fallback_extra:
                extra = {**extra, **fallback_extra}
                observation.extra = extra
        visible_text = tuple(_string_list(extra.get("visible_text"))[:30])
        content_desc = tuple(_string_list(extra.get("content_desc"))[:30])
        resource_ids = tuple(_string_list(extra.get("resource_ids"))[:30])
        contract_eval = evaluate_state_contract(verification_contract, observation=observation)

    if error:
        status = _classify_launch_error(error)
        return DeeplinkProbeRecord(
            uri=candidate.uri,
            kind=candidate.kind,
            status=status,
            action=candidate.action,
            error=error,
            component=launched_component,
            source=candidate.source,
            confidence=candidate.confidence,
            mime_type=candidate.mime_type,
            categories=candidate.categories,
            extras=candidate.extras,
            launch_error_type=status if status.startswith("launch_error") else None,
            foreground_app=foreground_app,
            screenshot_path=str(screenshot_path),
            contract_eval=contract_eval,
            visible_text=visible_text,
            content_desc=content_desc,
            resource_ids=resource_ids,
        )
    if observation is None:
        status = "no_observation"
    elif expected_app and foreground_app != expected_app:
        status = "wrong_app"
    elif _is_auth_gate((*visible_text, *content_desc)):
        status = "auth_gate"
    elif contract_eval is True:
        status = "target_verified"
    elif contract_eval is False:
        status = "contract_mismatch"
    else:
        status = "unverified"
    return DeeplinkProbeRecord(
        uri=candidate.uri,
        kind=candidate.kind,
        status=status,
        action=candidate.action,
        matched=status == "target_verified",
        component=launched_component,
        source=candidate.source,
        confidence=candidate.confidence,
        mime_type=candidate.mime_type,
        categories=candidate.categories,
        extras=candidate.extras,
        foreground_app=foreground_app,
        screenshot_path=str(screenshot_path),
        contract_eval=contract_eval,
        visible_text=visible_text,
        content_desc=content_desc,
        resource_ids=resource_ids,
    )


def _action_for_candidate(candidate: DeeplinkCandidate, *, component: str | None) -> Action:
    if _entry_type(candidate) == "deeplink":
        return Action(
            action_type="open_deeplink",
            text=candidate.uri,
            component=component,
            package=candidate.package,
        )
    return Action(
        action_type="open_intent",
        text=candidate.uri or None,
        intent_action=candidate.action,
        mime_type=candidate.mime_type,
        component=component,
        package=candidate.package,
        categories=candidate.categories,
        extras=candidate.extras,
    )


def _classify_launch_error(error: str) -> str:
    lowered = error.lower()
    if "securityexception" in lowered or "permission denial" in lowered or "permission" in lowered:
        return "launch_error_security"
    if (
        "activitynotfound" in lowered
        or "unable to resolve intent" in lowered
        or "no activity found" in lowered
        or "activity not started" in lowered
    ):
        return "launch_error_activity_not_found"
    return "launch_error"


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
        skill_app = candidate.package or app
        candidate_contract = _verification_contract_for_candidate(candidate, default_contract=contract)
        function_name = _function_name(skill_app, candidate)
        entry_type = _entry_type(candidate)
        is_uri_deeplink = entry_type == "deeplink"
        skill_prefix = entry_type
        skill_id = f"{skill_prefix}:{skill_app}:{_short_hash(_candidate_identity(candidate))}"
        if is_uri_deeplink:
            fixed_values: dict[str, Any] = {"text": candidate.uri, "package": skill_app}
        else:
            fixed_values = {"package": skill_app}
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
        if candidate.component:
            fixed_values["component"] = candidate.component
        provenance = {
            "behavior_intent": task or app,
            "launch_mode": entry_type,
            "source": candidate.source,
            "component": candidate.component,
            "confidence": round(candidate.confidence, 3),
        }
        action_type = "open_deeplink" if is_uri_deeplink else "open_intent"
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
    return json.dumps({
        "action": candidate.action,
        "uri": candidate.uri,
        "mime_type": candidate.mime_type,
        "component": candidate.component,
        "extras": list(candidate.extras),
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
    seen: set[tuple[str, str, str | None, str | None]] = set()
    result: list[DeeplinkCandidate] = []
    for candidate in candidates:
        key = (candidate.action, candidate.uri, candidate.mime_type, candidate.component)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
        if len(result) >= limit:
            break
    return result


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
