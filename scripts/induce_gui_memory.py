#!/usr/bin/env python3
"""Induce lightweight GuiMemoryItem entries from MobileWorld GUI trajectories.

Usage::

    # Extract memory items from a single task trace (dry-run)
    python scripts/induce_gui_memory.py \\
        --trace-dir ~/Project/MobileWorld_fork/traj_logs/v2/SomeTask \\
        --dry-run

    # Batch-extract from all tasks in a trace root
    python scripts/induce_gui_memory.py \\
        --trace-root ~/Project/MobileWorld_fork/traj_logs/v2 \\
        --model deepseek-v4-pro \\
        --base-url https://...

    # Optional: also keep a JSONL backup/debug bank
    python scripts/induce_gui_memory.py --trace-dir ... --memory-bank gui_memory_bank.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

# -- project imports (require nanobot_fork on PYTHONPATH) --------------------
try:
    from opengui.memory.gui_memory_item import GuiMemoryItem
except ImportError:
    # Lightweight fallback when running standalone (without PYTHONPATH)
    from dataclasses import dataclass, field

    @dataclass(frozen=True)
    class GuiMemoryItem:
        title: str
        description: str
        content: str
        status: str = "success"
        app: str | None = None
        created_at: float = field(default_factory=time.time)

        def to_dict(self) -> dict[str, Any]:
            return {
                "title": self.title,
                "description": self.description,
                "content": self.content,
                "status": self.status,
                "app": self.app,
                "created_at": self.created_at,
            }

        @classmethod
        def from_dict(cls, data: dict[str, Any]) -> "GuiMemoryItem":
            return cls(
                title=data["title"],
                description=data["description"],
                content=data["content"],
                status=data.get("status", "success"),
                app=data.get("app"),
                created_at=data.get("created_at", time.time()),
            )


# ---------------------------------------------------------------------------
# Prompt templates (adapted from reasoning-bank)
# ---------------------------------------------------------------------------

SUCCESS_SYSTEM_PROMPT = """\
You are an expert in Android GUI automation. You will be given a user task query
and the corresponding trajectory that represents **how an agent successfully
accomplished the task**.

## Guidelines
You need to extract and summarize useful insights in the format of memory items
based on the agent's successful trajectory.  The goal of summarized memory items
is to be helpful and generalizable for future similar tasks.

## Important notes
- You must first think why the trajectory is successful, and then summarize
  the insights.
- You can extract *at most 3* memory items from the trajectory.
- You must not repeat similar or overlapping items.
- Prefer concrete, actionable procedures over abstract principles.  Do not
  embed specific product names, queries, or literal string contents from the
  task.
- For Android GUI tasks, focus on: app navigation patterns, form-filling
  strategies, common UI pitfalls that were avoided, and efficient action
  sequences.
- When UI snippets are present in the trajectory, ground lessons in the actual
  visible/clickable controls rather than only repeating the agent's own
  reasoning.

## Output Format
Your output must strictly follow the Markdown format shown below:

```
# Memory Item i
## Title <the title of the memory item>
## Description <one sentence summary describing when to use the memory item>
## Content <1-3 sentences describing the insights learned to successfully
  accomplish similar tasks in the future>
```
"""

FAILURE_SYSTEM_PROMPT = """\
You are an expert in Android GUI automation. You will be given a user task query
and the corresponding trajectory that represents **how an agent attempted to
resolve the task but failed**.

## Guidelines
You need to extract and summarize useful insights in the format of memory items
based on the agent's failed trajectory.  The goal of summarized memory items is
to be helpful and generalizable for future similar tasks.

## Important notes
- You must first reflect and think why the trajectory failed, and then
  summarize what lessons you have learned or strategies to prevent the failure
  in the future.
- You can extract *at most 3* memory items from the trajectory.
- You must not repeat similar or overlapping items.
- Prefer concrete, actionable recovery procedures over abstract principles.
  Do not embed specific product names, queries, or literal string contents
  from the task.
- For Android GUI tasks, focus on: navigation mistakes, form-filling errors,
  premature task completion, app state assumptions that were wrong, and
  specific UI patterns that caused trouble.
- When UI snippets are present in the trajectory, ground lessons in the actual
  visible/clickable controls rather than only repeating the failed agent's own
  reasoning.

## Output Format
Your output must strictly follow the Markdown format shown below:

