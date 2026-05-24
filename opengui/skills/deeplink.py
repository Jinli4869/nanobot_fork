"""Static Android shortcut extraction from AndroidManifest.xml only."""

from __future__ import annotations

import hashlib
import re
import tempfile
import xml.etree.ElementTree as ET

from opengui.skills.state_contract import _clean_string
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_ANDROID_NS = "http://schemas.android.com/apk/res/android"


@dataclass(frozen=True)
class ManifestIntentFilter:
    component: str
    actions: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    schemes: tuple[str, ...] = ()
    authorities: tuple[str, ...] = ()
    paths: tuple[tuple[str, str], ...] = ()
    mime_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeepLink:
    uri_template: str
    scheme: str
    host: str | None
    path: str | None
    component: str
    description: str
    path_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"uri_template": self.uri_template, "scheme": self.scheme,
                "host": self.host, "path": self.path,
                "component": self.component, "description": self.description,
                "path_kind": self.path_kind}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DeepLink":
        return cls(uri_template=d["uri_template"], scheme=d["scheme"],
                   host=d.get("host"), path=d.get("path"),
                   component=d["component"], description=d.get("description", ""),
                   path_kind=d.get("path_kind"))


@dataclass(frozen=True)
class DeepIntent:
    action: str
    component: str
    mime_type: str | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "component": self.component,
                "mime_type": self.mime_type, "description": self.description}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DeepIntent":
        return cls(action=d["action"], component=d["component"],
                   mime_type=d.get("mime_type"), description=d.get("description", ""))


@dataclass(frozen=True)
class AppShortcutProfile:
    package: str
    deep_links: tuple[DeepLink, ...] = ()
    deep_intents: tuple[DeepIntent, ...] = ()
    activity_aliases: tuple[tuple[str, str], ...] = ()
    manifest_meta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"package": self.package,
                "deep_links": [dl.to_dict() for dl in self.deep_links],
                "deep_intents": [di.to_dict() for di in self.deep_intents],
                "activity_aliases": list(self.activity_aliases),
                "manifest_meta": self.manifest_meta}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AppShortcutProfile":
        return cls(package=d["package"],
                   deep_links=tuple(DeepLink.from_dict(x) for x in d.get("deep_links", [])),
                   deep_intents=tuple(DeepIntent.from_dict(x) for x in d.get("deep_intents", [])),
                   activity_aliases=tuple((a, t) for a, t in d.get("activity_aliases", [])),
                   manifest_meta=d.get("manifest_meta"))


async def extract_app_shortcuts(backend: Any, package: str) -> AppShortcutProfile:
    app = _clean_app(package)
    apk_path = await _pull_apk(backend, app)
    if apk_path is None:
        return AppShortcutProfile(package=app)

    manifest_root = _parse_manifest(apk_path)
    Path(apk_path).unlink(missing_ok=True)
    manifest_package = _clean_string(manifest_root.get("package")) or app
    filters = _extract_all_filters(manifest_root, manifest_package)

    aliases: list[tuple[str, str]] = []
    for alias in _find_elements(manifest_root, "activity-alias"):
        alias_component = _normalize_component_name(manifest_package, _android_attr(alias, "name"))
        target_component = _normalize_component_name(manifest_package, _android_attr(alias, "targetActivity"))
        if alias_component and target_component:
            aliases.append((alias_component, target_component))

    return AppShortcutProfile(
        package=manifest_package,
        deep_links=tuple(_classify_deep_links(filters)),
        deep_intents=tuple(_classify_deep_intents(filters)),
        activity_aliases=tuple(dict.fromkeys(aliases)),
        manifest_meta={"apk_path": apk_path, "filter_count": len(filters)},
    )


def profile_to_skills(profile: AppShortcutProfile) -> list[Any]:
    """Convert each shortcut in *profile* to a 1-step Skill for the skill library."""
    from opengui.skills.data import Skill, SkillStep
    skills: list[Any] = []
    for dl in profile.deep_links:
        step = SkillStep(action_type="open_deeplink", target=dl.uri_template,
                         parameters={"text": dl.uri_template, "component": dl.component})
        raw = f"{profile.package}|{dl.component}|{dl.uri_template}|{dl.path_kind or ''}"
        skills.append(Skill(name=_shortcut_skill_name(dl),
                           app=profile.package, platform="android",
                           description=dl.description, steps=(step,),
                           tags=("shortcut", "deeplink"),
                           skill_id=f"shortcut:dl:{profile.package}:{_stable_short_hash(raw)}"))
    for di in profile.deep_intents:
        step = SkillStep(action_type="open_intent", target=di.action,
                         parameters={"intent_action": di.action, "component": di.component,
                                     "mime_type": di.mime_type or ""})
        raw = f"{profile.package}|{di.component}|{di.action}|{di.mime_type or ''}"
        skills.append(Skill(name=_shortcut_skill_name(di),
                           app=profile.package, platform="android",
                           description=di.description, steps=(step,),
                           tags=("shortcut", "intent"),
                           skill_id=f"shortcut:di:{profile.package}:{_stable_short_hash(raw)}"))
    return skills


