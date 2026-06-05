#!/usr/bin/env python3
"""Extract APP_GUIDE / OS_GUIDE memory entries from failed GUI trajectories.

Usage:
  # Dry-run: inspect trajectories and print suggested memory entries
  python scripts/extract_failure_memory.py --trace-root <path> --dry-run

  # Write entries to ~/.opengui/memory/
  python scripts/extract_failure_memory.py --trace-root <path> --write
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

DEFAULT_TRACE_ROOT = Path.home() / "Project/MobileWorld_fork/traj_logs/nanobot_gui_only_35b_compact_skills_v2"
DEFAULT_OPENGUI_MEMORY_DIR = Path.home() / ".opengui" / "memory"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trace-root", type=Path, default=DEFAULT_TRACE_ROOT)
    p.add_argument("--memory-dir", type=Path, default=DEFAULT_OPENGUI_MEMORY_DIR)
    p.add_argument("--dry-run", action="store_true", default=True,
                   help="Print suggestions without writing (default)")
    p.add_argument("--write", dest="dry_run", action="store_false",
                   help="Write entries to opengui memory store")
    p.add_argument("--task", action="append", dest="tasks",
                   help="Only process specific task(s)")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Pattern detectors — each returns (MemoryEntry | None) for a failed trace
# ---------------------------------------------------------------------------

# We need to import these lazily so the script works standalone
def _import_opengui_types():
    try:
        from opengui.memory.types import MemoryEntry, MemoryType
        return MemoryEntry, MemoryType
    except ImportError:
        # Fallback for environments without nanobot in path
        from dataclasses import dataclass, field
        from enum import Enum

        class MemoryType(str, Enum):
            OS_GUIDE = "os"
            APP_GUIDE = "app"
            ICON_GUIDE = "icon"
            POLICY = "policy"

        @dataclass(frozen=True)
        class MemoryEntry:
            entry_id: str
            memory_type: "MemoryType"
            platform: str
            content: str
            app: str | None = None
            tags: tuple[str, ...] = ()
            created_at: float = field(default_factory=time.time)
            access_count: int = 0

        return MemoryEntry, MemoryType


def detect_email_attachment_navigation_lost(
    task_name: str,
    events: list[dict[str, Any]],
) -> str | None:
    """Detect: Model left email compose to view attachment, lost compose state on return."""
    if "mail" not in task_name.lower() and "email" not in task_name.lower():
        return None

    # Check if model visited another app then pressed back multiple times
    back_count = 0
    left_mail = False
    visited_other_app = False
    prev_app = ""

    for e in events:
        if e.get("type") != "step":
            continue
        action = e.get("action", {}) or {}
        atype = action.get("action_type", "")
        obs_app = (e.get("observation") or {}).get("foreground_app", "")

        if "mail" in prev_app.lower() and "mail" not in obs_app.lower():
            left_mail = True
        if left_mail and obs_app and "mail" not in obs_app.lower():
            visited_other_app = True
        if atype == "back":
            back_count += 1

        prev_app = obs_app

    if visited_other_app and back_count >= 2:
        return (
            "When you leave the Mail compose screen to view an attachment or file in "
            "another app (Files, Gallery, Chrome), do NOT press 'back' repeatedly to "
            "return. Multiple back presses may exit the compose screen entirely or "
            "land on the home screen, losing your draft. Instead, after viewing the "
            "file, press the Home button, then reopen Mail from the home screen. "
            "The draft email is usually auto-saved and accessible from the inbox."
        )
    return None


def detect_adb_skill_used_on_wrong_state(
    task_name: str,
    events: list[dict[str, Any]],
) -> str | None:
    """Detect: adb_read_sent_email used on drafts (not sent emails)."""
    for e in events:
        if e.get("type") == "skill_execution_result" and e.get("state") == "failed":
            error = str(e.get("error", ""))
            skill_name = str(e.get("skill_name", ""))
            if "read_sent_email" in skill_name and "No such file" in error:
                return (
                    "adb_read_sent_email only works on SENT emails, not drafts. "
                    "If the email hasn't been sent yet, the sentEmail.json file does "
                    "not exist. Do not use adb_read_sent_email to read draft content. "
                    "Use the GUI to view draft attachments instead."
                )
    return None


def detect_time_picker_am_pm_loop(
    task_name: str,
    events: list[dict[str, Any]],
) -> str | None:
    """Detect: 4+ consecutive time-related tap actions suggesting AM/PM confusion."""
    if "calendar" not in task_name.lower():
        return None

    time_steps = []
    for e in events:
        if e.get("type") != "step":
            continue
        thought = (e.get("model_output", "") or "")[:300]
        if any(word in thought.lower() for word in ("am", "pm", "time picker", "10:00", "10:30")):
            time_steps.append(e)

    if len(time_steps) >= 4:
        return (
            "The Fossify Calendar event editor uses a 12-hour time picker with "
            "separate AM/PM toggle. Common pitfall: after selecting the hour, the "
            "AM/PM may stay on the previous value. Always verify the AM/PM indicator "
            "before pressing OK. The start time and end time fields are edited "
            "separately — confirm each one individually. If you find yourself "
            "toggling AM/PM repeatedly, stop and visually verify the current state "
            "of BOTH time fields before making further changes."
        )
    return None


def detect_mastodon_repetitive_keyword_loop(
    task_name: str,
    events: list[dict[str, Any]],
) -> str | None:
    """Detect: Repeated add-keyword patterns in Mastodon filter tasks."""
    if "mastodon" not in task_name.lower() and "filter" not in task_name.lower():
        return None

    add_word_count = 0
    for e in events:
        if e.get("type") != "step":
            continue
        thought = (e.get("model_output", "") or "")[:300]
        if "add word" in thought.lower() or "add muted word" in thought.lower():
            add_word_count += 1

    if add_word_count >= 4:
        return (
            "When adding multiple muted words/filters in Mastodon: each keyword "
            "requires exactly 3 steps: (1) tap 'Add word', (2) type the keyword, "
            "(3) tap 'Add' to confirm. There is NO bulk or batch-add feature. "
            "Budget 3 actions per keyword. If you have 5 keywords, expect at least "
            "15 steps just for keyword entry, plus navigation overhead. If you are "
            "close to the step limit, reduce optional verification steps."
        )
    return None


def detect_gallery_multi_folder_organization(
    task_name: str,
    events: list[dict[str, Any]],
) -> str | None:
    """Detect: Select all photos at once when need to split into multiple folders."""
    if "photo" not in task_name.lower():
        return None

    moved_all_at_once = False
    had_multiple_folders = False
    for e in events:
        if e.get("type") != "step":
            continue
        thought = (e.get("model_output", "") or "")[:300]
        if "all" in thought.lower() and "select" in thought.lower():
            moved_all_at_once = True
        if "paris" in thought.lower() and "tokyo" in thought.lower():
            had_multiple_folders = True

    if moved_all_at_once and had_multiple_folders:
        return (
            "When organizing photos into MULTIPLE folders in Gallery: do NOT select "
            "all photos at once. Instead, select only the photos for ONE folder, "
            "create that folder and move them. Then go back and repeat for the next "
            "folder. If you select all photos and move them into one folder, you "
            "cannot split them afterwards without additional steps."
        )
    return None


# ---------------------------------------------------------------------------
# Main extraction logic
# ---------------------------------------------------------------------------


def load_events(trace_path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in trace_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def find_last_trace(task_dir: Path) -> Path | None:
    run_dir = task_dir / "nanobot_gui_task_runs"
    if not run_dir.exists():
        return None
    attempts = sorted(run_dir.iterdir())
    if not attempts:
        return None
    last_attempt = attempts[-1]
    traces = sorted(last_attempt.glob("trace_*.jsonl"))
    return traces[-1] if traces else None


def get_app_for_task(task_name: str) -> str | None:
    """Heuristic: map task name to likely app.

    Explicit app names are checked FIRST to avoid generic keywords
    (``event``, ``send``) matching ``Mail`` before ``Calendar``, etc.
    """
    task_lower = task_name.lower()
    # Explicit app names (most specific first)
    if any(k in task_lower for k in ("mattermost",)):
        return "com.mattermost.rnbeta"
    if any(k in task_lower for k in ("mastodon",)):
        return "org.joinmastodon.android.mastodon"
    if any(k in task_lower for k in ("calendar", "schedule", "conference")):
        return "org.fossify.calendar"
    if any(k in task_lower for k in ("cart", "taodian", "mall", "checkout", "item")):
        return "com.testmall.app"
    if any(k in task_lower for k in ("photo", "gallery", "wallpaper", "selfie")):
        return "gallery.photomanager.picturegalleryapp.imagegallery"
    if any(k in task_lower for k in ("file", "download", "invoice", "receipt")):
        return "com.google.android.documentsui"
    # Generic keywords (only after explicit app names)
    if any(k in task_lower for k in ("mail", "email", "gmail", "meeting", "event", "send")):
        return "com.gmailclone"
    return None


# All detectors in priority order
DETECTORS = [
    ("email_attachment_nav_lost", detect_email_attachment_navigation_lost),
    ("adb_skill_wrong_state", detect_adb_skill_used_on_wrong_state),
    ("time_picker_am_pm_loop", detect_time_picker_am_pm_loop),
    ("mastodon_repetitive_keywords", detect_mastodon_repetitive_keyword_loop),
    ("gallery_multi_folder", detect_gallery_multi_folder_organization),
]


def analyze_task(task_dir: Path) -> list[dict[str, Any]]:
    """Analyze a single failed task and return suggested memory entries."""
    task_name = task_dir.name
    trace_path = find_last_trace(task_dir)
    if trace_path is None:
        return []

    events = load_events(trace_path)

    # Confirm it's a failure
    last_error = ""
    for e in events:
        if e.get("type") == "result":
            if e.get("success") is not False and not e.get("error"):
                return []  # Skip succeeded tasks for now
            last_error = e.get("error", "")

    suggestions = []
    for detector_name, detector_fn in DETECTORS:
        content = detector_fn(task_name, events)
        if content is None:
            continue

        app = get_app_for_task(task_name)
        entry = {
            "detector": detector_name,
            "entry_id": f"mw_failure_{detector_name}_{_safe_id(task_name)}",
            "memory_type": "app" if app else "os",
            "platform": "android",
            "app": app,
            "content": content,
            "tags": ("mobileworld", "failure-analysis", detector_name),
        }
        suggestions.append(entry)

    return suggestions


def _safe_id(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name.lower())[:40]


def main() -> None:
    args = parse_args()
    MemoryEntry, MemoryType = _import_opengui_types()

    trace_root = args.trace_root.expanduser()
    task_dirs = (
        [trace_root / t for t in args.tasks]
        if args.tasks
        else sorted(d for d in trace_root.iterdir() if d.is_dir())
    )

    all_suggestions: list[dict[str, Any]] = []
    for task_dir in task_dirs:
        suggestions = analyze_task(task_dir)
        if suggestions:
            all_suggestions.extend(suggestions)
            print(f"\n{'='*70}")
            print(f"Task: {task_dir.name}")
            for s in suggestions:
                print(f"  Detector: {s['detector']}")
                print(f"  Type: {s['memory_type']}  App: {s['app'] or 'N/A'}")
                print(f"  Content: {s['content'][:200]}...")
                print()

    if not all_suggestions:
        print("No memory-worthy patterns found in the analyzed tasks.")
        return 0

    if args.dry_run:
        print(f"\nDry run — {len(all_suggestions)} suggestion(s) found. Use --write to persist.")
        return 0

    # Write to opengui memory
    from opengui.memory.store import MemoryStore

    store = MemoryStore(args.memory_dir)
    written = 0
    for s in all_suggestions:
        # Check for duplicate
        existing = store.get(s["entry_id"])
        if existing is not None:
            print(f"Skipping duplicate: {s['entry_id']}")
            continue

        entry = MemoryEntry(
            entry_id=s["entry_id"],
            memory_type=MemoryType.APP_GUIDE if s["memory_type"] == "app" else MemoryType.OS_GUIDE,
            platform=s["platform"],
            content=s["content"],
            app=s["app"],
            tags=s["tags"],
        )
        store.add(entry)
        written += 1
        print(f"Written: {s['entry_id']} ({s['memory_type']})")

    print(f"\nDone. {written} new entries written to {args.memory_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
