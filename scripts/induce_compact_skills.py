#!/usr/bin/env python3
"""Induce compact, parameterized GUI skills from successful MobileWorld trajectories.

Usage::

    # Extract skills from a single task trace (dry-run)
    python scripts/induce_compact_skills.py \\
        --trace-dir ~/Project/MobileWorld_fork/traj_logs/v2/SomeTask \\
        --dry-run

    # Batch-extract from all successful tasks in a trace root
    python scripts/induce_compact_skills.py \\
        --trace-root ~/Project/MobileWorld_fork/traj_logs/v2 \\
        --output skills.py \\
        --model deepseek-v4-pro \\
        --base-url https://...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# -- project imports ----------------------------------------------------------
try:
    from opengui.skills.flat import CODE_HEADER, compile_flat_skills, export_skills_to_source
except ImportError:
    CODE_HEADER = "from opengui.skills.flat import C, R, action, skill, tag"

# -- reuse trajectory formatting from induce_gui_memory -----------------------
try:
    from scripts.induce_gui_memory import (
        _event_type,
        _extract_thought,
        _find_gui_task_traces,
        _find_task_goal,
        _load_jsonl,
        _step_ui_hint,
        _trace_step_count,
        _truncate,
        get_task_outcome,
    )
except ImportError:
    # Fallback copies for standalone use
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

    def _extract_thought(model_output: Any) -> str:
        if isinstance(model_output, dict):
            text = str(model_output.get("raw_content") or model_output.get("action_text") or "")
        else:
            text = str(model_output or "")
        for delimiter in ("\nAction:", "Action:"):
            idx = text.find(delimiter)
            if idx >= 0:
                text = text[:idx]
                break
        return text.replace("Thought:", "").strip()

    def _truncate(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3] + "..."

    def _step_ui_hint(extra: dict[str, Any], *, max_chars: int) -> str:
        if not isinstance(extra, dict):
            return ""
        values: list[str] = []
        for key in ("clickable_text", "visible_text", "content_desc"):
            raw = extra.get(key)
            if not isinstance(raw, list):
                continue
            for v in raw:
                text = str(v).strip()
                if text:
                    values.append(text)
        deduped: list[str] = []
        seen: set[str] = set()
        for v in values:
            if v in seen:
                continue
            deduped.append(v)
            seen.add(v)
            if len(deduped) >= 12:
                break
        return _truncate(", ".join(deduped), max_chars) if deduped else ""

    def _find_gui_task_traces(task_dir: Path) -> list[Path]:
        run_dir = task_dir / "nanobot_gui_task_runs"
        if not run_dir.exists():
            return []
        traces: list[Path] = []
        for gui_task_dir in sorted(p for p in run_dir.iterdir() if p.is_dir()):
            candidates = sorted(gui_task_dir.glob("trace*.jsonl"))
            if not candidates:
                candidates = sorted(gui_task_dir.rglob("trace*.jsonl"))
            if candidates:
                traces.append(candidates[0])
        return traces

    def _trace_step_count(trace_path: Path) -> int:
        return sum(1 for e in _load_jsonl(trace_path) if _event_type(e) == "step")

    def get_task_outcome(task_dir: Path) -> tuple[str, str]:
        result_txt = task_dir / "result.txt"
        if not result_txt.exists():
            return "failure", "no result.txt found"
        text = result_txt.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"(?m)^score:\s*([0-9.]+)", text)
        if not m:
            return "failure", "no score field"
        try:
            score = float(m.group(1))
        except ValueError:
            return "failure", "unparseable score"
        return ("success", "") if score >= 1.0 else ("failure", f"score={score}")


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

SKILL_SYSTEM_PROMPT = f"""\
You are an expert in Android GUI automation. Given a successful trajectory,
extract up to 3 compact, parameterized GUI skills that the agent can reuse
as shortcuts for common same-screen operations.

## Target format
{CODE_HEADER}

@skill(app="com.example", platform="android",
       tags=["compact", "compact_extracted"],
       skill_id="compact:com.example:short_name",
       name="short_name",
       description="When to use: ...")
async def short_name(device, param1, param2):
    await action("tap", target="stable button label",
                 valid_state="No need to verify")
    await action("input_text", target="{{{{param1}}}}",
                 valid_state="No need to verify")
    await action("tap", target="another stable label",
                 valid_state="No need to verify")
    await action("input_text", target="{{{{param2}}}}",
                 valid_state="No need to verify")