def _shortcut_skill_name(shortcut: DeepLink | DeepIntent) -> str:
    if isinstance(shortcut, DeepLink):
        return f"open_{_slug('_'.join(x for x in (shortcut.scheme, shortcut.host or '', shortcut.path or '') if x))}"
    suffix = shortcut.action.split(".")[-1].lower()
    label = "_".join(x for x in (suffix, shortcut.mime_type or "") if x)
    return f"open_{_slug(label)}"


async def _pull_apk(backend: Any, package: str) -> str | None:
    output = await backend._run("shell", "pm", "path", package, timeout=10.0)
    apk_lines = [
        line.removeprefix("package:").strip()
        for line in str(output).splitlines()
        if line.strip().startswith("package:")
    ]
    if not apk_lines:
        return None

    safe_package = re.sub(r"[^A-Za-z0-9_.-]+", "_", package)
    with tempfile.NamedTemporaryFile(suffix=".apk", prefix=f"opengui-{safe_package}-", delete=False) as fd:
        local_path = fd.name
    await backend._run("pull", apk_lines[0], str(local_path), timeout=30.0)
    return local_path


def _parse_manifest(apk_path: str) -> ET.Element:
    from pyaxmlparser import APK

    manifest = APK(apk_path).get_android_manifest_xml()
    if hasattr(manifest, "tag"):
        return manifest
    if isinstance(manifest, bytes):
        return ET.fromstring(manifest)
    return ET.fromstring(str(manifest))


def _extract_all_filters(manifest_root: ET.Element, package: str) -> list[ManifestIntentFilter]:
    filters: list[ManifestIntentFilter] = []
    component_tags = ("activity", "activity-alias")

    for component_element in manifest_root.iter():
        if _local_tag(component_element.tag) not in component_tags:
            continue
        component = _normalize_component_name(package, _android_attr(component_element, "name"))
        if not component:
            continue

        for intent_filter in component_element:
            if _local_tag(intent_filter.tag) != "intent-filter":
                continue
            actions: list[str] = []
            categories: list[str] = []
            schemes: list[str] = []
            authorities: list[str] = []
            paths: list[tuple[str, str]] = []
            mime_types: list[str] = []

            for child in intent_filter:
                tag = _local_tag(child.tag)
                if tag == "action":
                    actions.append(_android_attr(child, "name"))
                elif tag == "category":
                    categories.append(_android_attr(child, "name"))
                elif tag == "data":
                    scheme = _android_attr(child, "scheme")
                    host = _android_attr(child, "host")
                    port = _android_attr(child, "port")
                    if scheme:
                        schemes.append(scheme)
                    if host and port:
                        authorities.append(f"{host}:{port}")
                    elif host:
                        authorities.append(host)
                    mime_type = _android_attr(child, "mimeType")
                    if mime_type:
                        mime_types.append(mime_type)
                    for path_attr in ("path", "pathPrefix", "pathPattern", "pathAdvancedPattern", "pathSuffix"):
                        path = _android_attr(child, path_attr)
                        if path:
                            paths.append((path_attr, path))

            filters.append(
                ManifestIntentFilter(
                    component=component,
                    actions=tuple(_dedupe(actions)),
                    categories=tuple(_dedupe(categories)),
                    schemes=tuple(_dedupe(schemes)),
                    authorities=tuple(_dedupe(authorities)),
                    paths=tuple(_dedupe_path_specs(paths)),
                    mime_types=tuple(_dedupe(mime_types)),
                )
            )

    return filters


