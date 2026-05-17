"""
opengui.skills.code_graph_repair
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Small repair-ticket helpers for code-backed skill graph failures.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opengui.skills.graph import GraphEdge


def build_repair_ticket(
    *,
    edge: GraphEdge,
    failure_reason: str,
    expected_contract: dict[str, Any] | None,
    observation: Any,
    source_root: Path | str | None = None,
) -> dict[str, Any]:
    """Build a compact coding-agent repair ticket for a graph failure."""
    observation_summary = _compact_observation(observation)
    return {
        "type": "graph_repair_ticket",
        "failure_reason": failure_reason,
        "runtime_error": failure_reason,
        "edge_id": edge.edge_id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "source_ref": edge.source_ref,
        "source_snippet": _source_snippet(edge.source_ref, source_root=source_root),
        "expected_contract": expected_contract or {},
        "state_contract_mismatch": {
            "expected_contract": expected_contract or {},
            "observation_summary": observation_summary,
        },
        "observation_summary": observation_summary,
        "trace_excerpt": {
            "edge_id": edge.edge_id,
            "source_node_id": edge.source_node_id,
            "target_node_id": edge.target_node_id,
            "action_type": edge.action_type,
            "failure_reason": failure_reason,
            "observation_summary": observation_summary,
        },
        "suggested_actions": ["patch_contract", "patch_transition", "spawn_version"],
    }


def _compact_observation(observation: Any) -> dict[str, Any]:
    extra = getattr(observation, "extra", None)
    if not isinstance(extra, dict):
        extra = {}
    ui_tree = extra.get("ui_tree")
    ui_tree_node_count = extra.get("ui_tree_node_count")
    if ui_tree_node_count is None and isinstance(ui_tree, list):
        ui_tree_node_count = len(ui_tree)
    return {
        "platform": getattr(observation, "platform", None),
        "foreground_app": getattr(observation, "foreground_app", None),
        "ui_tree_node_count": ui_tree_node_count,
        "visible_text": _string_list(extra.get("visible_text"), limit=20),
    }


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        if len(result) >= limit:
            break
    return result


def _source_snippet(
    source_ref: dict[str, Any] | None,
    *,
    source_root: Path | str | None,
) -> dict[str, Any]:
    ref = dict(source_ref or {})
    path_value = ref.get("path")
    line = _int_or_none(ref.get("line"))
    snippet = ""
    if isinstance(path_value, str) and source_root is not None:
        path = Path(path_value)
        if not path.is_absolute():
            path = Path(source_root) / path
        snippet = _read_snippet(path, line=line)
    return {
        "path": path_value,
        "symbol": ref.get("symbol"),
        "line": line,
        "kind": ref.get("kind"),
        "snippet": snippet,
    }


def _read_snippet(path: Path, *, line: int | None, radius: int = 4) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    if not lines:
        return ""
    if line is None or line < 1:
        start = 0
        end = min(len(lines), radius * 2 + 1)
    else:
        start = max(0, line - radius - 1)
        end = min(len(lines), line + radius)
    return "\n".join(lines[start:end])


def _int_or_none(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