```
# Memory Item i
## Title <the title of the memory item>
## Description <one sentence summary describing when NOT to use this approach>
## Content <1-3 sentences describing the insights learned to avoid such
  failures in the future>
```
"""


# ---------------------------------------------------------------------------
# Trajectory formatting (JSONL → LLM-readable text)
# ---------------------------------------------------------------------------

def format_trajectory_compact(
    trace_path: Path,
    *,
    max_steps_full: int = 30,
    keep_first: int = 3,
    keep_last: int = 10,
    thought_max_chars: int = 200,
    ui_hint_max_chars: int = 240,
) -> str | None:
    """Convert a MobileWorld JSONL trace into compact LLM-readable text.

    Returns ``None`` when the trace contains no usable steps.
    """
    events = _load_jsonl(trace_path)
    if not events:
        return None

    task_goal = _find_task_goal(events) or trace_path.stem
    steps = [e for e in events if _event_type(e) == "step"]

    # -- build step lines ----------------------------------------------------
    step_lines: list[str] = []
    for step in steps:
        action = step.get("action") or {}
        atype = action.get("action_type", "?")
        observation = step.get("observation") or {}
        obs_app = observation.get("foreground_app", "") or "?"
        thought = _extract_thought(step.get("model_output") or "")
        extra = observation.get("extra") or {}
        ui_hint = _step_ui_hint(extra, max_chars=ui_hint_max_chars)

        if len(thought) > thought_max_chars:
            thought = thought[: thought_max_chars - 3] + "..."

        idx = step.get("step_index", len(step_lines))
        line = f"  Step {idx} [{atype}] ({obs_app}): {thought}"
        if ui_hint:
            line += f" | UI: {ui_hint}"
        step_lines.append(line)

    if not step_lines:
        return None

    # -- truncate long trajectories ------------------------------------------
    if len(step_lines) > max_steps_full:
        omitted = len(step_lines) - keep_first - keep_last
        step_lines = (
            step_lines[:keep_first]
            + [f"  ... ({omitted} steps omitted) ..."]
            + step_lines[-keep_last:]
        )

    # -- assemble output -----------------------------------------------------
    parts: list[str] = [
        f"Task: {task_goal}",
        "",
        "Action sequence:",
        *step_lines,
    ]

    # -- skill execution failures --------------------------------------------
    skill_failures = [
        e
        for e in events
        if _event_type(e) == "skill_execution_result" and e.get("state") == "failed"
    ]
    if skill_failures:
        parts.append("")
        parts.append("Skill execution failures:")
        for sf in skill_failures:
            skill_name = sf.get("skill_name", "?")
            error = sf.get("error", "") or "unknown"
            parts.append(f"  - {skill_name}: {_truncate(error, 200)}")

    # -- final result error --------------------------------------------------
    result = _find_result(events)
    if result and result.get("error"):
        parts.extend([
            "",
            f"Final error: {_truncate(str(result['error']), 200)}",
        ])

    return "\n".join(parts).rstrip()


# ---------------------------------------------------------------------------
# Memory induction (LLM call)
# ---------------------------------------------------------------------------

MEMORY_ITEM_RE = re.compile(
    r"# Memory Item \d+\s*\n"
    r"## Title\s*(.+?)\s*\n"
    r"## Description\s*(.+?)\s*\n"
    r"## Content\s*(.+?)(?=\n# Memory Item|\n?\Z)",
    re.DOTALL,
)


def parse_memory_items(text: str, *, app: str | None = None) -> list[GuiMemoryItem]:
    """Parse LLM output into GuiMemoryItem objects."""
    items: list[GuiMemoryItem] = []
    for match in MEMORY_ITEM_RE.finditer(text):
        title = match.group(1).strip()
        description = match.group(2).strip()
        content = match.group(3).strip()
        if title and content:
            items.append(GuiMemoryItem(
                title=title,
                description=description,
                content=content,
                status="success",  # caller should override for failure traces
                app=app,
            ))
    return items


async def induce_memory_items(
    *,
    trajectory_text: str,
    task_outcome: str,  # "success" | "failure"
    app: str | None = None,
    api_key: str,
    base_url: str,
    model: str,
    max_tokens: int = 2048,
    temperature: float = 0.7,
) -> list[GuiMemoryItem]:
    """Call LLM to induce memory items from a formatted trajectory.

    Returns a list of GuiMemoryItem (0-3 items).
    """
    from openai import AsyncOpenAI

    system_prompt = (
        SUCCESS_SYSTEM_PROMPT if task_outcome == "success" else FAILURE_SYSTEM_PROMPT
    )
    user_prompt = trajectory_text

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    content = response.choices[0].message.content or ""
    items = parse_memory_items(content, app=app)

    # Set correct status
    for item in items:
        object.__setattr__(item, "status", task_outcome)

    return items


# ---------------------------------------------------------------------------
# Task outcome detection
# ---------------------------------------------------------------------------

def get_task_outcome(task_dir: Path) -> tuple[str, str]:
    """Return (outcome, error_message) for a task directory.

    outcome is "success" when result.txt score >= 1.0, otherwise "failure".
    """
    result_txt = task_dir / "result.txt"
    if not result_txt.exists():
        return "failure", "no result.txt found"

    text = result_txt.read_text(encoding="utf-8", errors="ignore")
    score_match = re.search(r"(?m)^score:\s*([0-9.]+)", text)
    if not score_match:
        return "failure", "no score field in result.txt"

    try:
        score = float(score_match.group(1))
    except ValueError:
        return "failure", f"unparseable score: {score_match.group(1)!r}"

    if score >= 1.0:
        return "success", ""
    return "failure", f"score={score}"


# ---------------------------------------------------------------------------
# Memory bank I/O
# ---------------------------------------------------------------------------

DEFAULT_MEMORY_BANK_PATH = Path.home() / ".opengui" / "memory" / "gui_memory_bank.jsonl"


def load_memory_bank(path: Path) -> list[GuiMemoryItem]:
    """Load all items from a JSONL memory bank."""
    if not path.exists():
        return []
    items: list[GuiMemoryItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(GuiMemoryItem.from_dict(json.loads(line)))
        except (json.JSONDecodeError, KeyError) as exc:
            print(f"Warning: skipping malformed line in {path}: {exc}", file=sys.stderr)
    return items


def append_to_memory_bank(items: list[GuiMemoryItem], path: Path) -> None:
    """Append items to a JSONL memory bank, skipping exact (title, content) duplicates."""
    existing = load_memory_bank(path)
    seen = {(item.title.strip(), item.content.strip()) for item in existing}

    new_count = 0
    with open(path, "a", encoding="utf-8") as fh:
        for item in items:
            key = (item.title.strip(), item.content.strip())
            if key in seen:
                continue
            fh.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
            seen.add(key)
            new_count += 1

    if new_count:
        print(f"Appended {new_count} new item(s) to {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    # Format-only mode (standalone, no other args required)
    p.add_argument("--format-only", type=Path,
                   help="Format a single trace file and print to stdout, then exit")
    # Input sources
    src = p.add_mutually_exclusive_group()
    src.add_argument("--trace-dir", type=Path, help="Single task trace directory")
    src.add_argument("--trace-root", type=Path, help="Root directory with many task subdirs")

    # Output
    p.add_argument("--memory-bank", type=Path, default=DEFAULT_MEMORY_BANK_PATH,
                   help=f"JSONL memory bank path (default: {DEFAULT_MEMORY_BANK_PATH})")

    # LLM config
    p.add_argument("--model", default=os.getenv("MEMORY_INDUCE_MODEL", "deepseek-v4-pro"))
    p.add_argument("--base-url", default=os.getenv("MEMORY_INDUCE_BASE_URL", ""))
    p.add_argument("--api-key-env", default="OPENAI_API_KEY")
    p.add_argument("--max-tokens", type=int, default=2048)
    p.add_argument("--temperature", type=float, default=0.7)

    # Filtering
    p.add_argument("--task", action="append", dest="tasks",
                   help="Only process specific task(s). Repeatable.")
    p.add_argument("--limit", type=int, default=0,
                   help="Max number of tasks to process (0 = unlimited)")

    # Modes
    p.add_argument("--dry-run", action="store_true",
                   help="Print formatted trajectories and exit without LLM calls")

    return p.parse_args()


async def main_async(args: argparse.Namespace) -> int:
    # -- format-only mode ----------------------------------------------------
    if args.format_only:
        text = format_trajectory_compact(args.format_only)
        if text is None:
            print("No usable steps found in trace.", file=sys.stderr)
            return 1
        print(text)
        return 0

    # -- validate input source -----------------------------------------------
    if not args.trace_dir and not args.trace_root:
        print("Error: --trace-dir or --trace-root is required (or use --format-only).",
              file=sys.stderr)
        return 1

    # -- collect task dirs ---------------------------------------------------
    if args.trace_dir:
        task_dirs = [args.trace_dir]
    else:
        assert args.trace_root is not None
        root = args.trace_root.expanduser()
        task_dirs = sorted(
            d for d in root.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
        if args.tasks:
            task_dirs = [d for d in task_dirs if d.name in set(args.tasks)]

    if args.limit > 0:
        task_dirs = task_dirs[: args.limit]

    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        return 1

    # -- process each task ---------------------------------------------------
    api_key = os.getenv(args.api_key_env, "")
    if not api_key and not args.dry_run:
        print(f"Error: {args.api_key_env} not set. Use --dry-run to skip LLM calls.",
              file=sys.stderr)
        return 1

    all_items: list[GuiMemoryItem] = []
    for task_dir in task_dirs:
        task_name = task_dir.name

        # Find one trace per GUI task run, matching the skill extraction job discovery.
        trace_paths = _find_gui_task_traces(task_dir)
        if not trace_paths:
            print(f"[SKIP] {task_name}: no trace found")
            continue

        # Determine outcome
        outcome, error_msg = get_task_outcome(task_dir)

        formatted_jobs: list[tuple[Path, str, int]] = []
        skipped_short = 0
        skipped_empty = 0
        for trace_path in trace_paths:
            step_count = _trace_step_count(trace_path)
            if step_count <= 2:
                skipped_short += 1
                continue
            trajectory_text = format_trajectory_compact(trace_path)
            if trajectory_text is None:
                skipped_empty += 1
                continue
            formatted_jobs.append((trace_path, trajectory_text, step_count))

        if not formatted_jobs:
            detail = []
            if skipped_short:
                detail.append(f"{skipped_short} short trace(s)")
            if skipped_empty:
                detail.append(f"{skipped_empty} empty trace(s)")
            suffix = f" ({', '.join(detail)})" if detail else ""
            print(f"[SKIP] {task_name}: no memory-worthy GUI task traces{suffix}")
            continue

        if args.dry_run:
            print(f"\n{'='*60}")
            print(f"Task: {task_name}  Outcome: {outcome}")
            if error_msg:
                print(f"Error: {error_msg}")
            print("Traces:")
            for trace_path, _, step_count in formatted_jobs:
                print(f"  - {trace_path} ({step_count} steps)")
            if skipped_short or skipped_empty:
                print(f"Skipped: {skipped_short} short, {skipped_empty} empty")
            print(f"{'='*60}")
            for trace_path, trajectory_text, _ in formatted_jobs:
                print(f"\n--- GUI task trace: {trace_path.parent.name} ---")
                print(trajectory_text[:1500])
                if len(trajectory_text) > 1500:
                    print(f"... ({len(trajectory_text)} chars total)")
            continue

        # Call LLM once per memory-worthy GUI task trace.
        task_items: list[GuiMemoryItem] = []
        print(f"[{outcome.upper()[:3]}] {task_name} ... ", end="", flush=True)
        for trace_path, trajectory_text, _ in formatted_jobs:
            try:
                items = await induce_memory_items(
                    trajectory_text=trajectory_text,
                    task_outcome=outcome,
                    app=_guess_app(task_name),
                    api_key=api_key,
                    base_url=args.base_url,
                    model=args.model,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                )
            except Exception as exc:
                print(f"\n  {trace_path}: LLM error: {exc}")
                continue
            task_items.extend(items)

        print(f"{len(task_items)} item(s)")
        all_items.extend(task_items)

    # -- write memory bank ---------------------------------------------------
    if all_items:
        bank_path = args.memory_bank.expanduser()
        bank_path.parent.mkdir(parents=True, exist_ok=True)
        append_to_memory_bank(all_items, bank_path)
        print(f"\nTotal: {len(all_items)} new memory item(s) in {bank_path}")

    return 0


def main() -> None:
    raise SystemExit(asyncio.run(main_async(parse_args())))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _event_type(event: dict[str, Any]) -> str:
    return str(event.get("type") or event.get("event") or "")


def _find_task_goal(events: list[dict[str, Any]]) -> str:
    for e in events:
        if _event_type(e) == "metadata":
            return str(e.get("task") or "")
    return ""


def _find_result(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for e in reversed(events):
        if _event_type(e) == "result":
            return e
    return None


def _extract_thought(model_output: Any) -> str:
    """Extract the 'Thought' portion from a model_output string."""
    if isinstance(model_output, dict):
        text = str(
            model_output.get("raw_content")
            or model_output.get("action_text")
            or model_output.get("action_summary")
            or model_output.get("state_summary")
            or ""
        )
    else:
        text = str(model_output or "")
    # Split on "Action:" and take everything before
    for delimiter in ("\nAction:", "Action:"):
        idx = text.find(delimiter)
        if idx >= 0:
            text = text[:idx]
            break
    return text.replace("Thought:", "").strip()


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3] + "..."


def _step_ui_hint(extra: dict[str, Any], *, max_chars: int) -> str:
    """Return a compact UI snippet from visible/clickable observation text."""
    if not isinstance(extra, dict):
        return ""
    values: list[str] = []
    for key in ("clickable_text", "visible_text", "content_desc"):
        raw_values = extra.get(key)
        if not isinstance(raw_values, list):
            continue
        for value in raw_values:
            text = str(value).strip()
            if text:
                values.append(text)
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        deduped.append(value)
        seen.add(value)
        if len(deduped) >= 12:
            break
    return _truncate(", ".join(deduped), max_chars) if deduped else ""


def _find_gui_task_traces(task_dir: Path) -> list[Path]:
    """Find one primary trace JSONL for each GUI task run under a task dir."""
    run_dir = task_dir / "nanobot_gui_task_runs"
    if not run_dir.exists():
        return []
    traces: list[Path] = []
    for gui_task_dir in sorted(path for path in run_dir.iterdir() if path.is_dir()):
        trace_path = _select_trace_file(gui_task_dir)
        if trace_path is not None:
            traces.append(trace_path)
    return traces


def _select_trace_file(run_dir: Path) -> Path | None:
    """Select the primary trace for one GUI task run, following skill extraction."""
    candidates = sorted(run_dir.glob("trace*.jsonl"))
    if not candidates:
        candidates = sorted(run_dir.glob("*.jsonl"))
    if not candidates:
        candidates = sorted(run_dir.rglob("trace*.jsonl"))
    if not candidates:
        candidates = sorted(run_dir.rglob("*.jsonl"))
    if not candidates:
        return None
    for name in ("trace.jsonl",):
        for path in candidates:
            if path.name == name:
                return path
    return candidates[0]


def _trace_step_count(trace_path: Path) -> int:
    return sum(1 for event in _load_jsonl(trace_path) if _event_type(event) == "step")


def _guess_app(task_name: str) -> str | None:
    """Heuristic: map task name to likely Android app.

    Explicit app names are checked FIRST to avoid generic keywords
    (``event``, ``send``) matching ``Mail`` before ``Calendar``, etc.
    """
    lowered = task_name.lower()

    # Explicit app names (most specific first, before generic keywords)
    if "mattermost" in lowered:
        return "com.mattermost.rnbeta"
    if "mastodon" in lowered:
        return "org.joinmastodon.android.mastodon"
    if "calendar" in lowered or "schedule" in lowered or "conference" in lowered:
        return "org.fossify.calendar"
    if "alarm" in lowered or "clock" in lowered:
        return "com.google.android.deskclock"
    if "chrome" in lowered or "github" in lowered or "search" in lowered:
        return "com.android.chrome"
    if "settings" in lowered or "airplane" in lowered or "flight" in lowered:
        return "com.android.settings"
    if any(k in lowered for k in ("cart", "mall", "checkout", "item", "taodian")):
        return "com.testmall.app"
    if any(k in lowered for k in ("photo", "gallery", "wallpaper", "selfie")):
        return "gallery.photomanager.picturegalleryapp.imagegallery"
    if any(k in lowered for k in ("file", "download", "count", "sum", "bid")):
        return "com.google.android.documentsui"

    # Generic keywords (only after explicit app names)
    if any(k in lowered for k in ("mail", "email", "gmail", "meeting", "send",
                                    "event", "receipt", "invoice")):
        return "com.gmailclone"

    return None


if __name__ == "__main__":
    main()
