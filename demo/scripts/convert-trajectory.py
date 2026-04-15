#!/usr/bin/env python3
"""Convert opengui_runs JSONL trajectories into demo-friendly JSON format.

Usage:
    python convert-trajectory.py [--runs-dir ../opengui_runs] [--out-dir ../data]

Reads trace.jsonl files, normalises both old (string action) and new (dict action)
formats, copies screenshots, and synthesises agent-log.json for each scenario.
Also generates manifest.json.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

# Mapping of run directories to demo scenarios
SCENARIOS = [
    {
        "run": "20260319_032813_363558/open_settings_1773890893364_0",
        "platform": "android",
        "id": "open-settings",
        "title": "Open Settings",
        "description": "Find and open the Settings app on an Android device",
    },
    {
        "run": "20260319_035508_251534/open_chrome_app_1773892508252_0",
        "platform": "android",
        "id": "open-chrome",
        "title": "Open Chrome",
        "description": "Locate and launch Chrome browser on Android",
    },
    {
        "run": "20260324_062500_867802/Open_vpn_in_clash_meta_1774333500868_0",
        "platform": "android",
        "id": "open-vpn-clash",
        "title": "Open VPN in Clash Meta",
        "description": "Open the Clash Meta app and start VPN connection",
    },
    {
        "run": "20260412_045455_536820/iOS_1775969697075_0",
        "platform": "ios",
        "id": "check-ios-version",
        "title": "Check iOS Version",
        "description": "Open Settings and navigate to check the iOS version",
    },
    {
        "run": "20260321_092149_774129/open_system_settings_1774084909774_0",
        "platform": "macos",
        "id": "open-system-settings",
        "title": "Open System Settings",
        "description": "Open macOS System Settings via Spotlight or Apple menu",
    },
]


def parse_old_action(action_str: str) -> dict | None:
    """Parse old-format string actions like 'tap at (388.0/999, 491.0/999)'."""
    if not isinstance(action_str, str):
        return action_str  # already a dict

    # tap at (x/999, y/999) or tap at (x, y)
    m = re.match(
        r"tap at \((\d+\.?\d*)/999,\s*(\d+\.?\d*)/999\)", action_str
    )
    if m:
        return {
            "action_type": "tap",
            "x": float(m.group(1)),
            "y": float(m.group(2)),
            "relative": True,
        }

    m = re.match(r"tap at \((\d+\.?\d*),\s*(\d+\.?\d*)\)", action_str)
    if m:
        return {
            "action_type": "tap",
            "x": float(m.group(1)),
            "y": float(m.group(2)),
            "relative": False,
        }

    if "task done" in action_str.lower() and "success" in action_str.lower():
        return {"action_type": "done", "status": "success"}

    if "task done" in action_str.lower() or "done" in action_str.lower():
        return {"action_type": "done", "status": "failure"}

    return {"action_type": "unknown", "raw": action_str}


def extract_model_text(step: dict) -> str | None:
    """Extract the human-readable model output from a step event."""
    mo = step.get("model_output")
    if isinstance(mo, dict):
        return mo.get("action_text") or mo.get("action_summary") or mo.get("raw_content")
    if isinstance(mo, str):
        return mo
    return step.get("action_summary") or step.get("action_debug")


def extract_action_summary(step: dict) -> str:
    """Get a short action summary string."""
    if step.get("action_summary"):
        return step["action_summary"]
    mo = step.get("model_output")
    if isinstance(mo, dict):
        return mo.get("action_summary") or mo.get("action_text") or ""
    action = step.get("action")
    if isinstance(action, str):
        return action
    if isinstance(action, dict):
        at = action.get("action_type", "")
        if at == "tap":
            return f"tap at ({action.get('x')}, {action.get('y')})"
        if at == "swipe":
            return f"swipe from ({action.get('x')}, {action.get('y')}) to ({action.get('x2')}, {action.get('y2')})"
        if at == "done":
            return f"done: {action.get('status', '')}"
        return at
    return ""


def convert_scenario(runs_dir: Path, out_dir: Path, scenario: dict) -> dict | None:
    """Convert one scenario. Returns manifest entry or None on failure."""
    run_path = runs_dir / scenario["run"]
    trace_path = run_path / "trace.jsonl"
    screenshots_dir = run_path / "screenshots"

    if not trace_path.exists():
        print(f"  SKIP {scenario['id']}: trace.jsonl not found at {trace_path}")
        return None

    # Read all events
    events = []
    for line in trace_path.read_text().splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))

    # Extract metadata from first attempt_start or first step
    task = scenario.get("title", "unknown")
    platform = scenario["platform"]
    screen_width = 0
    screen_height = 0

    for ev in events:
        if ev.get("event") == "attempt_start":
            task = ev.get("task", task)
        # Get screen dimensions from first step with model_output or observation
        if ev.get("event") == "step":
            mo = ev.get("model_output")
            if isinstance(mo, dict):
                prompt = ev.get("prompt", {})
                obs = prompt.get("current_observation", {})
                if obs.get("screen_width"):
                    screen_width = obs["screen_width"]
                    screen_height = obs["screen_height"]
                    break
            obs = ev.get("observation")
            if isinstance(obs, dict) and obs.get("screen_width"):
                screen_width = obs["screen_width"]
                screen_height = obs["screen_height"]
                break
            # Try from prompt history
            prompt = ev.get("prompt", {})
            hist = prompt.get("history", [])
            if hist:
                obs = hist[0].get("observation", {})
                if obs.get("screen_width"):
                    screen_width = obs["screen_width"]
                    screen_height = obs["screen_height"]
                    break
            co = prompt.get("current_observation", {})
            if co.get("screen_width"):
                screen_width = co["screen_width"]
                screen_height = co["screen_height"]
                break

    # Build steps
    steps = []
    step_events = [e for e in events if e.get("event") == "step"]

    # Step 0: initial screenshot (before any action)
    if screenshots_dir.exists() and (screenshots_dir / "step_000.png").exists():
        steps.append({
            "index": 0,
            "screenshot": "screenshots/step_000.png",
            "action": None,
            "action_summary": None,
            "model_output": None,
        })

    for se in step_events:
        idx = se.get("step_index", len(steps))
        action = parse_old_action(se.get("action"))
        # For structured action in new format
        if isinstance(se.get("action"), dict):
            action = se["action"]

        screenshot = None
        if se.get("screenshot_path"):
            # Normalize to relative path
            sp = Path(se["screenshot_path"])
            screenshot = f"screenshots/{sp.name}"

        steps.append({
            "index": idx,
            "screenshot": screenshot,
            "action": action,
            "action_summary": extract_action_summary(se),
            "model_output": extract_model_text(se),
        })

    # Extract result
    result_events = [e for e in events if e.get("event") == "attempt_result"]
    success = False
    duration_s = 0
    total_steps = len(step_events)
    summary = ""

    if result_events:
        re_ = result_events[-1]
        success = re_.get("success", False)
        total_steps = re_.get("steps_taken", total_steps)
        summary = re_.get("summary", "")
        # Compute duration from timestamps
        if step_events:
            first_ts = events[0].get("timestamp", 0)
            last_ts = re_.get("timestamp", first_ts)
            duration_s = round(last_ts - first_ts, 2)
    else:
        # Old format: infer success from last step's done field and action
        if step_events:
            last = step_events[-1]
            if last.get("done"):
                action = last.get("action")
                if isinstance(action, str) and "success" in action.lower():
                    success = True
                elif isinstance(action, dict) and action.get("status") == "success":
                    success = True
            first_ts = step_events[0].get("timestamp", 0)
            last_ts = step_events[-1].get("timestamp", first_ts)
            duration_s = round(last_ts - first_ts, 2)

    trajectory = {
        "metadata": {
            "task": task,
            "platform": platform,
            "screen_width": screen_width,
            "screen_height": screen_height,
        },
        "steps": steps,
        "result": {
            "success": success,
            "total_steps": total_steps,
            "duration_s": duration_s,
            "summary": summary,
        },
    }

    # Write output
    scenario_dir = out_dir / scenario["platform"] / scenario["id"]
    scenario_dir.mkdir(parents=True, exist_ok=True)

    (scenario_dir / "trajectory.json").write_text(
        json.dumps(trajectory, indent=2, ensure_ascii=False)
    )

    # Copy screenshots
    out_screenshots = scenario_dir / "screenshots"
    out_screenshots.mkdir(exist_ok=True)
    if screenshots_dir.exists():
        for png in sorted(screenshots_dir.glob("step_*.png")):
            shutil.copy2(png, out_screenshots / png.name)

    # Synthesise agent-log.json
    agent_log = {
        "entries": [
            {
                "type": "inbound",
                "channel": "user",
                "content": task,
            },
            {
                "type": "tool_call",
                "tool": "gui_task",
                "arguments": {"task": task, "backend": platform},
                "linkedSteps": [0, total_steps - 1] if total_steps > 0 else [0, 0],
            },
            {
                "type": "tool_result",
                "tool": "gui_task",
                "result": {
                    "success": success,
                    "steps_taken": total_steps,
                    "summary": summary,
                },
            },
            {
                "type": "outbound",
                "content": summary if summary else (
                    f"Task completed successfully in {total_steps} steps."
                    if success
                    else "Task failed."
                ),
            },
        ]
    }
    (scenario_dir / "agent-log.json").write_text(
        json.dumps(agent_log, indent=2, ensure_ascii=False)
    )

    # Return manifest entry
    return {
        "id": scenario["id"],
        "title": scenario["title"],
        "description": scenario["description"],
        "stepCount": total_steps,
        "success": success,
        "duration_s": duration_s,
    }


def main():
    parser = argparse.ArgumentParser(description="Convert opengui_runs to demo data")
    parser.add_argument("--runs-dir", type=Path, default=Path(__file__).resolve().parent.parent.parent / "opengui_runs")
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).resolve().parent.parent / "data")
    args = parser.parse_args()

    print(f"Runs dir: {args.runs_dir}")
    print(f"Output dir: {args.out_dir}")

    # Group scenarios by platform
    platforms_map: dict[str, list] = {}
    for sc in SCENARIOS:
        platforms_map.setdefault(sc["platform"], [])

    platform_labels = {
        "android": ("Android", "phone"),
        "ios": ("iOS", "tablet"),
        "macos": ("macOS", "desktop"),
        "windows": ("Windows", "desktop"),
        "linux": ("Linux", "desktop"),
    }

    for sc in SCENARIOS:
        print(f"Converting {sc['platform']}/{sc['id']}...")
        entry = convert_scenario(args.runs_dir, args.out_dir, sc)
        if entry:
            platforms_map[sc["platform"]].append(entry)
            print(f"  OK: {entry['stepCount']} steps, success={entry['success']}")

    # Build manifest
    manifest = {"platforms": []}
    for pid, scenarios in platforms_map.items():
        if not scenarios:
            continue
        label, device_type = platform_labels.get(pid, (pid.title(), "desktop"))
        manifest["platforms"].append({
            "id": pid,
            "label": label,
            "deviceType": device_type,
            "scenarios": scenarios,
        })

    (args.out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False)
    )
    print(f"\nManifest written with {len(manifest['platforms'])} platforms")


if __name__ == "__main__":
    main()