## What is a GOOD compact skill?
A fixed 2-4 step shortcut that operates entirely on ONE screen.  Every
task-specific value (email address, subject text, search query) becomes a
function parameter with {{{{double_braces}}}} placeholders.  Stable UI
labels (button names, field labels, toolbar icons) stay as literal strings.

### GOOD examples (extract these):
  - fill_email_composer(device, to_email, subject):
    tap("To field") → input_text({{to_email}}) → tap("Subject field")
    → input_text({{subject}})

### BAD skills (DO NOT extract):
  - Single-action skills (just one tap or one input_text)
  - Skills containing open_app, scroll, swipe, drag, back, or home
  - App initialisation: dismissing dialogs, setup screens, clearing popups
  - Final actions: send, publish, post, purchase, checkout, delete
  - Skills with 7+ steps

## Flat DSL rules
  - Output ONLY valid Python.  No markdown fences, no explanation text.
  - Use ONLY `await action(...)` calls in function bodies.
  - Action types: tap, long_press, double_tap, input_text, enter, wait.
  - Parameters in targets use {{{{name}}}} syntax (double braces).
  - Use valid_state="No need to verify" for EVERY step.
  - Do NOT use state_contract, fixed, fixed_values, or C.from_dict.
  - skill_id format: compact:<app_package>:<short_name>
  - description format: "When to use: <one sentence>"
  - Tags: ["compact", "compact_extracted"]
  - Extract 0 to 3 skills.  If the trajectory has no reusable same-screen
    subsequence, output nothing.