def _classify_deep_links(filters: list[ManifestIntentFilter]) -> list[DeepLink]:
    results: list[DeepLink] = []
    seen: set[tuple[str, str | None, str | None, str | None, str]] = set()

    for item in filters:
        if "android.intent.action.VIEW" not in item.actions:
            continue
        if "android.intent.category.BROWSABLE" not in item.categories:
            continue
        for scheme in item.schemes:
            if scheme.casefold() in {"http", "https"}:
                continue
            hosts = item.authorities or ("",)
            if item.authorities:
                paths = item.paths or (("", ""),)
            else:
                paths = (("", ""),)
            for host in hosts:
                host_value = host or None
                for path_kind, path in paths:
                    if path_kind not in {"", "path", "pathPrefix"}:
                        continue
                    path_value = path or None
                    if host_value and path_value:
                        path_part = path if path.startswith("/") else f"/{path}"
                        uri_template = f"{scheme}://{host_value}{path_part}"
                    elif host_value:
                        uri_template = f"{scheme}://{host_value}"
                    else:
                        uri_template = f"{scheme}:"
                    if not _usable_data_uri(uri_template):
                        continue
                    key = (scheme, host_value, path_value, path_kind or None, item.component)
                    if key in seen:
                        continue
                    seen.add(key)
                    kind_label = f" with {path_kind}={path_value}" if path_kind else ""
                    results.append(
                        DeepLink(
                            uri_template=uri_template,
                            scheme=scheme,
                            host=host_value,
                            path=path_value,
                            component=item.component,
                            description=(
                                f"Static Android deep link candidate for {uri_template}{kind_label}; "
                                f"component={item.component}; not page-validated."
                            ),
                            path_kind=path_kind or None,
                        )
                    )

    return results


def _classify_deep_intents(filters: list[ManifestIntentFilter]) -> list[DeepIntent]:
    results: list[DeepIntent] = []
    seen: set[tuple[str, str, str | None]] = set()

    for item in filters:
        for action in item.actions:
            if action in {"android.intent.action.MAIN", "android.intent.action.VIEW"}:
                continue
            mime_types: tuple[str | None, ...] = item.mime_types or (None,)
            for mime_type in mime_types:
                key = (action, item.component, mime_type)
                if key in seen:
                    continue
                seen.add(key)
                mime_label = f"; mime_type={mime_type}" if mime_type else ""
                results.append(
                    DeepIntent(
                        action=action,
                        component=item.component,
                        mime_type=mime_type,
                        description=(
                            f"Static Android intent candidate for action={action}{mime_label}; "
                            f"component={item.component}; not page-validated."
                        ),
                    )
                )

    return results


async def probe_deep_link(backend: Any, dl: DeepLink) -> bool:
    args = [
        "shell", "cmd", "package", "resolve-activity", "--brief",
        "-a", "android.intent.action.VIEW",
        "-c", "android.intent.category.BROWSABLE",
        "-d", dl.uri_template,
    ]
    output = await backend._run(*args, timeout=5.0)
    text = str(output).strip()
    return bool(text and "No activity found" not in text)


async def probe_deep_intent(backend: Any, di: DeepIntent) -> bool:
    args = ["shell", "cmd", "package", "resolve-activity", "--brief", "-a", di.action]
    if di.mime_type:
        args.extend(["-t", di.mime_type])
    if di.component:
        args.extend(["-n", di.component])
    output = await backend._run(*args, timeout=5.0)
    text = str(output).strip()
    return bool(text and "No activity found" not in text)


def _local_tag(tag: str) -> str:
    text = str(tag)
    if "}" in text:
        return text.rsplit("}", 1)[1]
    if ":" in text:
        return text.split(":", 1)[1]
    return text


def _android_attr(element: ET.Element, name: str) -> str:
    value = element.get(f"{{{_ANDROID_NS}}}{name}")
    if value is None:
        value = element.get(f"android:{name}")
    if value is None:
        value = element.get(name)
    return _clean_string(value)


def _normalize_component_name(package: str, name: str) -> str:
    app = _clean_app(package)
    text = _clean_string(name)
    if not app or not text:
        return ""
    if text.startswith("."):
        text = f"{app}{text}"
    elif "." not in text:
        text = f"{app}.{text}"
    return f"{app}/{text}"


def _find_elements(root: ET.Element, tag: str) -> list[ET.Element]:
    return [element for element in root.iter() if _local_tag(element.tag) == tag]


def _dedupe(items: list[str] | tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = str(item).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _dedupe_path_specs(items: list[tuple[str, str]] | tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for kind, value in items:
        cleaned_kind = str(kind).strip()
        cleaned_value = str(value).strip()
        key = (cleaned_kind, cleaned_value)
        if cleaned_kind and cleaned_value and key not in seen:
            seen.add(key)
            result.append(key)
    return result


def _stable_short_hash(text: str, n: int = 10) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def _slug(value: str, *, max_len: int = 80) -> str:
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    return (text or "shortcut")[:max_len]


def _clean_app(value: Any) -> str:
    return str(value or "").strip()


def _usable_data_uri(uri: str) -> bool:
    try:
        return bool(urlparse(uri).scheme)
    except Exception:
        return False
