#!/usr/bin/env python3
"""Generate and optionally execute Android deep-link probes."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote


TASK_PROFILES = {
    "search": {
        "paths": ["search", "search/", "search/result", "search/results", "find"],
        "query_keys": ["keyword", "query", "q", "text"],
        "query_value": "test",
    },
    "detail": {
        "paths": ["detail/123", "item/123", "note/123", "post/123"],
        "query_keys": ["id", "item_id", "note_id"],
        "query_value": "123",
    },
    "profile": {
        "paths": ["profile/test", "user/test", "u/test", "member/test"],
        "query_keys": ["user_id", "uid", "id"],
        "query_value": "test",
    },
    "web": {
        "paths": ["open", "deeplink", "launch"],
        "query_keys": ["url", "target", "redirect"],
        "query_value": quote("https://example.com"),
    },
    "generic": {
        "paths": ["open", "home", ""],
        "query_keys": ["target", "id"],
        "query_value": "test",
    },
}


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _guess_task_profile(task: str) -> str:
    lowered = task.lower()
    checks = [
        ("search", ["search", "find", "query", "keyword", "搜", "检索"]),
        ("detail", ["detail", "note", "post", "item", "详情", "详情页"]),
        ("profile", ["profile", "user", "account", "主页", "个人", "用户"]),
        ("web", ["web", "browser", "url", "link", "网页"]),
    ]
    for name, needles in checks:
        if any(needle in lowered for needle in needles):
            return name
    return "generic"


def _guess_schemes(package: str) -> list[str]:
    parts = [segment for segment in package.split(".") if segment]
    candidates = []
    if parts:
        candidates.append(parts[-1])
        if len(parts) >= 2:
            candidates.append("".join(parts[-2:]))
    normalized = re.sub(r"[^a-z0-9]+", "", package.lower())
    if normalized:
        candidates.append(normalized)
    return _dedupe(candidates)


def _shell_join(parts: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def _run_command(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode, output


def _classify_am_output(output: str) -> tuple[str, str]:
    lowered = output.lower()
    if "unable to resolve intent" in lowered or "error: activity not started" in lowered:
        return "unresolved", "Intent did not resolve to the target package."
    if "status: ok" in lowered and "activity:" in lowered:
        return "launched", "Activity launch succeeded."
    if "warning:" in lowered and "activity not started" in lowered:
        return "partial", "Command reached an activity boundary but did not clearly launch the expected target."
    if "starting: intent" in lowered:
        return "partial", "Intent was accepted but the launch outcome is ambiguous."
    return "unknown", "Need manual inspection of adb output."


def _extract_relevant_lines(output: str) -> list[str]:
    interesting = []
    for line in output.splitlines():
        lowered = line.lower()
        if any(token in lowered for token in ("status:", "activity:", "warning:", "error:", "unable", "intent")):
            interesting.append(line.strip())
    return interesting[:6]


@dataclass
class Probe:
    uri: str
    kind: str
    command: str
    status: str
    evidence: list[str]
    note: str


def _build_candidates(
    package: str,
    task: str,
    mode: str,
    schemes: list[str],
    hosts: list[str],
    paths: list[str],
    query_keys: list[str],
    candidate_uris: list[str],
) -> list[tuple[str, str]]:
    profile_name = _guess_task_profile(task)
    profile = TASK_PROFILES[profile_name]
    merged_paths = _dedupe(paths + profile["paths"])
    merged_query_keys = _dedupe(query_keys + profile["query_keys"])
    query_value = profile["query_value"]

    if mode == "fast":
        merged_paths = merged_paths[:3]
        merged_query_keys = merged_query_keys[:2]

    guesses = _dedupe(schemes + _guess_schemes(package))
    seed_candidates: list[tuple[str, str]] = [(uri, "seed") for uri in candidate_uris]
    custom_candidates: list[tuple[str, str]] = []
    web_candidates: list[tuple[str, str]] = []

    for scheme in guesses:
        for path in merged_paths:
            base_uri = f"{scheme}://{path}" if path else f"{scheme}://"
            custom_candidates.append((base_uri, "custom_scheme"))
            for key in merged_query_keys:
                custom_candidates.append((f"{base_uri}?{key}={query_value}", "custom_scheme"))

    for host in hosts:
        base_host = host if host.startswith("http") else f"https://{host}"
        for path in merged_paths:
            path_part = f"/{path}" if path else ""
            base_uri = f"{base_host}{path_part}"
            web_candidates.append((base_uri, "web_link"))
            for key in merged_query_keys:
                web_candidates.append((f"{base_uri}?{key}={query_value}", "web_link"))

    limits = {"fast": {"custom": 8, "web": 4, "total": 12}, "investigate": {"custom": 18, "web": 12, "total": 30}}
    current = limits[mode]
    combined = seed_candidates + custom_candidates[: current["custom"]] + web_candidates[: current["web"]]
    return _dedupe_probe_candidates(combined, current["total"])


def _dedupe_probe_candidates(candidates: list[tuple[str, str]], total_limit: int) -> list[tuple[str, str]]:
    seen: set[str] = set()
    deduped: list[tuple[str, str]] = []
    for uri, kind in candidates:
        if uri in seen:
            continue
        seen.add(uri)
        deduped.append((uri, kind))
        if len(deduped) >= total_limit:
            break
    return deduped


def _adb_prefix(serial: str | None) -> list[str]:
    command = ["adb"]
    if serial:
        command.extend(["-s", serial])
    return command


def _probe_uri(package: str, serial: str | None, uri: str, kind: str, no_exec: bool) -> Probe:
    command_parts = _adb_prefix(serial) + [
        "shell",
        "am",
        "start",
        "-W",
        "-a",
        "android.intent.action.VIEW",
        "-d",
        uri,
        package,
    ]
    command = _shell_join(command_parts)
    if no_exec:
        return Probe(
            uri=uri,
            kind=kind,
            command=command,
            status="planned",
            evidence=[],
            note="Dry run only; command not executed.",
        )

    returncode, output = _run_command(command_parts)
    status, note = _classify_am_output(output)
    if returncode != 0 and status == "unknown":
        status = "error"
    return Probe(
        uri=uri,
        kind=kind,
        command=command,
        status=status,
        evidence=_extract_relevant_lines(output),
        note=note,
    )


def _inspect_package(package: str, serial: str | None, no_exec: bool) -> dict[str, object]:
    package_cmd = _adb_prefix(serial) + ["shell", "dumpsys", "package", package]
    domain_cmd = _adb_prefix(serial) + ["shell", "dumpsys", "package", "domain-preferred-apps"]
    result: dict[str, object] = {
        "package_dump_command": _shell_join(package_cmd),
        "domain_check_command": _shell_join(domain_cmd),
    }
    if no_exec:
        result["note"] = "Dry run only; dumpsys commands not executed."
        return result

    package_rc, package_output = _run_command(package_cmd)
    domain_rc, domain_output = _run_command(domain_cmd)
    result["package_dump_status"] = "ok" if package_rc == 0 else "error"
    result["domain_check_status"] = "ok" if domain_rc == 0 else "error"
    result["package_hints"] = _extract_dump_hints(package_output, package)
    result["domain_hints"] = _extract_dump_hints(domain_output, package)
    return result


def _extract_dump_hints(output: str, package: str) -> list[str]:
    hints = []
    lowered_package = package.lower()
    for line in output.splitlines():
        lowered = line.lower()
        if any(token in lowered for token in ("view", "browsable", "scheme", "host", "path", lowered_package)):
            hints.append(line.strip())
    return hints[:12]


def _build_summary(probes: list[Probe], mode: str) -> dict[str, object]:
    best = [probe.uri for probe in probes if probe.status == "launched"][:5]
    partial = [probe.uri for probe in probes if probe.status == "partial"][:5]
    invalid = [probe.uri for probe in probes if probe.status in {"unresolved", "error"}][:5]
    planned = [probe.uri for probe in probes if probe.status == "planned"][:5]

    next_tries: list[str]
    if best:
        next_tries = ["Reuse the best launched URI and refine only one parameter or path segment at a time."]
    elif partial:
        next_tries = [
            "Keep the same scheme/host and vary one path level or parameter name.",
            "Inspect dumpsys output for BROWSABLE/path hints before widening the search.",
        ]
    elif planned:
        next_tries = [
            "Execute the top planned candidates on a connected device.",
            "If https links fall back to browser, inspect domain-preferred-apps before discarding the host.",
        ]
    else:
        next_tries = [
            "Add known schemes, hosts, or a direct candidate URI from documentation or trace context.",
            "Switch to investigate mode for a wider candidate set.",
        ]

    if mode == "fast" and not best:
        next_tries.append("Escalate to investigate mode if the fast candidate set does not reach the target state.")

    return {
        "best_candidates": best,
        "partial_matches": partial,
        "invalid_candidates": invalid,
        "next_tries": next_tries[:5],
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, help="Target Android package name.")
    parser.add_argument("--task", default="open target page", help="Short task description.")
    parser.add_argument("--serial", help="Optional adb device serial.")
    parser.add_argument("--mode", choices=["fast", "investigate"], default="fast")
    parser.add_argument("--scheme", action="append", default=[], help="Known custom scheme. Repeat for more.")
    parser.add_argument("--host", action="append", default=[], help="Known host. Repeat for more.")
    parser.add_argument("--path", action="append", default=[], help="Known candidate path. Repeat for more.")
    parser.add_argument("--query-key", action="append", default=[], help="Known query key. Repeat for more.")
    parser.add_argument("--candidate-uri", action="append", default=[], help="Direct URI seed. Repeat for more.")
    parser.add_argument("--no-exec", action="store_true", help="Only plan probes; do not run adb commands.")
    parser.add_argument("--format", choices=["json", "text"], default="json")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    candidates = _build_candidates(
        package=args.package,
        task=args.task,
        mode=args.mode,
        schemes=args.scheme,
        hosts=args.host,
        paths=args.path,
        query_keys=args.query_key,
        candidate_uris=args.candidate_uri,
    )
    probes = [
        _probe_uri(args.package, args.serial, uri=uri, kind=kind, no_exec=args.no_exec)
        for uri, kind in candidates
    ]
    system_checks = _inspect_package(args.package, args.serial, no_exec=args.no_exec)
    payload = {
        "inputs": {
            "package": args.package,
            "task": args.task,
            "serial": args.serial,
            "mode": args.mode,
            "no_exec": args.no_exec,
            "schemes": _dedupe(args.scheme),
            "hosts": _dedupe(args.host),
            "paths": _dedupe(args.path),
            "query_keys": _dedupe(args.query_key),
            "candidate_uris": _dedupe(args.candidate_uri),
        },
        "probes": [
            {
                "uri": probe.uri,
                "kind": probe.kind,
                "command": probe.command,
                "status": probe.status,
                "evidence": probe.evidence,
                "note": probe.note,
            }
            for probe in probes
        ],
        "system_checks": system_checks,
        "summary": _build_summary(probes, args.mode),
    }

    if args.format == "json":
        json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    print(f"Package: {args.package}")
    print(f"Task: {args.task}")
    print(f"Mode: {args.mode}")
    print()
    for probe in probes:
        print(f"[{probe.status}] {probe.uri}")
        print(f"  command: {probe.command}")
        if probe.evidence:
            print(f"  evidence: {' | '.join(probe.evidence)}")
        print(f"  note: {probe.note}")
    print()
    print("Next tries:")
    for item in payload["summary"]["next_tries"]:
        print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