"""


# ---------------------------------------------------------------------------
# Trajectory formatting for skill induction
# ---------------------------------------------------------------------------

def format_trajectory_for_skill(
    trace_path: Path,
    *,
    max_steps_full: int = 30,
    keep_first: int = 3,
    keep_last: int = 10,
    thought_max_chars: int = 200,
    ui_hint_max_chars: int = 240,
) -> str | None:
    """Convert a trace into LLM-readable text for skill extraction.

    Same as ``format_trajectory_compact`` but enriched with action
    details that help the LLM identify stable UI controls.
    """
    events = _load_jsonl(trace_path)
    if not events:
        return None

    task_goal = _find_task_goal(events) or trace_path.stem
    steps = [e for e in events if _event_type(e) == "step"]

    step_lines: list[str] = []
    for step in steps:
        action = step.get("action") or {}
        atype = action.get("action_type", "?")
        observation = step.get("observation") or {}
        obs_app = observation.get("foreground_app", "") or "?"
        thought = _extract_thought(step.get("model_output") or "")
        extra = observation.get("extra") or {}
        ui_hint = _step_ui_hint(extra, max_chars=ui_hint_max_chars)

        # Include fixed-value hints: coordinates and text
        params = action.get("action_params") or {}
        fixed_detail = ""
        if params:
            parts = []
            if "text" in params and str(params["text"]):
                parts.append(f"text={_truncate(str(params['text']), 60)}")
            if "x" in params and "y" in params:
                parts.append(f"pos=({params['x']}, {params['y']})")
            if parts:
                fixed_detail = " | " + ", ".join(parts)

        if len(thought) > thought_max_chars:
            thought = thought[: thought_max_chars - 3] + "..."

        idx = step.get("step_index", len(step_lines))
        line = f"  Step {idx} [{atype}] ({obs_app}): {thought}"
        if ui_hint:
            line += f" | UI: {ui_hint}"
        if fixed_detail:
            line += fixed_detail
        step_lines.append(line)

    if not step_lines:
        return None

    if len(step_lines) > max_steps_full:
        omitted = len(step_lines) - keep_first - keep_last
        step_lines = (
            step_lines[:keep_first]
            + [f"  ... ({omitted} steps omitted) ..."]
            + step_lines[-keep_last:]
        )

    parts: list[str] = [
        f"Task: {task_goal}",
        "",
        "Action sequence:",
        *step_lines,
    ]

    # Include app info from metadata
    for e in events:
        if _event_type(e) == "metadata":
            fg = (e.get("foreground_app") or "").strip()
            if fg:
                parts.insert(1, f"Foreground app: {fg}")
            break

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Output processing
# ---------------------------------------------------------------------------

def clean_skill_code(text: str) -> str:
    """Strip markdown fences and ensure CODE_HEADER is present."""
    t = (text or "").strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        t = "\n".join(lines).strip()

    if not t or t.upper() == "NO_SKILL":
        return f"{CODE_HEADER}\n"

    if not t.startswith("from opengui.skills.flat import"):
        t = f"{CODE_HEADER}\n\n{t}"
    return t.rstrip() + "\n"


# ---------------------------------------------------------------------------
# Quality filter (adapted from compact_extractor quality_report)
# ---------------------------------------------------------------------------

SUPPORTED_ACTIONS = {
    "tap", "long_press", "double_tap", "input_text", "enter", "wait",
}
DENY_FINAL_WORDS = {
    "send", "publish", "post", "purchase", "checkout", "pay",
    "delete", "unfollow",
}


def filter_skills(
    skills: list[Any],
    *,
    max_steps: int = 8,
    task_goal: str = "",
) -> tuple[list[Any], dict[str, list[str]]]:
    """Filter out poorly-defined skills. Returns (accepted, report)."""
    report: dict[str, list[str]] = {}
    accepted: list[Any] = []

    for skill in skills:
        issues: list[str] = []
        sid = str(getattr(skill, "skill_id", "") or skill.name or "?")

        if not getattr(skill, "steps", None):
            issues.append("empty_skill")
        step_count = len(skill.steps) if skill.steps else 0
        if step_count > max_steps:
            issues.append(f"too_many_steps:{step_count}")
        if step_count < 2:
            issues.append("single_step_skill")

        # open_app / scroll / back / home
        for i, step in enumerate(skill.steps):
            atype = str(step.action_type)
            if atype == "open_app":
                issues.append(f"contains_open_app:{i}")
            if atype in ("scroll", "swipe", "drag"):
                issues.append(f"contains_scroll:{i}")
            if atype == "back":
                issues.append(f"contains_back:{i}")
            if atype not in SUPPORTED_ACTIONS:
                issues.append(f"unsupported_action:{i}:{atype}")

        # Generic parameter names
        generic = [
            p for p in getattr(skill, "parameters", ())
            if re.fullmatch(r"param\d+", str(p))
        ]
        if generic:
            issues.append(f"generic_parameters:{','.join(map(str, generic))}")

        # Final words in targets
        for i, step in enumerate(skill.steps):
            text = " ".join(str(v or "") for v in (
                getattr(step, "target", ""),
                getattr(step, "valid_state", ""),
            )).lower()
            if any(re.search(rf"\b{re.escape(w)}\b", text) for w in DENY_FINAL_WORDS):
                issues.append(f"risky_final_word:{i}")

        # Task literals leaking
        literals = _task_specific_literals(task_goal)
        for i, step in enumerate(skill.steps):
            text = " ".join(str(v or "") for v in (
                getattr(skill, "description", ""),
                getattr(step, "target", ""),
            )).lower()
            hits = sorted(t for t in literals if t.lower() in text)
            if hits:
                issues.append(f"task_literals:{i}:{','.join(hits[:5])}")

        # verbose valid_state
        verbose = sum(
            1 for s in skill.steps
            if getattr(s, "valid_state", None)
            and str(s.valid_state).strip().lower() not in (
                "no need to verify", "none", "n/a", "", "return true",
            )
        )
        if verbose:
            issues.append(f"verbose_valid_state:{verbose}")

        if issues:
            report[sid] = issues
        else:
            accepted.append(skill)

    return accepted, report


def _task_specific_literals(task_goal: str) -> set[str]:
    generic = {
        "reply", "recent", "email", "message", "meeting", "cancel",
        "available", "shopping", "cart", "weather", "login", "verification",
        "settings", "wallpaper", "conference", "duration", "depart", "time",
        "github", "repo", "repos", "invoice", "file", "files", "search",
        "task", "android",
    }
    tokens = {
        t for t in re.findall(r"[A-Za-z][A-Za-z0-9_-]{4,}", task_goal or "")
        if t.lower() not in generic
    }
    for m in re.finditer(r"['\"]([^'\"]{4,80})['\"]", task_goal or ""):
        phrase = re.sub(r"\s+", " ", m.group(1)).strip()
        if phrase:
            tokens.add(phrase)
    return tokens


# ---------------------------------------------------------------------------
# Skill induction (LLM call)
# ---------------------------------------------------------------------------

async def induce_skills(
    *,
    trajectory_text: str,
    app: str,
    api_key: str,
    base_url: str,
    model: str,
    max_tokens: int = 2048,
    temperature: float = 0.1,
    max_retries: int = 2,
) -> tuple[str, list[Any]]:
    """Call LLM, compile output, retry on errors. Returns (source, skills)."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    prompt_with_app = SKILL_SYSTEM_PROMPT.replace("com.example", app)

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": prompt_with_app},
            {"role": "user", "content": trajectory_text},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    source = clean_skill_code(response.choices[0].message.content or "")

    compiled = compile_flat_skills(source)
    if not compiled.errors:
        return source, list(compiled.skills)

    # Retry with errors
    for attempt in range(1, max_retries + 1):
        retry_prompt = (
            f"{trajectory_text}\n\n"
            f"The previous Python code had compilation errors. Fix them:\n"
            f"{json.dumps(list(compiled.errors), ensure_ascii=False, indent=2)}\n\n"
            "Regenerate the entire skill code as valid Python only."
        )
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt_with_app},
                {"role": "user", "content": retry_prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        source = clean_skill_code(response.choices[0].message.content or "")
        compiled = compile_flat_skills(source)
        if not compiled.errors:
            return source, list(compiled.skills)

    return source, list(compiled.skills)  # Return whatever we have


# ---------------------------------------------------------------------------
# Skill storage
# ---------------------------------------------------------------------------

def append_skills_to_file(skills: list[Any], path: Path) -> int:
    """Append skills as Python source to a skills.py file, skipping duplicates."""
    if not path.exists():
        path.write_text(f"{CODE_HEADER}\n\n", encoding="utf-8")

    existing = path.read_text(encoding="utf-8")
    new_count = 0
    with open(path, "a", encoding="utf-8") as fh:
        for skill in skills:
            sid = str(getattr(skill, "skill_id", "") or skill.name or "")
            if sid and sid in existing:
                continue
            source = export_skills_to_source([skill])
            # Strip CODE_HEADER since it's already in the file
            source = source.replace(f"{CODE_HEADER}\n\n", "").replace(f"{CODE_HEADER}\n", "")
            fh.write(source)
            if not source.endswith("\n"):
                fh.write("\n")
            fh.write("\n")
            new_count += 1
    return new_count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--format-only", type=Path,
                   help="Format a single trace and print, then exit")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--trace-dir", type=Path, help="Single task trace directory")
    src.add_argument("--trace-root", type=Path, help="Root directory with task subdirs")

    p.add_argument("--output", type=Path, default=Path("compact_skills.py"),
                   help="Output skills.py file (default: compact_skills.py)")
    p.add_argument("--model", default=os.getenv("SKILL_INDUCE_MODEL", "deepseek-v4-pro"))
    p.add_argument("--base-url", default=os.getenv("SKILL_INDUCE_BASE_URL", ""))
    p.add_argument("--api-key-env", default="OPENAI_API_KEY")
    p.add_argument("--max-tokens", type=int, default=3072)
    p.add_argument("--temperature", type=float, default=0.1)
    p.add_argument("--task", action="append", dest="tasks",
                   help="Only process specific task(s). Repeatable.")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--dry-run", action="store_true",
                   help="Print formatted trajectories without LLM calls")
    p.add_argument("--max-skills-per-task", type=int, default=3)
    return p.parse_args()


