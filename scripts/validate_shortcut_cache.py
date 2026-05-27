#!/usr/bin/env python3
"""Validate Android shortcut cache entries on a connected device.

The script keeps shortcut discovery and validation separate:

* ``shortcut_cache/*.json`` remains the static discovery artifact.
* this script writes device-specific validation sidecars.
* only page-validated records are promoted to ``skills.py`` by default.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus, urlparse, urlunparse

from opengui.skills.deeplink import (
    AppShortcutProfile,
    add_validated_shortcut_skill,
)
from opengui.skills.flat import FlatSkillLibrary


VIEW_ACTION = "android.intent.action.VIEW"
BROWSABLE_CATEGORY = "android.intent.category.BROWSABLE"
DEFAULT_QUERY_KEYS = ("keyword", "query", "q", "text", "word")
DEFAULT_INTENT_EXTRA_KEYS = (
    "query",
    "keyword",
    "text",
    "android.intent.extra.TEXT",
    "user_query",
)
RISKY_TOKENS = (
    "pay",
    "bilipay",
    "recharge",
    "share",
    "push",
    "authorize",
    "auth",
    "accountlinking",
    "account linking",
    "login",
    "sso",
    "nfc",
    "sign",
    "order",
    "purchase",
)


@dataclass(frozen=True)
class Candidate:
    index: int
    kind: str
    package: str
    description: str
    uri_template: str | None = None
    action: str | None = None
    component: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True)
class Variant:
    label: str
    kind: str
    package: str
    uri: str | None = None
    action: str | None = None
    component: str | None = None
    mime_type: str | None = None
    categories: tuple[str, ...] = ()
    extras: tuple[tuple[str, Any], ...] = ()


@dataclass
class ProbeResult:
    candidate: Candidate
    variants: list[dict[str, Any]] = field(default_factory=list)
    status: str = "static_only"
    description: str = ""
    parameters: list[str] = field(default_factory=list)
    best_variant: dict[str, Any] | None = None
    reason: str = ""
    probe_plan: dict[str, Any] | None = None


@dataclass(frozen=True)
class ProbePlan:
    capability: str
    task: str
    query: str
    candidate_limit: int
    variant_limit: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True, help="Path to shortcut_cache/<package>.json")
    parser.add_argument("--serial", default="", help="ADB device serial. Defaults to adb's selected device.")
    parser.add_argument("--task", default="", help="Optional target task, e.g. '在B站搜索敢杀我的马'.")
    parser.add_argument("--query", default="", help="Optional payload text used to test search/text variants.")
    parser.add_argument("--max-candidates", type=int, default=20)
    parser.add_argument("--max-try", type=int, default=5)
    parser.add_argument("--execute", action="store_true", help="Actually launch resolved variants.")
    parser.add_argument("--include-risky", action="store_true", help="Do not skip pay/share/push/auth candidates.")
    parser.add_argument("--validation-root", type=Path, default=None)
    parser.add_argument("--promote", action="store_true", help="Promote page-validated shortcuts into skills.py.")
    parser.add_argument("--allow-launchable-promote", action="store_true")
    parser.add_argument("--skill-store-root", type=Path, default=None)
    parser.add_argument("--llm-base-url", default="")
    parser.add_argument("--llm-model", default="")
    parser.add_argument("--llm-api-key", default="")
    parser.add_argument("--llm-api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--llm-temperature", type=float, default=0.0)
    return parser.parse_args()


def load_profile(cache_path: Path) -> AppShortcutProfile:
    return AppShortcutProfile.from_dict(json.loads(cache_path.read_text(encoding="utf-8")))


def validation_root_for(cache_path: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser()
    parent = cache_path.expanduser().parent
    if parent.name == "shortcut_cache":
        return parent.parent / "shortcut_cache_validation"
    return parent / "shortcut_cache_validation"


def candidate_records(profile: AppShortcutProfile, *, include_risky: bool) -> list[Candidate]:
    records: list[Candidate] = []
    for i, dl in enumerate(profile.deep_links):
        candidate = Candidate(
            index=i,
            kind="deeplink",
            package=profile.package,
            description=dl.description,
            uri_template=dl.uri_template,
            component=dl.component,
        )
        if include_risky or not is_risky_candidate(candidate):
            records.append(candidate)
    offset = len(profile.deep_links)
    for i, di in enumerate(profile.deep_intents):
        candidate = Candidate(
            index=offset + i,
            kind="intent",
            package=profile.package,
            description=di.description,
            action=di.action,
            component=di.component,
            mime_type=di.mime_type,
        )
        if include_risky or not is_risky_candidate(candidate):
            records.append(candidate)
    return sorted(records, key=candidate_priority, reverse=True)


def build_probe_plans(profile: AppShortcutProfile, args: argparse.Namespace) -> list[ProbePlan]:
    candidates = candidate_records(profile, include_risky=args.include_risky)
    if args.task or args.query:
        inferred_capability = infer_primary_capability(candidates)
        query = args.query or default_probe_query(profile.package, inferred_capability)
        return [
            ProbePlan(
                capability="manual",
                task=args.task or default_probe_task(profile.package, inferred_capability, query),
                query=query,
                candidate_limit=args.max_candidates,
                variant_limit=args.max_try,
            )
        ]

    capabilities: list[str] = []
    if any(looks_query_like(candidate) for candidate in candidates):
        capabilities.append("search")
    if any(looks_open_page_candidate(candidate) for candidate in candidates):
        capabilities.append("open_page")
    if not capabilities:
        capabilities.append("open_page")

    plans: list[ProbePlan] = []
    for capability in capabilities[:3]:
        query = default_probe_query(profile.package, capability)
        plans.append(
            ProbePlan(
                capability=capability,
                task=default_probe_task(profile.package, capability, query),
                query=query,
                candidate_limit=args.max_candidates,
                variant_limit=args.max_try,
            )
        )
    return plans


def infer_primary_capability(candidates: list[Candidate]) -> str:
    if any(looks_query_like(candidate) for candidate in candidates):
        return "search"
    return "open_page"


def default_probe_query(package: str, capability: str) -> str:
    if capability != "search":
        return ""
    if package == "tv.danmaku.bili":
        return "敢杀我的马"
    if package == "com.google.android.youtube":
        return "Never Gonna Give You Up"
    return "hello world"


def default_probe_task(package: str, capability: str, query: str) -> str:
    app = display_app_name(package)
    if capability == "search":
        return f"验证 {app} 搜索 deeplink/intent 是否能打开搜索结果页并保留查询词，query={query}"
    return f"验证 {app} deeplink/intent 是否能打开对应页面"


def display_app_name(package: str) -> str:
    names = {
        "tv.danmaku.bili": "B站",
        "com.google.android.youtube": "YouTube",
    }
    return names.get(package, package)


def candidate_matches_plan(candidate: Candidate, plan: ProbePlan) -> bool:
    if plan.capability == "search":
        return looks_query_like(candidate)
    if plan.capability == "open_page":
        return looks_open_page_candidate(candidate)
    return True


def looks_open_page_candidate(candidate: Candidate) -> bool:
    return looks_open_page_like(candidate) and not looks_query_like(candidate)


def looks_open_page_like(candidate: Candidate) -> bool:
    text = candidate_search_text(candidate)
    return any(token in text for token in ("view", "open", "detail", "watch", "play", "video", "home", "首页", "详情"))


def candidate_search_text(candidate: Candidate) -> str:
    return " ".join(
        str(item or "")
        for item in (
            candidate.uri_template,
            candidate.action,
            candidate.component,
            candidate.description,
        )
    ).lower()


def probe_plan_to_dict(plan: ProbePlan) -> dict[str, Any]:
    return {
        "capability": plan.capability,
        "task": plan.task,
        "query": plan.query,
        "candidate_limit": plan.candidate_limit,
        "variant_limit": plan.variant_limit,
    }


def is_risky_candidate(candidate: Candidate) -> bool:
    text = " ".join(
        str(item or "")
        for item in (
            candidate.uri_template,
            candidate.action,
            candidate.component,
            candidate.description,
        )
    ).lower()
    return any(token in text for token in RISKY_TOKENS)


def candidate_priority(candidate: Candidate) -> tuple[int, int]:
    uri_and_description = f"{candidate.uri_template or ''} {candidate.description or ''}".lower()
    action = (candidate.action or "").lower()
    component = (candidate.component or "").lower()
    score = 0
    if candidate.kind == "deeplink" and has_route_word(uri_and_description, ("search", "query", "keyword", "搜索")):
        score += 120
    elif action == "android.intent.action.search":
        score += 90
    elif has_route_word(uri_and_description, ("search", "query", "keyword", "搜索")):
        score += 80
    elif "search" in component:
        score += 70
    if has_route_word(uri_and_description, ("browser", "home", "首页")):
        score += 35
    if has_route_word(uri_and_description, ("detail", "详情")):
        score += 20
    if candidate.kind == "deeplink":
        score += 8
    return score, -candidate.index


def has_route_word(text: str, words: tuple[str, ...]) -> bool:
    tokens = set(re.split(r"[^a-z0-9\u4e00-\u9fff]+", text.lower()))
    return any(word in tokens or (not word.isascii() and word in text) for word in words)


def variants_for_candidate(candidate: Candidate, *, query: str, max_try: int) -> list[Variant]:
    if candidate.kind == "deeplink":
        return variants_for_deeplink(candidate, query=query, max_try=max_try)
    return variants_for_intent(candidate, query=query, max_try=max_try)


def variants_for_deeplink(candidate: Candidate, *, query: str, max_try: int) -> list[Variant]:
    uri = candidate.uri_template or ""
    variants: list[Variant] = []

    def add(label: str, value: str, *, component: str | None = None) -> None:
        if not value:
            return
        variant = Variant(
            label=label,
            kind="deeplink",
            package=candidate.package,
            uri=value,
            component=component,
            categories=(BROWSABLE_CATEGORY,),
        )
        if variant not in variants:
            variants.append(variant)

    add("raw_package", uri)
    if candidate.component:
        add("raw_component", uri, component=candidate.component)

    if query and looks_query_like(candidate):
        for key in DEFAULT_QUERY_KEYS:
            add(f"{key}_encoded", uri_with_query(uri, key, quote(query, safe="")))
            add(f"{key}_plus", uri_with_query(uri, key, quote_plus(query)))
            add(f"{key}_raw", uri_with_query(uri, key, query))

    return variants[:max_try]


def variants_for_intent(candidate: Candidate, *, query: str, max_try: int) -> list[Variant]:
    action = candidate.action or ""
    variants: list[Variant] = []

    def add(label: str, *, component: str | None, extras: tuple[tuple[str, Any], ...] = ()) -> None:
        if not action:
            return
        variant = Variant(
            label=label,
            kind="intent",
            package=candidate.package,
            action=action,
            component=component,
            mime_type=candidate.mime_type,
            extras=extras,
        )
        if variant not in variants:
            variants.append(variant)

    add("component_no_extra", component=candidate.component)
    add("package_no_extra", component=None)
    if query and looks_query_like(candidate):
        for key in DEFAULT_INTENT_EXTRA_KEYS:
            add(f"component_extra_{key}", component=candidate.component, extras=((key, query),))
            add(f"package_extra_{key}", component=None, extras=((key, query),))
    return variants[:max_try]


def looks_query_like(candidate: Candidate) -> bool:
    text = candidate_search_text(candidate)
    return any(token in text for token in ("search", "query", "keyword", "media_search", "media_play_from_search", "搜索"))


def uri_with_query(uri: str, key: str, value: str) -> str:
    parsed = urlparse(uri)
    sep = "&" if parsed.query else ""
    query = f"{parsed.query}{sep}{key}={value}"
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))


class Adb:
    def __init__(self, serial: str = "") -> None:
        self.serial = serial.strip()

    def run(self, *args: str, timeout: float = 10.0) -> tuple[int, str, bool]:
        command = ["adb"]
        if self.serial:
            command.extend(["-s", self.serial])
        command.extend(args)
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
            return completed.returncode, (completed.stdout + completed.stderr).strip(), False
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + (exc.stderr or "")
            if isinstance(output, bytes):
                output = output.decode("utf-8", "ignore")
            return 124, output.strip(), True


def resolve_variant(adb: Adb, variant: Variant) -> dict[str, Any]:
    if variant.kind == "deeplink":
        args = [
            "shell",
            "cmd",
            "package",
            "resolve-activity",
            "--brief",
            "-a",
            VIEW_ACTION,
            "-c",
            BROWSABLE_CATEGORY,
            "-d",
            variant.uri or "",
        ]
    else:
        args = [
            "shell",
            "cmd",
            "package",
            "resolve-activity",
            "--brief",
            "-a",
            variant.action or "",
        ]
        if variant.mime_type:
            args.extend(["-t", variant.mime_type])
        if variant.component:
            args.extend(["-n", variant.component])
    rc, output, timed_out = adb.run(*args, timeout=5.0)
    ok = is_resolve_ok(output)
    return {
        "ok": ok,
        "rc": rc,
        "timed_out": timed_out,
        "command": args,
        "output": output,
        "target_package": variant.package in output,
    }


def is_resolve_ok(output: str) -> bool:
    lowered = (output or "").lower()
    return bool(
        output.strip()
        and "no activity found" not in lowered
        and "unable to resolve" not in lowered
        and "error:" not in lowered
    )


def launch_variant(
    adb: Adb,
    variant: Variant,
    *,
    artifacts_dir: Path,
    index: int,
    capture_evidence: bool = False,
    settle_seconds: float = 2.0,
) -> dict[str, Any]:
    adb.run("shell", "am", "force-stop", variant.package, timeout=5.0)
    time.sleep(0.4)
    args = build_launch_args(variant)
    rc, output, timed_out = adb.run(*args, timeout=15.0)
    time.sleep(settle_seconds)
    foreground = foreground_activity(adb)
    screenshot_path = None
    ui_tree = ""
    ui_sample: list[str] = []
    if capture_evidence:
        screenshot_path = capture_screenshot(adb, artifacts_dir / f"variant_{index:03d}.png")
        ui_tree, ui_sample = capture_ui_tree(adb)
    return {
        "rc": rc,
        "timed_out": timed_out,
        "command": args,
        "output": output,
        "foreground": foreground,
        "screenshot_path": str(screenshot_path) if screenshot_path else None,
        "ui_sample": ui_sample,
        "ui_tree": ui_tree,
        "target_package": foreground.startswith(f"{variant.package}/"),
    }


def build_launch_args(variant: Variant) -> list[str]:
    if variant.kind == "deeplink":
        args = [
            "shell",
            "am",
            "start",
            "-W",
            "-a",
            VIEW_ACTION,
            "-c",
            BROWSABLE_CATEGORY,
            "-d",
            variant.uri or "",
        ]
    else:
        args = ["shell", "am", "start", "-W", "-a", variant.action or ""]
        if variant.uri:
            args.extend(["-d", variant.uri])
        if variant.mime_type:
            args.extend(["-t", variant.mime_type])
        for category in variant.categories:
            args.extend(["-c", category])
        for key, value in variant.extras:
            args.extend(["--es", key, "" if value is None else str(value)])
    if variant.component:
        args.extend(["-n", variant.component])
    else:
        args.extend(["-p", variant.package])
    return args


def foreground_activity(adb: Adb) -> str:
    _, output, _ = adb.run("shell", "dumpsys", "window", "windows", timeout=5.0)
    match = (
        re.search(r"mCurrentFocus=Window\{[^ ]+ [^ ]+ ([^/ ]+)/([^}\s]+)", output)
        or re.search(r"mFocusedApp=.* ([^/ ]+)/([^\s}]+)", output)
    )
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    _, output, _ = adb.run("shell", "dumpsys", "activity", "activities", timeout=5.0)
    match = re.search(r"topResumedActivity=.* ([^/ ]+)/([^\s}]+)", output)
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def capture_screenshot(adb: Adb, path: Path) -> Path | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    command = ["adb"]
    if adb.serial:
        command.extend(["-s", adb.serial])
    command.extend(["exec-out", "screencap", "-p"])
    try:
        completed = subprocess.run(command, capture_output=True, timeout=8.0, check=False)
    except subprocess.TimeoutExpired:
        return None
    if completed.returncode != 0 or not completed.stdout:
        return None
    path.write_bytes(completed.stdout)
    return path


def capture_ui_tree(adb: Adb) -> tuple[str, list[str]]:
    remote = "/sdcard/window_dump.xml"
    adb.run("shell", "rm", "-f", remote, timeout=3.0)
    adb.run("shell", "uiautomator", "dump", "--compressed", remote, timeout=15.0)
    _, xml, _ = adb.run("exec-out", "cat", remote, timeout=8.0)
    values: list[str] = []
    for attr in ("text", "content-desc", "resource-id"):
        values.extend(re.findall(attr + r'="([^"]{1,100})"', xml))
    sample: list[str] = []
    for value in values:
        if value and value not in sample and len(sample) < 40:
            sample.append(value)
    return xml, sample


def verify_with_llm(
    *,
    base_url: str,
    model: str,
    api_key: str,
    temperature: float,
    task: str,
    candidate: Candidate,
    variant: Variant,
    launch: dict[str, Any],
) -> dict[str, Any]:
    content: list[dict[str, Any]] = [{
        "type": "text",
        "text": json.dumps({
            "task": task,
            "candidate": candidate_to_dict(candidate),
            "variant": variant_to_dict(variant),
            "foreground": launch.get("foreground"),
            "adb_output": summarize_text(str(launch.get("output") or ""), 1200),
            "ui_sample": launch.get("ui_sample") or [],
            "ui_tree_excerpt": summarize_text(str(launch.get("ui_tree") or ""), 4000),
        }, ensure_ascii=False),
    }]
    screenshot = launch.get("screenshot_path")
    if screenshot:
        image_data = Path(screenshot).read_bytes()
        content.append({
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64," + base64.b64encode(image_data).decode("ascii")},
        })
    messages = [
        {
            "role": "system",
            "content": (
                "You validate Android deeplink/intent probe results. "
                "Return only one JSON object with fields: "
                "usable (boolean), status ('page_validated' or 'launchable' or 'failed'), "
                "description (short natural-language capability), parameters (array of strings), "
                "payload_preserved (boolean), reason (short string), "
                "next_variant_hint (string or null). "
                "Set usable=true only if the screenshot/UI indicates the intended app page opened "
                "and the payload, such as query text, was preserved when relevant. "
                "Do not treat a query visible only in search history or suggestions as payload_preserved; "
                "payload_preserved means the current input/result page reflects that payload. "
                "Use a concise natural-language description such as 'B站搜索视频'. "
                "Do not mention adb, URI, component, or implementation details in description."
            ),
        },
        {
            "role": "user",
            "content": content,
        },
    ]
    try:
        from openai import OpenAI

        client = OpenAI(base_url=base_url, api_key=api_key or "EMPTY")
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
    except Exception as exc:
        return {
            "usable": False,
            "status": "verifier_error",
            "reason": str(exc)[:200],
        }
    text = response.choices[0].message.content or ""
    return parse_json_object(text)


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        from json_repair import loads as json_repair_loads

        data = json_repair_loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def verifier_enabled(args: argparse.Namespace) -> bool:
    return bool(args.llm_base_url and args.llm_model)


def verifier_api_key(args: argparse.Namespace) -> str:
    return args.llm_api_key or os.environ.get(args.llm_api_key_env, "")


def args_for_probe_plan(args: argparse.Namespace, plan: ProbePlan) -> argparse.Namespace:
    plan_args = argparse.Namespace(**vars(args))
    plan_args.task = plan.task
    plan_args.query = plan.query
    plan_args.max_try = plan.variant_limit
    return plan_args


def validate_candidate(
    adb: Adb,
    candidate: Candidate,
    *,
    args: argparse.Namespace,
    artifacts_dir: Path,
) -> ProbeResult:
    result = ProbeResult(candidate=candidate, description=candidate.description)
    variants = variants_for_candidate(candidate, query=args.query, max_try=args.max_try)
    hint = ""
    for attempt, variant in enumerate(reorder_variants(variants, hint), start=1):
        variant_record = {
            "attempt": attempt,
            "variant": variant_to_dict(variant),
            "resolve": resolve_variant(adb, variant),
        }
        result.variants.append(variant_record)
        if variant_record["resolve"]["ok"]:
            result.status = "resolved"
        else:
            continue
        if not args.execute:
            continue
        llm_enabled = verifier_enabled(args)
        launch = launch_variant(
            adb,
            variant,
            artifacts_dir=artifacts_dir,
            index=len(result.variants),
            capture_evidence=llm_enabled,
        )
        variant_record["launch"] = launch
        if launch.get("target_package"):
            result.status = "launchable"
            result.best_variant = variant_to_dict(variant)
            if not llm_enabled:
                break
        if llm_enabled:
            verdict = verify_with_llm(
                base_url=args.llm_base_url,
                model=args.llm_model,
                api_key=verifier_api_key(args),
                temperature=args.llm_temperature,
                task=args.task,
                candidate=candidate,
                variant=variant,
                launch=launch,
            )
            variant_record["verifier"] = verdict
            if verdict.get("description"):
                result.description = str(verdict["description"])
            if isinstance(verdict.get("parameters"), list):
                result.parameters = normalize_parameters(verdict["parameters"], query=args.query)
            hint = str(verdict.get("next_variant_hint") or "")
            if verdict.get("usable") is True:
                if (
                    args.query
                    and looks_query_like(candidate)
                    and verdict.get("payload_preserved") is not True
                    and not variant_contains_query(variant, args.query)
                ):
                    continue
                result.status = str(verdict.get("status") or "page_validated")
                result.best_variant = variant_to_dict(variant)
                result.reason = str(verdict.get("reason") or "")
                break
    if not result.best_variant and result.variants:
        for variant_record in reversed(result.variants):
            if variant_record.get("resolve", {}).get("ok"):
                result.best_variant = variant_record["variant"]
                break
    return result


def reorder_variants(variants: list[Variant], hint: str) -> list[Variant]:
    if not hint:
        return variants
    lowered = hint.lower()
    preferred = [variant for variant in variants if lowered in variant.label.lower()]
    rest = [variant for variant in variants if variant not in preferred]
    return [*preferred, *rest]


def result_to_validation_record(result: ProbeResult, *, query: str = "") -> dict[str, Any] | None:
    variant = result.best_variant
    if not variant:
        return None
    variant = template_query_payload(variant, query=query)
    placeholders = placeholder_names(variant)
    parameters = normalize_parameters(result.parameters, query=query)
    if query and "query" in placeholders and "query" not in parameters:
        parameters.append("query")
    parameters = [name for name in parameters if name in placeholders]
    record = {
        "package": result.candidate.package,
        "kind": result.candidate.kind,
        "status": result.status,
        "description": result.description,
        "parameters": parameters,
        "valid_state": result.description,
    }
    if result.candidate.kind == "deeplink":
        record["uri_template"] = variant.get("uri")
    else:
        record["intent_action"] = variant.get("action")
        if variant.get("uri"):
            record["uri_template"] = variant.get("uri")
        if variant.get("mime_type"):
            record["mime_type"] = variant.get("mime_type")
        if variant.get("categories"):
            record["categories"] = variant.get("categories")
        if variant.get("extras"):
            record["extras"] = variant.get("extras")
    if variant.get("component"):
        record["component"] = variant.get("component")
    return record


def normalize_parameters(values: Any, *, query: str = "") -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value).strip()
        if not text or text.startswith(("android.", "com.")):
            continue
        if "=" in text:
            key, raw_value = text.split("=", 1)
            text = key.strip() if not query or raw_value.strip() == query else ""
        name = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")
        if name and re.match(r"^[A-Za-z_]\w*$", name) and name not in result:
            result.append(name)
    return result


def template_query_payload(value: Any, *, query: str) -> Any:
    if not query:
        return value
    if isinstance(value, str):
        for item in (quote(query, safe=""), quote_plus(query), query):
            value = value.replace(item, "{{query}}")
        return value
    if isinstance(value, list):
        return [template_query_payload(item, query=query) for item in value]
    if isinstance(value, tuple):
        return tuple(template_query_payload(item, query=query) for item in value)
    if isinstance(value, dict):
        return {key: template_query_payload(item, query=query) for key, item in value.items()}
    return value


def placeholder_names(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(re.findall(r"\{\{(\w+)\}\}", value))
    if isinstance(value, dict):
        names: set[str] = set()
        for item in value.values():
            names.update(placeholder_names(item))
        return names
    if isinstance(value, (list, tuple)):
        names: set[str] = set()
        for item in value:
            names.update(placeholder_names(item))
        return names
    return set()


def variant_contains_query(variant: Variant, query: str) -> bool:
    if not query:
        return False
    return "{{query}}" in json.dumps(template_query_payload(variant_to_dict(variant), query=query), ensure_ascii=False)


async def promote_results(args: argparse.Namespace, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not args.promote or not records:
        return []
    if args.skill_store_root is None:
        raise SystemExit("--promote requires --skill-store-root")
    library = FlatSkillLibrary(store_dir=args.skill_store_root.expanduser())
    outcomes: list[dict[str, Any]] = []
    for record in records:
        decision, skill_id = await add_validated_shortcut_skill(
            library,
            record,
            require_page_validated=not args.allow_launchable_promote,
        )
        outcomes.append({"decision": decision, "skill_id": skill_id, "record": record})
    return outcomes


def candidate_to_dict(candidate: Candidate) -> dict[str, Any]:
    return {
        "index": candidate.index,
        "kind": candidate.kind,
        "package": candidate.package,
        "description": candidate.description,
        "uri_template": candidate.uri_template,
        "action": candidate.action,
        "component": candidate.component,
        "mime_type": candidate.mime_type,
    }


def variant_to_dict(variant: Variant) -> dict[str, Any]:
    return {
        "label": variant.label,
        "kind": variant.kind,
        "package": variant.package,
        "uri": variant.uri,
        "action": variant.action,
        "component": variant.component,
        "mime_type": variant.mime_type,
        "categories": list(variant.categories),
        "extras": [list(item) for item in variant.extras],
    }


def summarize_text(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text or "").strip("_") or "default"


def write_sidecar(
    *,
    path: Path,
    profile: AppShortcutProfile,
    args: argparse.Namespace,
    results: list[ProbeResult],
    promotions: list[dict[str, Any]],
    probe_plans: list[ProbePlan],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "package": profile.package,
        "device_serial": args.serial,
        "cache_path": str(args.cache),
        "task": args.task,
        "query": args.query,
        "probe_plans": [probe_plan_to_dict(plan) for plan in probe_plans],
        "execute": args.execute,
        "verifier_model": args.llm_model or None,
        "created_at": time.time(),
        "results": [
            {
                "candidate": candidate_to_dict(result.candidate),
                "status": result.status,
                "description": result.description,
                "parameters": result.parameters,
                "best_variant": result.best_variant,
                "reason": result.reason,
                "probe_plan": result.probe_plan,
                "variants": result.variants,
                "validation_record": result_to_validation_record(result, query=result_probe_query(result, args)),
            }
            for result in results
        ],
        "promotions": promotions,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def result_probe_query(result: ProbeResult, args: argparse.Namespace) -> str:
    if result.probe_plan:
        return str(result.probe_plan.get("query") or "")
    return args.query


def main() -> None:
    args = parse_args()
    args.cache = args.cache.expanduser()
    profile = load_profile(args.cache)
    root = validation_root_for(args.cache, args.validation_root)
    serial_label = safe_name(args.serial or "default")
    package_label = safe_name(profile.package)
    artifacts_dir = root / f"{package_label}.{serial_label}.artifacts"
    sidecar_path = root / f"{package_label}.{serial_label}.json"
    adb = Adb(args.serial)

    probe_plans = build_probe_plans(profile, args)
    candidates = candidate_records(profile, include_risky=args.include_risky)
    results: list[ProbeResult] = []
    for plan in probe_plans:
        plan_args = args_for_probe_plan(args, plan)
        plan_candidates = [
            candidate
            for candidate in candidates
            if candidate_matches_plan(candidate, plan)
        ][: plan.candidate_limit]
        for candidate in plan_candidates:
            result = validate_candidate(adb, candidate, args=plan_args, artifacts_dir=artifacts_dir)
            result.probe_plan = probe_plan_to_dict(plan)
            results.append(result)

    validation_records = [
        record
        for result in results
        if (record := result_to_validation_record(result, query=result_probe_query(result, args))) is not None
        and (record["status"] == "page_validated" or (args.allow_launchable_promote and record["status"] == "launchable"))
    ]
    promotions = asyncio.run(promote_results(args, validation_records))
    write_sidecar(
        path=sidecar_path,
        profile=profile,
        args=args,
        results=results,
        promotions=promotions,
        probe_plans=probe_plans,
    )

    print(f"cache: {args.cache}")
    print(f"package: {profile.package}")
    print(f"candidates_tested: {len(results)}")
    print("probe_plans:", json.dumps([probe_plan_to_dict(plan) for plan in probe_plans], ensure_ascii=False))
    print(f"sidecar: {sidecar_path}")
    print("status_counts:", status_counts(results))
    if promotions:
        print("promotions:", json.dumps(promotions, ensure_ascii=False, indent=2))


def status_counts(results: list[ProbeResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


if __name__ == "__main__":
    main()
