"""Shared normalization helpers for GUI skill storage identifiers."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from opengui.skills.data import Skill

GUI_SKILLS_DIRNAME = "gui_skills"

_ANDROID_APP_ALIASES = {
    "settings": "com.android.settings",
    "android settings": "com.android.settings",
    "system settings": "com.android.settings",
    "device settings": "com.android.settings",
    "phone settings": "com.android.settings",
    "gmail": "com.google.android.gm",
    "google mail": "com.google.android.gm",
    "google gmail": "com.google.android.gm",
    "chrome": "com.android.chrome",
    "google chrome": "com.android.chrome",
}


def get_gui_skill_store_root(workspace: Path) -> Path:
    return Path(workspace) / GUI_SKILLS_DIRNAME


def normalize_app_identifier(platform: str, app: str) -> str:
    cleaned = " ".join((app or "").strip().strip("\"'").split())
    if not cleaned:
        return "unknown"

    platform_key = (platform or "").strip().lower()
    lowered = cleaned.lower()

    if platform_key == "android":
        if lowered in _ANDROID_APP_ALIASES:
            return _ANDROID_APP_ALIASES[lowered]
        if "." in cleaned:
            return lowered

    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "unknown"


def normalize_skill_app(skill: Skill) -> Skill:
    normalized_app = normalize_app_identifier(skill.platform, skill.app)
    if normalized_app == skill.app:
        return skill
    return replace(skill, app=normalized_app)