def _guess_app(task_name: str) -> str:
    lowered = task_name.lower()
    if "mattermost" in lowered:
        return "com.mattermost.rnbeta"
    if "mastodon" in lowered:
        return "org.joinmastodon.android.mastodon"
    if "calendar" in lowered or "schedule" in lowered or "conference" in lowered:
        return "org.fossify.calendar"
    if "alarm" in lowered or "clock" in lowered:
        return "com.google.android.deskclock"
    if "chrome" in lowered or "github" in lowered:
        return "com.android.chrome"
    if "settings" in lowered or "airplane" in lowered or "flight" in lowered:
        return "com.android.settings"
    if any(k in lowered for k in ("cart", "mall", "checkout", "item", "taodian")):
        return "com.testmall.app"
    if any(k in lowered for k in ("photo", "gallery", "wallpaper", "selfie")):
        return "gallery.photomanager.picturegalleryapp.imagegallery"
    if any(k in lowered for k in ("file", "download", "count", "sum", "bid")):
        return "com.google.android.documentsui"
    if any(k in lowered for k in ("mail", "email", "gmail", "meeting", "send",
                                    "event", "receipt", "invoice")):
        return "com.gmailclone"
    return "com.android.chrome"


async def main_async(args: argparse.Namespace) -> int:
    if args.format_only:
        text = format_trajectory_for_skill(args.format_only)
        if text is None:
            print("No usable steps found.", file=sys.stderr)
            return 1
        print(text)
        return 0

    if not args.trace_dir and not args.trace_root:
        print("Error: --trace-dir or --trace-root required", file=sys.stderr)
        return 1

    if args.trace_dir:
        task_dirs = [args.trace_dir]
    else:
        root = args.trace_root.expanduser()
        task_dirs = sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith("."))
        if args.tasks:
            task_dirs = [d for d in task_dirs if d.name in set(args.tasks)]

    if args.limit > 0:
        task_dirs = task_dirs[: args.limit]

    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        return 1

    api_key = os.getenv(args.api_key_env, "")
    if not api_key and not args.dry_run:
        print(f"Error: {args.api_key_env} not set", file=sys.stderr)
        return 1

    output_path = args.output.expanduser()
    all_skills: list[Any] = []
    total_processed = 0
    total_skipped_no_trace = 0
    total_skipped_failure = 0
    total_skipped_short = 0

    for task_dir in task_dirs:
        task_name = task_dir.name

        # Only process successful tasks
        outcome, error_msg = get_task_outcome(task_dir)
        if outcome != "success":
            total_skipped_failure += 1
            continue

        trace_paths = _find_gui_task_traces(task_dir)
        if not trace_paths:
            total_skipped_no_trace += 1
            continue

        app = _guess_app(task_name)

        formatted_jobs: list[tuple[Path, str, int]] = []
        for trace_path in trace_paths:
            step_count = _trace_step_count(trace_path)
            if step_count <= 2:
                total_skipped_short += 1
                continue
            text = format_trajectory_for_skill(trace_path)
            if text is None:
                continue
            formatted_jobs.append((trace_path, text, step_count))

        if not formatted_jobs:
            continue

        if args.dry_run:
            print(f"\n{'='*60}")
            print(f"Task: {task_name}  App: {app}")
            for tp, _, sc in formatted_jobs:
                print(f"  Trace: {tp} ({sc} steps)")
            print(f"{'='*60}")
            for _, text, _ in formatted_jobs:
                print(text[:1500])
                if len(text) > 1500:
                    print(f"... ({len(text)} chars total)")
            continue

        task_skills: list[Any] = []
        print(f"[SKL] {task_name} ({app}) ... ", end="", flush=True)
        for tp, trajectory_text, _ in formatted_jobs:
            try:
                source, skills = await induce_skills(
                    trajectory_text=trajectory_text,
                    app=app,
                    api_key=api_key,
                    base_url=args.base_url,
                    model=args.model,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                )
            except Exception as exc:
                print(f"\n  {tp}: LLM error: {exc}")
                continue

            # Apply quality filter
            task_goal = _find_task_goal(_load_jsonl(tp))
            accepted, report = filter_skills(
                skills,
                max_steps=8,
                task_goal=task_goal,
            )
            if report:
                for sid, issues in report.items():
                    print(f"\n  [REJECTED] {sid}: {', '.join(issues)}")

            accepted = accepted[: args.max_skills_per_task]
            task_skills.extend(accepted)

        print(f"{len(task_skills)} skill(s) accepted")
        all_skills.extend(task_skills)
        total_processed += 1

    # Write output
    if all_skills and not args.dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        new_count = append_skills_to_file(all_skills, output_path)
        print(f"\nWrote {new_count} new skill(s) to {output_path}")

    print(f"\nProcessed: {total_processed} task(s)")
    print(f"Skipped: {total_skipped_failure} failure(s), "
          f"{total_skipped_no_trace} no-trace, {total_skipped_short} short")

    return 0


def main() -> None:
    raise SystemExit(asyncio.run(main_async(parse_args())))


if __name__ == "__main__":
    main()
