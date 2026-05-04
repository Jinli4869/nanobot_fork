"""
opengui.skills.graph
~~~~~~~~~~~~~~~~~~~~
App-scoped skill graph primitives.

The graph is intentionally small and deterministic:
- nodes are UI states identified by canonical state contracts;
- edges are GUI actions with machine-checkable preconditions;
- goal resolution uses node-description embeddings only, never embeddings for
  node identity;
- flat skills remain a compatibility export/import path.
"""

from __future__ import annotations

import heapq
import json
import logging
import math
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

from opengui.skills.data import Skill, SkillStep
from opengui.skills.normalization import normalize_app_identifier
from opengui.skills.state_contract import (
    normalize_state_contract,
    score_state_contract,
    state_contract_fingerprint,
    state_contract_overlap,
)
from opengui.skills.static_selector_filter import (
    filter_static_controls,
    filter_static_resource_ids,
    filter_static_texts,
    selector_is_static,
)

logger = logging.getLogger(__name__)

GRAPH_FILENAME = "skill_graph.json"
GRAPH_EMBEDDINGS_FILENAME = "skill_graph_embeddings.npy"
REFRESH_QUEUE_FILENAME = "skill_graph_refresh_queue.jsonl"
TRANSITION_EVIDENCE_FILENAME = "skill_graph_transition_evidence.jsonl"
GRAPH_VERSION = 1

NODE_STATUS_ACTIVE = "active"
NODE_STATUS_DEPRECATED = "deprecated"
NODE_STATUS_ARCHIVED = "archived"
EDGE_STATUS_ACTIVE = "active"
EDGE_STATUS_DISABLED = "disabled"
NODE_KIND_STATE = "state"
NODE_KIND_INTERRUPT = "interrupt"
NODE_KIND_AUXILIARY = "auxiliary"
REFRESH_ALLOWED_OUTPUTS = ("patch_contract", "spawn_version", "add_edge")

_GOAL_CONFIDENCE_THRESHOLD = 0.45
_GOAL_MARGIN_THRESHOLD = 0.03
_STATE_IDENTIFICATION_THRESHOLD = 0.72
_STATE_MARGIN_THRESHOLD = 0.05
_VERSION_OVERLAP_THRESHOLD = 0.58
_EDGE_HARD_SCORE_THRESHOLD = 0.08


def infer_app_hint_from_task(
    task: str,
    *,
    platform: str,
    candidate_apps: list[str] | tuple[str, ...] | set[str],
) -> str | None:
    """Infer a graph app bucket from task text using known app aliases."""
    platform_norm = (platform or "unknown").strip().lower()
    apps = {
        normalize_app_identifier(platform_norm, app)
        for app in candidate_apps
        if isinstance(app, str) and app.strip()
    }
    apps.discard("unknown")
    if not apps:
        return None

    text = " ".join((task or "").strip().split())
    if not text:
        return None
    lowered = text.lower()
    for app in sorted(apps, key=lambda value: (-len(value), value)):
        if app and app in lowered:
            return app

    compact = text.replace(" ", "")
    max_span = min(18, len(compact))
    best: tuple[int, str] | None = None
    for start in range(len(compact)):
        for end in range(start + 2, min(len(compact), start + max_span) + 1):
            fragment = compact[start:end].strip(" ，。,.!！?？:：;；\"'“”‘’()（）[]【】")
            if len(fragment) < 2:
                continue
            normalized = normalize_app_identifier(platform_norm, fragment)
            if normalized not in apps:
                continue
            span = end - start
            if best is None or span > best[0]:
                best = (span, normalized)
    return best[1] if best is not None else None


@dataclass
class NodeStats:
    reach_count: int = 0
    contract_match_count: int = 0
    contract_miss_count: int = 0
    last_seen_at: float | None = None
    last_verified_at: float | None = None

    @property
    def contract_match_rate(self) -> float:
        total = self.contract_match_count + self.contract_miss_count
        if total <= 0:
            return 0.5
        return self.contract_match_count / total

    def to_dict(self) -> dict[str, Any]:
        return {
            "reach_count": int(self.reach_count),
            "contract_match_count": int(self.contract_match_count),
            "contract_miss_count": int(self.contract_miss_count),
            "last_seen_at": self.last_seen_at,
            "last_verified_at": self.last_verified_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "NodeStats":
        if not isinstance(data, dict):
            return cls()
        return cls(
            reach_count=int(data.get("reach_count") or 0),
            contract_match_count=int(data.get("contract_match_count") or 0),
            contract_miss_count=int(data.get("contract_miss_count") or 0),
            last_seen_at=_float_or_none(data.get("last_seen_at")),
            last_verified_at=_float_or_none(data.get("last_verified_at")),
        )


@dataclass
class EdgeStats:
    attempt_count: int = 0
    success_count: int = 0
    last_attempt_at: float | None = None
    last_success_at: float | None = None
    avg_latency_ms: float | None = None
    failure_reason_counts: dict[str, int] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        return (self.success_count + 1) / (self.attempt_count + 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_count": int(self.attempt_count),
            "success_count": int(self.success_count),
            "last_attempt_at": self.last_attempt_at,
            "last_success_at": self.last_success_at,
            "avg_latency_ms": self.avg_latency_ms,
            "failure_reason_counts": dict(self.failure_reason_counts),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "EdgeStats":
        if not isinstance(data, dict):
            return cls()
        reasons = data.get("failure_reason_counts")
        if not isinstance(reasons, dict):
            reasons = {}
        return cls(
            attempt_count=int(data.get("attempt_count") or 0),
            success_count=int(data.get("success_count") or 0),
            last_attempt_at=_float_or_none(data.get("last_attempt_at")),
            last_success_at=_float_or_none(data.get("last_success_at")),
            avg_latency_ms=_float_or_none(data.get("avg_latency_ms")),
            failure_reason_counts={str(k): int(v) for k, v in reasons.items()},
        )


@dataclass
class GraphNode:
    node_id: str
    app: str
    platform: str
    description: str
    state_contract: dict[str, Any] | None = None
    version: int = 1
    status: str = NODE_STATUS_ACTIVE
    superseded_by: str | None = None
    stats: NodeStats = field(default_factory=NodeStats)
    kind: str = NODE_KIND_STATE
    skill_ids: tuple[str, ...] = ()
    fingerprint: str = ""
    dismiss_action: dict[str, Any] | None = None
    resume_policy: str | None = None
    retrieval_profile: dict[str, Any] | None = None

    def normalized(self) -> "GraphNode":
        platform = (self.platform or "unknown").strip().lower()
        app = normalize_app_identifier(platform, self.app)
        contract = normalize_state_contract(self.state_contract)
        fingerprint = self.fingerprint or state_contract_fingerprint(contract)
        if not fingerprint:
            fingerprint = _stable_id("node", platform, app, self.kind, self.description)
        node_id = self.node_id or _stable_id("node", platform, app, fingerprint, self.version)
        return GraphNode(
            node_id=node_id,
            app=app,
            platform=platform,
            description=self.description,
            state_contract=contract,
            version=int(self.version or 1),
            status=self.status or NODE_STATUS_ACTIVE,
            superseded_by=self.superseded_by,
            stats=self.stats,
            kind=self.kind or NODE_KIND_STATE,
            skill_ids=tuple(_dedupe_strings(self.skill_ids)),
            fingerprint=fingerprint,
            dismiss_action=self.dismiss_action,
            resume_policy=self.resume_policy,
            retrieval_profile=_normalize_retrieval_profile(self.retrieval_profile),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "app": self.app,
            "platform": self.platform,
            "description": self.description,
            "state_contract": self.state_contract,
            "version": self.version,
            "status": self.status,
            "superseded_by": self.superseded_by,
            "stats": self.stats.to_dict(),
            "kind": self.kind,
            "skill_ids": list(self.skill_ids),
            "fingerprint": self.fingerprint,
            "dismiss_action": self.dismiss_action,
            "resume_policy": self.resume_policy,
            "retrieval_profile": self.retrieval_profile,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphNode":
        return cls(
            node_id=str(data.get("node_id") or ""),
            app=str(data.get("app") or "unknown"),
            platform=str(data.get("platform") or "unknown"),
            description=str(data.get("description") or ""),
            state_contract=normalize_state_contract(data.get("state_contract")),
            version=int(data.get("version") or 1),
            status=str(data.get("status") or NODE_STATUS_ACTIVE),
            superseded_by=data.get("superseded_by"),
            stats=NodeStats.from_dict(data.get("stats")),
            kind=str(data.get("kind") or NODE_KIND_STATE),
            skill_ids=tuple(str(sid) for sid in data.get("skill_ids", []) if sid),
            fingerprint=str(data.get("fingerprint") or ""),
            dismiss_action=data.get("dismiss_action") if isinstance(data.get("dismiss_action"), dict) else None,
            resume_policy=data.get("resume_policy"),
            retrieval_profile=data.get("retrieval_profile") if isinstance(data.get("retrieval_profile"), dict) else None,
        ).normalized()


@dataclass
class GraphEdge:
    edge_id: str
    app: str
    platform: str
    source_node_id: str
    target_node_id: str
    action_type: str
    target: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    precondition: dict[str, Any] | None = None
    status: str = EDGE_STATUS_ACTIVE
    stats: EdgeStats = field(default_factory=EdgeStats)
    skill_id: str | None = None
    kind: str = "action"

    def normalized(self) -> "GraphEdge":
        platform = (self.platform or "unknown").strip().lower()
        app = normalize_app_identifier(platform, self.app)
        precondition = normalize_state_contract(self.precondition)
        edge_id = self.edge_id or _stable_id(
            "edge",
            platform,
            app,
            self.source_node_id,
            self.target_node_id,
            self.action_type,
            self.target,
            self.skill_id or "",
        )
        return GraphEdge(
            edge_id=edge_id,
            app=app,
            platform=platform,
            source_node_id=self.source_node_id,
            target_node_id=self.target_node_id,
            action_type=(self.action_type or "").strip().lower(),
            target=self.target,
            parameters=dict(self.parameters or {}),
            precondition=precondition,
            status=self.status or EDGE_STATUS_ACTIVE,
            stats=self.stats,
            skill_id=self.skill_id,
            kind=self.kind or "action",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "app": self.app,
            "platform": self.platform,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "action_type": self.action_type,
            "target": self.target,
            "parameters": self.parameters,
            "precondition": self.precondition,
            "status": self.status,
            "stats": self.stats.to_dict(),
            "skill_id": self.skill_id,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphEdge":
        return cls(
            edge_id=str(data.get("edge_id") or ""),
            app=str(data.get("app") or "unknown"),
            platform=str(data.get("platform") or "unknown"),
            source_node_id=str(data.get("source_node_id") or ""),
            target_node_id=str(data.get("target_node_id") or ""),
            action_type=str(data.get("action_type") or ""),
            target=str(data.get("target") or ""),
            parameters=data.get("parameters") if isinstance(data.get("parameters"), dict) else {},
            precondition=normalize_state_contract(data.get("precondition")),
            status=str(data.get("status") or EDGE_STATUS_ACTIVE),
            stats=EdgeStats.from_dict(data.get("stats")),
            skill_id=data.get("skill_id"),
            kind=str(data.get("kind") or "action"),
        ).normalized()


@dataclass(frozen=True)
class SelectorSignature:
    resource_ids: frozenset[str] = frozenset()
    content_descs: frozenset[str] = frozenset()
    texts: frozenset[str] = frozenset()


@dataclass
class GraphRuntimeIndex:
    stable_by_app: dict[tuple[str, str], tuple[str, ...]] = field(default_factory=dict)
    stable_by_activity: dict[tuple[str, str, str], tuple[str, ...]] = field(default_factory=dict)
    retrieval_by_app: dict[tuple[str, str], tuple[str, ...]] = field(default_factory=dict)
    outgoing_by_node: dict[str, tuple[str, ...]] = field(default_factory=dict)
    selector_signatures: dict[str, SelectorSignature] = field(default_factory=dict)
    dirty_apps: set[tuple[str, str]] = field(default_factory=set)
    stable_anchor_scan_count: int = 0
    retrieval_profile_scan_count: int = 0


@dataclass(frozen=True)
class GraphCandidate:
    node: GraphNode
    score: float
    reason: str = ""


@dataclass(frozen=True)
class GraphCanonicalityReport:
    platform: str
    app: str
    active_state_nodes: int
    anchored_state_nodes: int
    auxiliary_nodes: int
    deprecated_nodes: int
    self_loop_edges: int
    unanchored_state_nodes: int
    blocking_reasons: tuple[str, ...] = ()
    ready_for_graph_only: bool = False


@dataclass(frozen=True)
class GoalNodeResolution:
    status: str
    goal_node: GraphNode | None = None
    candidates: tuple[GraphCandidate, ...] = ()
    confidence: float = 0.0
    reason: str | None = None


@dataclass(frozen=True)
class StateIdentificationResult:
    status: str
    current_node: GraphNode | None = None
    candidates: tuple[GraphCandidate, ...] = ()
    confidence: float = 0.0
    reason: str | None = None


@dataclass(frozen=True)
class PathCompilation:
    status: str
    edges: tuple[GraphEdge, ...] = ()
    nodes: tuple[GraphNode, ...] = ()
    total_cost: float = 0.0
    reason: str | None = None


@dataclass
class GraphSessionCursor:
    current_node_id: str | None = None
    platform: str | None = None
    app: str | None = None
    fingerprint: str | None = None
    updated_at: float | None = None
    clear_reason: str | None = None

    def set(self, node: GraphNode) -> None:
        self.current_node_id = node.node_id
        self.platform = node.platform
        self.app = node.app
        self.fingerprint = node.fingerprint
        self.updated_at = time.time()
        self.clear_reason = None

    def clear(self, reason: str) -> None:
        self.current_node_id = None
        self.platform = None
        self.app = None
        self.fingerprint = None
        self.updated_at = None
        self.clear_reason = reason

    def compatible_with(self, *, platform: str | None, app: str | None) -> bool:
        if not self.current_node_id:
            return False
        platform_norm = (platform or "").strip().lower()
        if self.platform and platform_norm and platform_norm != self.platform:
            return False
        if self.app and not app:
            return False
        if app and self.app:
            normalized_app = normalize_app_identifier(self.platform or platform_norm, app)
            if normalized_app != self.app:
                return False
        return True


class SkillGraphStore:
    """Persistent app-scoped graph store for GUI skills."""

    def __init__(
        self,
        *,
        store_dir: Path,
        embedding_provider: Any | None = None,
        embedding_signature: str | None = None,
        version_overlap_threshold: float = _VERSION_OVERLAP_THRESHOLD,
    ) -> None:
        self.store_dir = Path(store_dir)
        self.embedding_provider = embedding_provider
        self.embedding_signature = embedding_signature
        self.version_overlap_threshold = float(version_overlap_threshold)
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}
        self._embeddings: dict[str, np.ndarray] = {}
        self._embeddings_signature: str | None = None
        self._runtime_index = GraphRuntimeIndex()
        self.load_all()

    @property
    def count_nodes(self) -> int:
        return len(self._nodes)

    @property
    def count_edges(self) -> int:
        return len(self._edges)

    @property
    def graph_path(self) -> Path:
        return self.store_dir / GRAPH_FILENAME

    @property
    def embeddings_path(self) -> Path:
        return self.store_dir / GRAPH_EMBEDDINGS_FILENAME

    def load_all(self) -> None:
        self._nodes.clear()
        self._edges.clear()
        self._embeddings.clear()
        self._embeddings_signature = None
        self._runtime_index = GraphRuntimeIndex()
        loaded_graph = self.graph_path.is_file()
        if self.graph_path.is_file():
            try:
                payload = json.loads(self.graph_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Skipping invalid skill graph %s: %s", self.graph_path, exc)
                payload = {}
            for item in payload.get("nodes", []) if isinstance(payload, dict) else []:
                if isinstance(item, dict):
                    node = GraphNode.from_dict(item)
                    self._nodes[node.node_id] = node
            for item in payload.get("edges", []) if isinstance(payload, dict) else []:
                if isinstance(item, dict):
                    edge = GraphEdge.from_dict(item)
                    if edge.source_node_id and edge.target_node_id:
                        self._edges[edge.edge_id] = edge
        self._load_embeddings()
        if loaded_graph:
            self.sanitize_canonical_graph(save=True)
        self._mark_index_dirty()

    def save(self) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": GRAPH_VERSION,
            "nodes": [node.to_dict() for node in sorted(self._nodes.values(), key=lambda n: n.node_id)],
            "edges": [edge.to_dict() for edge in sorted(self._edges.values(), key=lambda e: e.edge_id)],
        }
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            dir=self.store_dir,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        try:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.close()
            Path(tmp.name).replace(self.graph_path)
        except BaseException:
            Path(tmp.name).unlink(missing_ok=True)
            raise
        self._save_embeddings()

    def sanitize_canonical_graph(self, save: bool = True) -> dict[str, int]:
        """Move non-contract artifacts out of canonical state pathing."""
        counts = {"nodes": 0, "edges": 0}
        for node in list(self._nodes.values()):
            if (
                node.kind == NODE_KIND_AUXILIARY
                and node.state_contract is None
                and node.retrieval_profile
            ):
                contract = self._profile_contract_for_existing_node(node)
                if contract is None or not _is_canonical_state_contract(contract):
                    continue
                self._nodes[node.node_id] = replace(
                    node,
                    state_contract=contract,
                    kind=NODE_KIND_STATE,
                    fingerprint=state_contract_fingerprint(contract) or node.fingerprint,
                )
                counts["nodes"] += 1

        deprecated_promotions = 0
        for node in list(self._nodes.values()):
            if (
                node.kind != NODE_KIND_STATE
                or node.status != NODE_STATUS_DEPRECATED
                or not _is_canonical_state_contract(node.state_contract)
                or not node.retrieval_profile
            ):
                continue
            candidate = self._best_active_version_for_deprecated(node)
            if candidate is None or candidate.node_id == node.node_id:
                continue
            for edge in list(self._edges.values()):
                if edge.source_node_id != node.node_id or edge.status != EDGE_STATUS_ACTIVE:
                    continue
                if self._has_equivalent_edge(
                    source_node_id=candidate.node_id,
                    target_node_id=edge.target_node_id,
                    action_type=edge.action_type,
                    target=edge.target,
                ):
                    continue
                self.upsert_edge(
                    GraphEdge(
                        edge_id=_stable_id(
                            "edge",
                            edge.platform,
                            edge.app,
                            candidate.node_id,
                            edge.target_node_id,
                            edge.action_type,
                            edge.target,
                            edge.skill_id,
                        ),
                        app=edge.app,
                        platform=edge.platform,
                        source_node_id=candidate.node_id,
                        target_node_id=edge.target_node_id,
                        action_type=edge.action_type,
                        target=edge.target,
                        parameters=dict(edge.parameters or {}),
                        precondition=candidate.state_contract,
                        skill_id=edge.skill_id,
                        stats=replace(edge.stats),
                    ),
                    save=False,
                )
                deprecated_promotions += 1

        for node in list(self._nodes.values()):
            if (
                node.kind == NODE_KIND_STATE
                and not _is_canonical_state_contract(node.state_contract)
            ):
                self._nodes[node.node_id] = replace(
                    node,
                    state_contract=None,
                    kind=NODE_KIND_AUXILIARY,
                )
                counts["nodes"] += 1

        for edge in list(self._edges.values()):
            source = self._nodes.get(edge.source_node_id)
            target = self._nodes.get(edge.target_node_id)
            if edge.source_node_id == edge.target_node_id:
                if edge.status == EDGE_STATUS_ACTIVE:
                    self._edges[edge.edge_id] = replace(edge, status=EDGE_STATUS_DISABLED)
                    counts["edges"] += 1
                continue
            if (
                edge.status == EDGE_STATUS_DISABLED
                and edge.action_type != "open_app"
                and source is not None
                and target is not None
                and source.kind == NODE_KIND_STATE
                and target.kind == NODE_KIND_STATE
                and _is_canonical_state_contract(source.state_contract)
                and _is_canonical_state_contract(target.state_contract)
            ):
                self._edges[edge.edge_id] = replace(edge, status=EDGE_STATUS_ACTIVE)
                counts["edges"] += 1
                continue
            if edge.status != EDGE_STATUS_ACTIVE:
                continue
            source = self._nodes.get(edge.source_node_id)
            target = self._nodes.get(edge.target_node_id)
            if source is None or target is None:
                continue
            if source.kind != NODE_KIND_STATE or target.kind != NODE_KIND_STATE:
                self._edges[edge.edge_id] = replace(edge, status=EDGE_STATUS_DISABLED)
                counts["edges"] += 1

        if save and (counts["nodes"] or counts["edges"] or deprecated_promotions):
            self.save()
        if counts["nodes"] or counts["edges"] or deprecated_promotions:
            self._mark_index_dirty()
        return counts

    def canonicality_report(self, *, platform: str, app: str) -> GraphCanonicalityReport:
        platform_norm = (platform or "unknown").strip().lower()
        app_norm = normalize_app_identifier(platform_norm, app)
        active_state_nodes = 0
        anchored_state_nodes = 0
        auxiliary_nodes = 0
        deprecated_nodes = 0
        unanchored_state_nodes = 0

        for node in self._nodes.values():
            if node.platform != platform_norm or node.app != app_norm:
                continue
            if node.status == NODE_STATUS_DEPRECATED:
                deprecated_nodes += 1
            if node.kind == NODE_KIND_AUXILIARY:
                auxiliary_nodes += 1
            if node.kind == NODE_KIND_STATE and node.status == NODE_STATUS_ACTIVE:
                active_state_nodes += 1
                if _is_canonical_state_contract(node.state_contract):
                    anchored_state_nodes += 1
                else:
                    unanchored_state_nodes += 1

        self_loop_edges = 0
        for edge in self._edges.values():
            if (
                edge.platform != platform_norm
                or edge.app != app_norm
                or edge.status != EDGE_STATUS_ACTIVE
                or edge.source_node_id != edge.target_node_id
            ):
                continue
            source = self._nodes.get(edge.source_node_id)
            target = self._nodes.get(edge.target_node_id)
            if (
                source is not None
                and target is not None
                and _is_active_state_node(source)
                and _is_active_state_node(target)
            ):
                self_loop_edges += 1

        blocking_reasons: list[str] = []
        if unanchored_state_nodes:
            blocking_reasons.append("unanchored_state_nodes")
        if self_loop_edges:
            blocking_reasons.append("self_loop_edges")
        return GraphCanonicalityReport(
            platform=platform_norm,
            app=app_norm,
            active_state_nodes=active_state_nodes,
            anchored_state_nodes=anchored_state_nodes,
            auxiliary_nodes=auxiliary_nodes,
            deprecated_nodes=deprecated_nodes,
            self_loop_edges=self_loop_edges,
            unanchored_state_nodes=unanchored_state_nodes,
            blocking_reasons=tuple(blocking_reasons),
            ready_for_graph_only=not blocking_reasons and anchored_state_nodes > 0,
        )

    def _best_active_version_for_deprecated(self, node: GraphNode) -> GraphNode | None:
        def candidate_score(candidate: GraphNode) -> float:
            contract_score = state_contract_overlap(node.state_contract, candidate.state_contract)
            profile_score = _profile_similarity(node.retrieval_profile, candidate.retrieval_profile)
            description_score = _token_similarity(node.description, candidate.description)
            return max(contract_score, profile_score, description_score)

        if node.superseded_by:
            successor = self._nodes.get(node.superseded_by)
            if (
                successor is not None
                and successor.node_id != node.node_id
                and successor.platform == node.platform
                and successor.app == node.app
                and successor.kind == NODE_KIND_STATE
                and successor.status == NODE_STATUS_ACTIVE
                and _is_canonical_state_contract(successor.state_contract)
            ):
                return successor

        best_node: GraphNode | None = None
        best_score = 0.0
        for candidate in self._nodes.values():
            if (
                candidate.node_id == node.node_id
                or candidate.platform != node.platform
                or candidate.app != node.app
                or candidate.kind != NODE_KIND_STATE
                or candidate.status != NODE_STATUS_ACTIVE
                or not _is_canonical_state_contract(candidate.state_contract)
            ):
                continue
            score = candidate_score(candidate)
            if score > best_score:
                best_score = score
                best_node = candidate
        return best_node if best_score >= 0.25 else None

    def _has_equivalent_edge(
        self,
        *,
        source_node_id: str,
        target_node_id: str,
        action_type: str | None,
        target: str | None,
    ) -> bool:
        for edge in self.list_edges(platform=self._nodes[source_node_id].platform, app=self._nodes[source_node_id].app):
            if (
                edge.source_node_id == source_node_id
                and edge.target_node_id == target_node_id
                and edge.action_type == action_type
                and edge.target == target
                and edge.status == EDGE_STATUS_ACTIVE
            ):
                return True
        return False

    def _profile_contract_for_existing_node(self, node: GraphNode) -> dict[str, Any] | None:
        labels: list[tuple[str | None, bool]] = []
        for edge in self._edges.values():
            if edge.app != node.app or edge.platform != node.platform:
                continue
            if edge.source_node_id == node.node_id and edge.action_type in {"tap", "long_press", "double_tap"}:
                labels.append((edge.target, True))
            elif edge.target_node_id == node.node_id:
                labels.append((edge.target, False))
        for label, require_clickable in labels:
            contract = _state_contract_from_retrieval_profile(
                node.retrieval_profile,
                app=node.app,
                platform=node.platform,
                target=label,
                require_clickable=require_clickable,
            )
            if contract is not None:
                return contract
        return None

    def list_nodes(
        self,
        *,
        platform: str | None = None,
        app: str | None = None,
        status: str | None = None,
        kind: str | None = None,
    ) -> list[GraphNode]:
        platform_norm = platform.strip().lower() if isinstance(platform, str) else None
        app_norm = normalize_app_identifier(platform_norm or "", app) if app and platform_norm else app
        nodes = []
        for node in self._nodes.values():
            if platform_norm and node.platform != platform_norm:
                continue
            if app_norm and node.app != app_norm:
                continue
            if status and node.status != status:
                continue
            if kind and node.kind != kind:
                continue
            nodes.append(node)
        return sorted(nodes, key=lambda n: n.node_id)

    def list_edges(
        self,
        *,
        platform: str | None = None,
        app: str | None = None,
        status: str | None = None,
    ) -> list[GraphEdge]:
        platform_norm = platform.strip().lower() if isinstance(platform, str) else None
        app_norm = normalize_app_identifier(platform_norm or "", app) if app and platform_norm else app
        edges = []
        for edge in self._edges.values():
            if platform_norm and edge.platform != platform_norm:
                continue
            if app_norm and edge.app != app_norm:
                continue
            if status and edge.status != status:
                continue
            edges.append(edge)
        return sorted(edges, key=lambda e: e.edge_id)

    def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def get_edge(self, edge_id: str) -> GraphEdge | None:
        return self._edges.get(edge_id)

    def stable_anchor_candidates(
        self,
        *,
        platform: str,
        app: str,
        activity_class: str | None = None,
    ) -> list[GraphNode]:
        app_key = self._app_key(platform, app)
        self._ensure_runtime_index(platform=platform, app=app)
        node_ids: tuple[str, ...] = ()
        activity = _clean_index_string(activity_class)
        if activity:
            node_ids = self._runtime_index.stable_by_activity.get((*app_key, activity), ())
        if not node_ids:
            node_ids = self._runtime_index.stable_by_app.get(app_key, ())
        candidates = [
            node for node_id in node_ids
            if (node := self._nodes.get(node_id)) is not None
        ]
        self._runtime_index.stable_anchor_scan_count = len(candidates)
        return candidates

    def retrieval_profile_candidates(
        self,
        *,
        platform: str,
        app: str,
    ) -> list[GraphNode]:
        app_key = self._app_key(platform, app)
        self._ensure_runtime_index(platform=platform, app=app)
        node_ids = self._runtime_index.retrieval_by_app.get(app_key, ())
        candidates = [
            node for node_id in node_ids
            if (node := self._nodes.get(node_id)) is not None
        ]
        self._runtime_index.retrieval_profile_scan_count = len(candidates)
        return candidates

    def outgoing_edges(self, node_id: str, *, include_auxiliary_source: bool = False) -> list[GraphEdge]:
        node = self._nodes.get(node_id)
        if node is None:
            return []
        self._ensure_runtime_index(platform=node.platform, app=node.app)
        edge_ids = self._runtime_index.outgoing_by_node.get(node_id, ())
        if include_auxiliary_source and node.kind == NODE_KIND_AUXILIARY and not edge_ids:
            edge_ids = tuple(
                edge.edge_id
                for edge in self.list_edges(platform=node.platform, app=node.app, status=EDGE_STATUS_ACTIVE)
                if edge.source_node_id == node_id
                and (target := self._nodes.get(edge.target_node_id)) is not None
                and _is_active_state_node(target)
            )
        return [edge for edge_id in edge_ids if (edge := self._edges.get(edge_id)) is not None]

    def index_stats(self) -> dict[str, int]:
        return {
            "stable_anchor_scan_count": self._runtime_index.stable_anchor_scan_count,
            "retrieval_profile_scan_count": self._runtime_index.retrieval_profile_scan_count,
            "dirty_app_count": len(self._runtime_index.dirty_apps),
            "stable_app_bucket_count": len(self._runtime_index.stable_by_app),
            "stable_activity_bucket_count": len(self._runtime_index.stable_by_activity),
            "retrieval_profile_bucket_count": len(self._runtime_index.retrieval_by_app),
            "outgoing_node_count": len(self._runtime_index.outgoing_by_node),
            "selector_signature_count": len(self._runtime_index.selector_signatures),
        }

    def upsert_node(self, node: GraphNode, *, save: bool = True) -> GraphNode:
        node = node.normalized()
        if node.kind == NODE_KIND_STATE and not _is_canonical_state_contract(node.state_contract):
            existing = self._nodes.get(node.node_id)
            if (
                existing is not None
                and existing.kind == NODE_KIND_STATE
                and _is_canonical_state_contract(existing.state_contract)
            ):
                merged = _merge_nodes(existing, _coerce_noncanonical_state_node(node))
                self._nodes[merged.node_id] = merged
                if node.node_id != merged.node_id:
                    self._embeddings.pop(node.node_id, None)
                self._mark_index_dirty(platform=merged.platform, app=merged.app)
                if save:
                    self.save()
                return merged
            node = _coerce_noncanonical_state_node(node)

        exact = self._find_exact_node(node)
        if exact is not None:
            merged = _merge_nodes(exact, node)
            self._nodes[merged.node_id] = merged
            if node.node_id != merged.node_id:
                self._embeddings.pop(node.node_id, None)
            self._mark_index_dirty(platform=merged.platform, app=merged.app)
            if save:
                self.save()
            return merged

        version_base = self._find_version_base(node)
        if version_base is not None:
            version = max(version_base.version + 1, node.version)
            node = GraphNode(
                node_id=_stable_id("node", node.platform, node.app, node.fingerprint, version),
                app=node.app,
                platform=node.platform,
                description=node.description,
                state_contract=node.state_contract,
                version=version,
                status=NODE_STATUS_ACTIVE,
                stats=node.stats,
                kind=node.kind,
                skill_ids=node.skill_ids,
                fingerprint=node.fingerprint,
                dismiss_action=node.dismiss_action,
                resume_policy=node.resume_policy,
                retrieval_profile=node.retrieval_profile,
            )
            self._nodes[version_base.node_id] = GraphNode(
                node_id=version_base.node_id,
                app=version_base.app,
                platform=version_base.platform,
                description=version_base.description,
                state_contract=version_base.state_contract,
                version=version_base.version,
                status=NODE_STATUS_DEPRECATED,
                superseded_by=node.node_id,
                stats=version_base.stats,
                kind=version_base.kind,
                skill_ids=version_base.skill_ids,
                fingerprint=version_base.fingerprint,
                dismiss_action=version_base.dismiss_action,
                resume_policy=version_base.resume_policy,
                retrieval_profile=version_base.retrieval_profile,
            )

        self._nodes[node.node_id] = node
        self._mark_index_dirty(platform=node.platform, app=node.app)
        if save:
            self.save()
        return node

    def upsert_edge(self, edge: GraphEdge, *, save: bool = True) -> GraphEdge:
        edge = edge.normalized()
        existing = self._edges.get(edge.edge_id)
        if existing is not None:
            edge = _merge_edges(existing, edge)
        self._edges[edge.edge_id] = edge
        self._mark_index_dirty(platform=edge.platform, app=edge.app)
        if save:
            self.save()
        return edge

    def set_node_status(
        self,
        node_id: str,
        *,
        status: str,
        superseded_by: str | None = None,
        save: bool = True,
    ) -> GraphNode | None:
        node = self._nodes.get(node_id)
        if node is None:
            return None
        updated = GraphNode(
            node_id=node.node_id,
            app=node.app,
            platform=node.platform,
            description=node.description,
            state_contract=node.state_contract,
            version=node.version,
            status=status,
            superseded_by=superseded_by,
            stats=node.stats,
            kind=node.kind,
            skill_ids=node.skill_ids,
            fingerprint=node.fingerprint,
            dismiss_action=node.dismiss_action,
            resume_policy=node.resume_policy,
            retrieval_profile=node.retrieval_profile,
        )
        self._nodes[node_id] = updated
        self._mark_index_dirty(platform=updated.platform, app=updated.app)
        if save:
            self.save()
        return updated

    def _resolve_continuation_anchor(
        self,
        continuation_anchor_id: str | None,
        *,
        app: str,
        platform: str,
        first_source: GraphNode,
    ) -> GraphNode | None:
        if not continuation_anchor_id:
            return None
        if first_source.kind != NODE_KIND_STATE or not _is_canonical_state_contract(first_source.state_contract):
            return None
        anchor = self._nodes.get(continuation_anchor_id)
        if anchor is None:
            return None
        if anchor.platform != platform or anchor.app != app:
            return None
        if anchor.status != NODE_STATUS_ACTIVE:
            return None
        if anchor.kind != NODE_KIND_STATE or not _is_canonical_state_contract(anchor.state_contract):
            return None
        if anchor.fingerprint and first_source.fingerprint and anchor.fingerprint == first_source.fingerprint:
            return anchor
        overlap = state_contract_overlap(anchor.state_contract, first_source.state_contract)
        if overlap < self.version_overlap_threshold:
            return None
        return anchor

    async def ingest_skill(
        self,
        skill: Skill,
        *,
        continuation_anchor_id: str | None = None,
        node_profiles: dict[int | str, dict[str, Any] | None] | None = None,
    ) -> None:
        """Import a flat skill as a graph path view."""
        if not skill.steps:
            return
        platform = (skill.platform or "unknown").strip().lower()
        app = normalize_app_identifier(platform, skill.app)
        source_candidates = [
            _source_node_from_step(
                skill,
                step,
                index,
                app=app,
                platform=platform,
                retrieval_profile=(node_profiles or {}).get(index),
            )
            for index, step in enumerate(skill.steps)
        ]
        continuation_anchor = self._resolve_continuation_anchor(
            continuation_anchor_id,
            app=app,
            platform=platform,
            first_source=source_candidates[0],
        )
        source_nodes = [
            self.upsert_node(candidate, save=False)
            for candidate in (
                source_candidates[1:] if continuation_anchor is not None else source_candidates
            )
        ]
        terminal = self.upsert_node(
            _terminal_node_from_step(
                skill,
                skill.steps[-1],
                app=app,
                platform=platform,
                retrieval_profile=(node_profiles or {}).get("terminal"),
            ),
            save=False,
        )
        if continuation_anchor is not None:
            path_nodes = [continuation_anchor] + source_nodes + [terminal]
        else:
            path_nodes = source_nodes + [terminal]
        for index, step in enumerate(skill.steps):
            source = path_nodes[index]
            target = path_nodes[index + 1]
            if source.node_id == target.node_id:
                continue
            self.upsert_edge(
                GraphEdge(
                    edge_id=_stable_id(
                        "edge",
                        platform,
                        app,
                        source.node_id,
                        target.node_id,
                        step.action_type,
                        step.target,
                        skill.skill_id,
                    ),
                    app=app,
                    platform=platform,
                    source_node_id=source.node_id,
                    target_node_id=target.node_id,
                    action_type=step.action_type,
                    target=step.target,
                    parameters=dict(step.fixed_values or step.parameters or {}),
                    precondition=source.state_contract,
                    skill_id=skill.skill_id,
                ),
                save=False,
            )
        await self.ensure_node_embeddings(path_nodes)
        self.save()

    async def migrate_flat_skills(self, skills: list[Skill]) -> dict[str, Any]:
        """Import flat skills and report basic coverage / exit criteria stats."""
        total = len(skills)
        replayable = 0
        for skill in skills:
            await self.ingest_skill(skill)
            if any(
                edge.skill_id == skill.skill_id
                for edge in self.list_edges(platform=skill.platform, app=skill.app)
            ):
                replayable += 1
        active_nodes = self.list_nodes(status=NODE_STATUS_ACTIVE)
        match_rates = [node.stats.contract_match_rate for node in active_nodes]
        avg_match_rate = sum(match_rates) / len(match_rates) if match_rates else 1.0
        coverage = replayable / total if total else 1.0
        return {
            "flat_skill_count": total,
            "replayable_skill_count": replayable,
            "graph_coverage_rate": coverage,
            "active_node_count": len(active_nodes),
            "active_edge_count": len(self.list_edges(status=EDGE_STATUS_ACTIVE)),
            "avg_contract_match_rate": avg_match_rate,
            "exit_criteria": {
                "coverage_90_percent": coverage >= 0.90,
                "contract_match_rate_90_percent": avg_match_rate >= 0.90,
                "p0_regression_guard": False,
            },
        }

    async def ensure_node_embeddings(self, nodes: list[GraphNode] | None = None) -> None:
        if self.embedding_provider is None:
            return
        if self._embeddings_signature != self.embedding_signature:
            self._embeddings.clear()
            self._embeddings_signature = self.embedding_signature

        target_nodes = nodes or list(self._nodes.values())
        missing = [
            node for node in target_nodes
            if node.node_id not in self._embeddings and node.description.strip()
        ]
        if not missing:
            return
        try:
            vectors = await self.embedding_provider.embed([node.description for node in missing])
        except Exception as exc:
            logger.warning("Failed to embed %d graph nodes: %s", len(missing), exc)
            return
        for node, vector in zip(missing, vectors):
            arr = np.asarray(vector, dtype=np.float32)
            self._embeddings[node.node_id] = arr
        self._save_embeddings()

    def resolve_active_node(self, node_id: str) -> GraphNode | None:
        seen: set[str] = set()
        current = self._nodes.get(node_id)
        while current is not None:
            if current.node_id in seen:
                return None
            seen.add(current.node_id)
            if current.status == NODE_STATUS_ACTIVE:
                return current
            if current.status == NODE_STATUS_ARCHIVED:
                return None
            if not current.superseded_by:
                return None
            current = self._nodes.get(current.superseded_by)
        return None

    def record_node_match(self, node_id: str, *, matched: bool, save: bool = True) -> None:
        node = self._nodes.get(node_id)
        if node is None:
            return
        now = time.time()
        stats = NodeStats(
            reach_count=node.stats.reach_count + 1,
            contract_match_count=node.stats.contract_match_count + (1 if matched else 0),
            contract_miss_count=node.stats.contract_miss_count + (0 if matched else 1),
            last_seen_at=now,
            last_verified_at=now if matched else node.stats.last_verified_at,
        )
        self._nodes[node_id] = GraphNode(
            node_id=node.node_id,
            app=node.app,
            platform=node.platform,
            description=node.description,
            state_contract=node.state_contract,
            version=node.version,
            status=node.status,
            superseded_by=node.superseded_by,
            stats=stats,
            kind=node.kind,
            skill_ids=node.skill_ids,
            fingerprint=node.fingerprint,
            dismiss_action=node.dismiss_action,
            resume_policy=node.resume_policy,
            retrieval_profile=node.retrieval_profile,
        )
        if save:
            self.save()

    def record_edge_attempt(
        self,
        edge_id: str,
        *,
        success: bool,
        latency_ms: float | None = None,
        failure_reason: str | None = None,
        save: bool = True,
    ) -> None:
        edge = self._edges.get(edge_id)
        if edge is None:
            return
        now = time.time()
        reasons = dict(edge.stats.failure_reason_counts)
        if failure_reason and not success:
            reasons[failure_reason] = reasons.get(failure_reason, 0) + 1
        attempts = edge.stats.attempt_count + 1
        successes = edge.stats.success_count + (1 if success else 0)
        if latency_ms is not None and edge.stats.avg_latency_ms is not None:
            avg_latency = (
                edge.stats.avg_latency_ms * edge.stats.attempt_count + float(latency_ms)
            ) / attempts
        else:
            avg_latency = float(latency_ms) if latency_ms is not None else edge.stats.avg_latency_ms
        stats = EdgeStats(
            attempt_count=attempts,
            success_count=successes,
            last_attempt_at=now,
            last_success_at=now if success else edge.stats.last_success_at,
            avg_latency_ms=avg_latency,
            failure_reason_counts=reasons,
        )
        self._edges[edge_id] = GraphEdge(
            edge_id=edge.edge_id,
            app=edge.app,
            platform=edge.platform,
            source_node_id=edge.source_node_id,
            target_node_id=edge.target_node_id,
            action_type=edge.action_type,
            target=edge.target,
            parameters=edge.parameters,
            precondition=edge.precondition,
            status=edge.status,
            stats=stats,
            skill_id=edge.skill_id,
            kind=edge.kind,
        )
        if save:
            self.save()

    def _app_key(self, platform: str | None, app: str | None) -> tuple[str, str]:
        platform_norm = (platform or "unknown").strip().lower()
        return (platform_norm, normalize_app_identifier(platform_norm, app or "unknown"))

    def _mark_index_dirty(self, *, platform: str | None = None, app: str | None = None) -> None:
        if platform is not None and app is not None:
            self._runtime_index.dirty_apps.add(self._app_key(platform, app))
            return
        keys = {
            self._app_key(node.platform, node.app)
            for node in self._nodes.values()
        }
        keys.update(
            self._app_key(edge.platform, edge.app)
            for edge in self._edges.values()
        )
        self._runtime_index.dirty_apps.update(keys)

    def _rebuild_runtime_index(self, app_key: tuple[str, str] | None = None) -> None:
        index = self._runtime_index
        if app_key is None:
            all_app_keys = {
                self._app_key(node.platform, node.app)
                for node in self._nodes.values()
            }
            all_app_keys.update(
                self._app_key(edge.platform, edge.app)
                for edge in self._edges.values()
            )
            index.stable_by_app.clear()
            index.stable_by_activity.clear()
            index.retrieval_by_app.clear()
            index.outgoing_by_node.clear()
            index.selector_signatures.clear()
            app_keys: set[tuple[str, str]] | None = None
        else:
            all_app_keys = {app_key}
            index.stable_by_app.pop(app_key, None)
            for key in list(index.stable_by_activity):
                if key[:2] == app_key:
                    index.stable_by_activity.pop(key, None)
            index.retrieval_by_app.pop(app_key, None)
            app_node_ids = {
                node.node_id
                for node in self._nodes.values()
                if self._app_key(node.platform, node.app) == app_key
            }
            for node_id in app_node_ids:
                index.outgoing_by_node.pop(node_id, None)
                index.selector_signatures.pop(node_id, None)
            app_keys = {app_key}

        stable_by_app: dict[tuple[str, str], list[str]] = {}
        stable_by_activity: dict[tuple[str, str, str], list[str]] = {}
        retrieval_by_app: dict[tuple[str, str], list[str]] = {}
        for node in self._nodes.values():
            node_key = self._app_key(node.platform, node.app)
            if app_keys is not None and node_key not in app_keys:
                continue
            if not _is_active_state_node(node) or not _is_canonical_state_contract(node.state_contract):
                continue
            stable_by_app.setdefault(node_key, []).append(node.node_id)
            activity = _contract_activity_class(node.state_contract)
            if activity:
                stable_by_activity.setdefault((*node_key, activity), []).append(node.node_id)
            index.selector_signatures[node.node_id] = _selector_signature(node.state_contract)

        for node in self._nodes.values():
            node_key = self._app_key(node.platform, node.app)
            if app_keys is not None and node_key not in app_keys:
                continue
            if node.status == NODE_STATUS_ARCHIVED or not node.retrieval_profile:
                continue
            retrieval_by_app.setdefault(node_key, []).append(node.node_id)

        for key in app_keys or stable_by_app:
            index.stable_by_app[key] = tuple(sorted(stable_by_app.get(key, [])))
        for key in all_app_keys:
            index.stable_by_app.setdefault(key, ())
        for key, node_ids in stable_by_activity.items():
            index.stable_by_activity[key] = tuple(sorted(node_ids))
        for key in all_app_keys:
            index.retrieval_by_app[key] = tuple(sorted(retrieval_by_app.get(key, [])))

        outgoing: dict[str, list[str]] = {}
        for edge in self._edges.values():
            edge_key = self._app_key(edge.platform, edge.app)
            if app_keys is not None and edge_key not in app_keys:
                continue
            if edge.status != EDGE_STATUS_ACTIVE:
                continue
            if edge.source_node_id == edge.target_node_id:
                continue
            source = self._nodes.get(edge.source_node_id)
            target = self._nodes.get(edge.target_node_id)
            if source is None or target is None:
                continue
            if (
                not _is_active_state_node(source)
                or not _is_active_state_node(target)
                or not _is_canonical_state_contract(source.state_contract)
                or not _is_canonical_state_contract(target.state_contract)
            ):
                continue
            outgoing.setdefault(edge.source_node_id, []).append(edge.edge_id)
        for node_id, edge_ids in outgoing.items():
            index.outgoing_by_node[node_id] = tuple(sorted(edge_ids))

        if app_key is None:
            index.dirty_apps.clear()
        else:
            index.dirty_apps.discard(app_key)

    def _ensure_runtime_index(self, *, platform: str | None = None, app: str | None = None) -> None:
        if platform is not None and app is not None:
            app_key = self._app_key(platform, app)
            if app_key in self._runtime_index.dirty_apps or app_key not in self._runtime_index.stable_by_app:
                self._rebuild_runtime_index(app_key=app_key)
            return
        if self._runtime_index.dirty_apps:
            self._rebuild_runtime_index()

    def append_refresh_trigger(self, payload: dict[str, Any]) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": time.time(),
            "reason": str(payload.get("reason") or "unknown"),
            "platform": payload.get("platform"),
            "app": payload.get("app"),
            "node_id": payload.get("node_id"),
            "candidate_node_ids": list(payload.get("candidate_node_ids") or []),
            "allowed_outputs": list(REFRESH_ALLOWED_OUTPUTS),
        }
        path = self.store_dir / REFRESH_QUEUE_FILENAME
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def append_transition_evidence(self, payload: dict[str, Any]) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": time.time(),
            "platform": payload.get("platform"),
            "app": payload.get("app"),
            "source_node_id": payload.get("source_node_id"),
            "action_type": payload.get("action_type"),
            "edge_kind": payload.get("edge_kind"),
            "target_node_id": payload.get("target_node_id"),
            "reason": str(payload.get("reason") or "unknown"),
            "candidate_node_ids": list(payload.get("candidate_node_ids") or []),
        }
        path = self.store_dir / TRANSITION_EVIDENCE_FILENAME
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _find_exact_node(self, node: GraphNode) -> GraphNode | None:
        for existing in self._nodes.values():
            if existing.platform != node.platform or existing.app != node.app:
                continue
            if existing.kind != node.kind:
                continue
            if existing.fingerprint and node.fingerprint and existing.fingerprint == node.fingerprint:
                return existing
            if (
                not existing.state_contract
                and not node.state_contract
                and _normalize_description(existing.description) == _normalize_description(node.description)
            ):
                return existing
        return None

    def _find_version_base(self, node: GraphNode) -> GraphNode | None:
        if node.kind != NODE_KIND_STATE or not _is_canonical_state_contract(node.state_contract):
            return None
        best: tuple[float, GraphNode] | None = None
        for existing in self._nodes.values():
            if existing.platform != node.platform or existing.app != node.app:
                continue
            if existing.kind != node.kind or existing.status != NODE_STATUS_ACTIVE:
                continue
            if not _is_canonical_state_contract(existing.state_contract) or existing.fingerprint == node.fingerprint:
                continue
            overlap = state_contract_overlap(existing.state_contract, node.state_contract)
            if overlap >= self.version_overlap_threshold:
                if best is None or overlap > best[0]:
                    best = (overlap, existing)
        return best[1] if best is not None else None

    def _load_embeddings(self) -> None:
        path = self.embeddings_path
        if not path.is_file():
            return
        try:
            payload = np.load(str(path), allow_pickle=True).item()
        except Exception as exc:
            logger.warning("Failed to load skill graph embeddings from %s: %s", path, exc)
            return
        if not isinstance(payload, dict):
            return
        signature = payload.get("embedding_signature")
        if signature != self.embedding_signature:
            return
        vectors = payload.get("vectors")
        if not isinstance(vectors, dict):
            return
        self._embeddings_signature = signature
        for node_id, vector in vectors.items():
            self._embeddings[str(node_id)] = np.asarray(vector, dtype=np.float32)

    def _save_embeddings(self) -> None:
        if not self._embeddings:
            self.embeddings_path.unlink(missing_ok=True)
            return
        self.store_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "embedding_signature": self.embedding_signature,
            "vectors": self._embeddings,
        }
        tmp_path = self.store_dir / "skill_graph_embeddings.tmp.npy"
        np.save(str(tmp_path), payload)
        tmp_path.replace(self.embeddings_path)


class GoalNodeResolver:
    """Resolve natural-language intent into a confirmed goal node."""

    def __init__(
        self,
        store: SkillGraphStore,
        *,
        confidence_threshold: float = _GOAL_CONFIDENCE_THRESHOLD,
        margin_threshold: float = _GOAL_MARGIN_THRESHOLD,
    ) -> None:
        self.store = store
        self.confidence_threshold = confidence_threshold
        self.margin_threshold = margin_threshold

    async def resolve(
        self,
        intent: str,
        *,
        platform: str | None = None,
        app: str | None = None,
        top_k: int = 5,
    ) -> GoalNodeResolution:
        state_nodes = [
            node for node in self.store.list_nodes(platform=platform, app=app, kind=NODE_KIND_STATE)
            if node.status != NODE_STATUS_ARCHIVED
        ]
        if state_nodes:
            await self.store.ensure_node_embeddings(state_nodes)
        query_vec = await _embed_query(self.store, intent)
        raw_candidates: list[GraphCandidate] = []
        for node in state_nodes:
            desc_score = _description_score(intent, node, self.store, query_vec)
            score = _rerank_goal_score(desc_score, node)
            if score <= 0:
                continue
            active = self.store.resolve_active_node(node.node_id)
            if active is None:
                continue
            raw_candidates.append(GraphCandidate(node=active, score=score, reason="active"))

        stable_candidates = _dedupe_candidates(raw_candidates)[:top_k]
        profile_nodes = self.store.retrieval_profile_candidates(
            platform=platform or "unknown",
            app=app or "unknown",
        )
        profile_candidates = _rank_retrieval_profile_candidates(
            profile_nodes,
            intent,
            reason="retrieval_profile",
            resolve_active_node=self.store.resolve_active_node,
        )[:top_k]

        candidates = _merge_candidate_groups(stable_candidates, profile_candidates)[:top_k]
        if not candidates:
            return GoalNodeResolution(status="unresolvable", reason="goal_unresolvable")
        top1 = candidates[0]
        top2_score = candidates[1].score if len(candidates) > 1 else 0.0
        margin = top1.score - top2_score
        if (
            top1.score >= self.confidence_threshold
            and margin >= self.margin_threshold
            and top1.node.kind == NODE_KIND_STATE
            and top1.node.state_contract is not None
        ):
            return GoalNodeResolution(
                status="confirmed",
                goal_node=top1.node,
                candidates=tuple(candidates),
                confidence=top1.score,
                reason="profile_only_match" if not stable_candidates and profile_candidates else None,
            )

        return GoalNodeResolution(
            status="candidates",
            goal_node=None,
            candidates=tuple(candidates),
            confidence=candidates[0].score,
            reason="profile_only_match" if not stable_candidates and profile_candidates else "low_confidence_or_ambiguous",
        )


class StateIdentifier:
    """Identify the current graph node from observation metadata."""

    def __init__(
        self,
        store: SkillGraphStore,
        *,
        confidence_threshold: float = _STATE_IDENTIFICATION_THRESHOLD,
        margin_threshold: float = _STATE_MARGIN_THRESHOLD,
    ) -> None:
        self.store = store
        self.confidence_threshold = confidence_threshold
        self.margin_threshold = margin_threshold

    async def identify(
        self,
        observation: Any | None = None,
        *,
        foreground_app: str | None = None,
        observation_extra: dict[str, Any] | None = None,
        platform: str | None = None,
        app: str | None = None,
        top_k: int = 5,
    ) -> StateIdentificationResult:
        actual_app = (
            foreground_app
            or getattr(observation, "foreground_app", None)
            or (observation.get("foreground_app") if isinstance(observation, dict) else None)
            or (observation.get("app") if isinstance(observation, dict) else None)
        )
        platform_filter = platform or getattr(observation, "platform", None)
        app_filter = app or actual_app

        interrupts = await self._rank_nodes(
            observation,
            foreground_app=actual_app,
            observation_extra=observation_extra,
            platform=platform_filter,
            app=app_filter,
            kind=NODE_KIND_INTERRUPT,
        )
        if interrupts and interrupts[0].score >= self.confidence_threshold:
            return StateIdentificationResult(
                status="interrupt",
                current_node=interrupts[0].node,
                candidates=tuple(interrupts[:top_k]),
                confidence=interrupts[0].score,
            )

        stable_candidates = await self._rank_nodes(
            observation,
            foreground_app=actual_app,
            observation_extra=observation_extra,
            platform=platform_filter,
            app=app_filter,
            kind=NODE_KIND_STATE,
        )
        stable_candidates = stable_candidates[:top_k]
        profile_candidates = await self._rank_retrieval_profile_nodes(
            observation,
            foreground_app=actual_app,
            observation_extra=observation_extra,
            platform=platform_filter,
            app=app_filter,
        )
        profile_candidates = profile_candidates[:top_k]

        candidates = _merge_candidate_groups(stable_candidates, profile_candidates)[:top_k]
        if not candidates:
            return StateIdentificationResult(status="unknown", reason="state_identification_miss")

        top1 = candidates[0]
        top2_score = candidates[1].score if len(candidates) > 1 else 0.0
        if (
            top1.score >= self.confidence_threshold
            and (top1.score - top2_score) >= self.margin_threshold
            and top1.node.kind == NODE_KIND_STATE
            and top1.node.state_contract is not None
        ):
            self.store.record_node_match(top1.node.node_id, matched=True)
            return StateIdentificationResult(
                status="matched",
                current_node=top1.node,
                candidates=tuple(candidates),
                confidence=top1.score,
                reason="profile_only_match" if not stable_candidates and profile_candidates else None,
            )

        reason = "profile_only_match" if not stable_candidates and profile_candidates else "low_confidence_or_ambiguous"
        for candidate in candidates:
            if candidate.reason == "retrieval_profile":
                continue
            self.store.record_node_match(candidate.node.node_id, matched=False, save=False)
        self.store.save()
        return StateIdentificationResult(
            status="unknown",
            candidates=tuple(candidates),
            confidence=top1.score,
            reason=reason,
        )

    async def _rank_nodes(
        self,
        observation: Any | None,
        *,
        foreground_app: str | None,
        observation_extra: dict[str, Any] | None,
        platform: str | None,
        app: str | None,
        kind: str,
    ) -> list[GraphCandidate]:
        ranked: list[GraphCandidate] = []
        if kind == NODE_KIND_STATE:
            activity = _observation_activity_class(observation, observation_extra)
            nodes = self.store.stable_anchor_candidates(
                platform=platform or getattr(observation, "platform", None) or "unknown",
                app=app or foreground_app or "unknown",
                activity_class=activity,
            )
        else:
            nodes = self.store.list_nodes(platform=platform, app=app, status=NODE_STATUS_ACTIVE, kind=kind)
        for node in nodes:
            if not node.state_contract:
                continue
            score = score_state_contract(
                node.state_contract,
                observation=observation,
                foreground_app=foreground_app,
                observation_extra=observation_extra,
            )
            if score is None or score <= 0:
                continue
            final = 0.85 * score + 0.10 * node.stats.contract_match_rate + 0.05 * _recency_score(node.stats.last_seen_at)
            ranked.append(GraphCandidate(node=node, score=final, reason="contract"))
        ranked.sort(key=lambda c: (-c.score, c.node.node_id))
        return ranked

    async def _rank_retrieval_profile_nodes(
        self,
        observation: Any | None,
        *,
        foreground_app: str | None,
        observation_extra: dict[str, Any] | None,
        platform: str | None,
        app: str | None,
    ) -> list[GraphCandidate]:
        query_text = _observation_profile_query_text(observation, observation_extra)
        nodes = self.store.retrieval_profile_candidates(
            platform=platform or getattr(observation, "platform", None) or "unknown",
            app=app or foreground_app or "unknown",
        )
        ranked: list[GraphCandidate] = []
        for node in nodes:
            profile_score = _profile_recall_score(query_text, node.retrieval_profile)
            if profile_score <= 0:
                continue
            active = self.store.resolve_active_node(node.node_id)
            if active is None:
                continue
            final = 0.80 * profile_score + 0.10 * active.stats.contract_match_rate + 0.10 * _recency_score(active.stats.last_seen_at)
            ranked.append(GraphCandidate(node=active, score=final, reason="retrieval_profile"))
        ranked.sort(key=lambda c: (-c.score, c.node.node_id))
        return ranked


class PathCompiler:
    """Compile deterministic weighted paths between graph nodes."""

    def __init__(self, store: SkillGraphStore) -> None:
        self.store = store

    def compile(self, current_node_id: str, goal_node_id: str) -> PathCompilation:
        paths = self.compile_k_shortest(current_node_id, goal_node_id, k=1)
        if paths:
            return paths[0]
        if current_node_id == goal_node_id:
            node = self.store.get_node(current_node_id)
            if node is None:
                return PathCompilation(status="blocked", reason="current_node_missing")
            if not _is_active_state_node(node):
                return PathCompilation(status="blocked", reason="non_state_node")
            return PathCompilation(status="ok", nodes=(node,))
        if self.store.get_node(current_node_id) is None:
            return PathCompilation(status="blocked", reason="current_node_missing")
        if self.store.get_node(goal_node_id) is None:
            return PathCompilation(status="blocked", reason="goal_node_missing")
        if self.store.get_node(goal_node_id) is None:
            return PathCompilation(status="blocked", reason="goal_node_missing")
        paths = self.compile_k_shortest(current_node_id, goal_node_id, k=1)
        if paths:
            return paths[0]
        return PathCompilation(status="blocked", reason="no_path")

    def compile_k_shortest(
        self,
        current_node_id: str,
        goal_node_id: str,
        *,
        k: int = 3,
    ) -> list[PathCompilation]:
        if k <= 0:
            return []
        current_node = self.store.get_node(current_node_id)
        goal_node = self.store.get_node(goal_node_id)
        if (
            current_node is None
            or goal_node is None
            or not _is_active_state_node(current_node)
            or not _is_active_state_node(goal_node)
        ):
            return []
        if current_node_id == goal_node_id:
            return [PathCompilation(status="ok", nodes=(current_node,))]

        queue: list[tuple[float, str, tuple[str, ...], tuple[str, ...]]] = [
            (0.0, current_node_id, (current_node_id,), ())
        ]
        results: list[PathCompilation] = []
        seen_paths: set[tuple[str, ...]] = set()

        while queue and len(results) < k:
            cost, node_id, node_path, path_edge_ids = heapq.heappop(queue)
            if node_id == goal_node_id:
                if path_edge_ids in seen_paths:
                    continue
                seen_paths.add(path_edge_ids)
                edges = tuple(
                    edge
                    for edge in (self.store.get_edge(edge_id) for edge_id in path_edge_ids)
                    if edge is not None
                )
                nodes = tuple(
                    node
                    for node in (self.store.get_node(node_id) for node_id in node_path)
                    if node is not None
                )
                results.append(
                    PathCompilation(
                        status="ok",
                        edges=edges,
                        nodes=nodes,
                        total_cost=cost,
                    )
                )
                continue

            for edge_cost, edge in self._ranked_outgoing_edges(node_id):
                target = edge.target_node_id
                if target in node_path:
                    continue
                heapq.heappush(
                    queue,
                    (
                        cost + edge_cost,
                        target,
                        node_path + (target,),
                        path_edge_ids + (edge.edge_id,),
                    ),
                )

        return results

    def compile_deepest_prefix(
        self,
        current_node_id: str,
        intent: str,
        *,
        platform: str,
        app: str,
        max_depth: int = 6,
        min_relevance: float = _GOAL_CONFIDENCE_THRESHOLD,
    ) -> PathCompilation:
        current_node = self.store.get_node(current_node_id)
        if current_node is None:
            return PathCompilation(status="blocked", reason="current_node_missing")
        if current_node.status != NODE_STATUS_ACTIVE:
            return PathCompilation(status="blocked", reason="current_node_inactive")
        if current_node.kind not in {NODE_KIND_STATE, NODE_KIND_AUXILIARY}:
            return PathCompilation(status="blocked", reason="non_state_node")
        if current_node.kind == NODE_KIND_STATE and current_node.state_contract is None:
            return PathCompilation(status="blocked", reason="non_state_node")
        platform_norm = (platform or "unknown").strip().lower()
        app_norm = normalize_app_identifier(platform_norm, app or "unknown")
        if current_node.platform != platform_norm or current_node.app != app_norm:
            return PathCompilation(status="blocked", reason="current_node_app_mismatch")

        max_depth = max(0, int(max_depth))
        queue: list[tuple[int, str, tuple[str, ...], tuple[str, ...]]] = [
            (0, current_node_id, (current_node_id,), ())
        ]
        best_paths: dict[str, tuple[int, tuple[str, ...], tuple[str, ...]]] = {
            current_node_id: (0, (current_node_id,), ())
        }

        while queue:
            depth, node_id, node_path, edge_ids = queue.pop(0)
            if depth >= max_depth:
                continue
            for _, edge in self._ranked_outgoing_edges(node_id):
                target_id = edge.target_node_id
                if target_id in node_path:
                    continue
                target = self.store.get_node(target_id)
                if target is None or not _is_active_state_node(target) or not target.state_contract:
                    continue
                next_depth = depth + 1
                next_node_path = node_path + (target_id,)
                next_edge_ids = edge_ids + (edge.edge_id,)
                existing = best_paths.get(target_id)
                next_reliability = _path_reliability(self.store, next_edge_ids)
                if (
                    existing is None
                    or next_depth < existing[0]
                    or (
                        next_depth == existing[0]
                        and next_reliability > _path_reliability(self.store, existing[2])
                    )
                    or (
                        next_depth == existing[0]
                        and math.isclose(next_reliability, _path_reliability(self.store, existing[2]))
                        and next_edge_ids < existing[2]
                    )
                ):
                    best_paths[target_id] = (next_depth, next_node_path, next_edge_ids)
                queue.append((next_depth, target_id, next_node_path, next_edge_ids))

        candidates: list[tuple[int, float, float, str, tuple[str, ...], tuple[str, ...]]] = []
        for node_id, (depth, node_path, edge_ids) in best_paths.items():
            if depth <= 0:
                continue
            node = self.store.get_node(node_id)
            if node is None or not _is_active_state_node(node) or not node.state_contract:
                continue
            relevance = _prefix_relevance_score(intent, node)
            if relevance < min_relevance:
                continue
            candidates.append((
                depth,
                relevance,
                _path_reliability(self.store, edge_ids),
                node_id,
                node_path,
                edge_ids,
            ))

        if not candidates:
            return PathCompilation(status="blocked", reason="no_relevant_prefix")

        candidates.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3]))
        _, _, _, _, node_path, edge_ids = candidates[0]
        edges = tuple(
            edge
            for edge in (self.store.get_edge(edge_id) for edge_id in edge_ids)
            if edge is not None
        )
        nodes = tuple(
            node
            for node in (self.store.get_node(node_id) for node_id in node_path)
            if node is not None
        )
        return PathCompilation(
            status="ok",
            edges=edges,
            nodes=nodes,
            total_cost=sum(_edge_cost(edge) for edge in edges),
        )

    def _ranked_outgoing_edges(self, node_id: str) -> list[tuple[float, GraphEdge]]:
        ranked: list[tuple[float, GraphEdge]] = []
        node = self.store.get_node(node_id)
        include_auxiliary_source = bool(node is not None and node.kind == NODE_KIND_AUXILIARY)
        for edge in self.store.outgoing_edges(node_id, include_auxiliary_source=include_auxiliary_source):
            if edge.kind != "action":
                continue
            if edge.source_node_id == edge.target_node_id:
                continue
            target = self.store.get_node(edge.target_node_id)
            if target is None or not _is_active_state_node(target):
                continue
            edge_score = _edge_score(edge)
            if edge_score < _EDGE_HARD_SCORE_THRESHOLD:
                continue
            ranked.append((_edge_cost(edge), edge))
        ranked.sort(key=lambda item: (item[0], item[1].edge_id))
        return ranked


def _is_active_state_node(node: GraphNode) -> bool:
    return node.kind == NODE_KIND_STATE and node.status == NODE_STATUS_ACTIVE


def _coerce_noncanonical_state_node(node: GraphNode) -> GraphNode:
    if node.kind != NODE_KIND_STATE:
        return node
    if _is_canonical_state_contract(node.state_contract):
        return node
    return replace(node, state_contract=None, kind=NODE_KIND_AUXILIARY)


def _is_canonical_state_contract(contract: dict[str, Any] | None) -> bool:
    normalized = normalize_state_contract(contract)
    if not normalized:
        return False
    anchor = normalized.get("anchor")
    if not isinstance(anchor, dict) or not anchor.get("app_package"):
        return False
    signature = normalized.get("signature")
    if not isinstance(signature, dict):
        return False
    required = signature.get("required")
    if not isinstance(required, list):
        return False
    for element in required:
        if not isinstance(element, dict):
            continue
        selector = element.get("selector")
        if not isinstance(selector, dict):
            continue
        if selector_is_static(selector) and any(
            _clean_index_string(selector.get(key))
            for key in ("resource_id", "content_desc", "text", "class", "xpath")
        ):
            return True
    return False


def _prefix_relevance_score(intent: str, node: GraphNode) -> float:
    return _rerank_goal_score(
        max(
            _token_similarity(intent, node.description),
            _profile_recall_score(intent, node.retrieval_profile),
        ),
        node,
    )


def _path_reliability(store: SkillGraphStore, edge_ids: tuple[str, ...]) -> float:
    if not edge_ids:
        return 1.0
    score = 1.0
    for edge_id in edge_ids:
        edge = store.get_edge(edge_id)
        if edge is None:
            return 0.0
        score *= _edge_score(edge)
    return score


def _edge_cost(edge: GraphEdge) -> float:
    return -math.log(max(_edge_score(edge), 1e-6)) + 0.05


def _contract_activity_class(contract: Any) -> str | None:
    normalized = normalize_state_contract(contract)
    if not normalized:
        return None
    anchor = normalized.get("anchor")
    if not isinstance(anchor, dict):
        return None
    return _clean_index_string(anchor.get("activity_class"))


def _observation_activity_class(observation: Any | None, observation_extra: dict[str, Any] | None) -> str | None:
    extra = observation_extra or getattr(observation, "extra", None) or {}
    if not isinstance(extra, dict):
        return None
    value = extra.get("activity_class") or extra.get("activity") or extra.get("fragment_class")
    return _clean_index_string(value)


def _selector_signature(contract: Any) -> SelectorSignature:
    normalized = normalize_state_contract(contract)
    if not normalized:
        return SelectorSignature()
    resource_ids: set[str] = set()
    content_descs: set[str] = set()
    texts: set[str] = set()
    signature = normalized.get("signature")
    if not isinstance(signature, dict):
        return SelectorSignature()
    for bucket in ("required", "forbidden"):
        elements = signature.get(bucket)
        if not isinstance(elements, list):
            continue
        for element in elements:
            if not isinstance(element, dict):
                continue
            selector = element.get("selector")
            if not isinstance(selector, dict):
                continue
            resource_id = _clean_index_string(selector.get("resource_id"))
            content_desc = _clean_index_string(selector.get("content_desc"))
            text = _clean_index_string(selector.get("text"))
            if resource_id:
                resource_ids.add(resource_id)
            if content_desc:
                content_descs.add(content_desc)
            if text:
                texts.add(text)
    return SelectorSignature(
        resource_ids=frozenset(resource_ids),
        content_descs=frozenset(content_descs),
        texts=frozenset(texts),
    )


def _clean_index_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _source_node_from_step(
    skill: Skill,
    step: SkillStep,
    index: int,
    *,
    app: str,
    platform: str,
    retrieval_profile: dict[str, Any] | None = None,
) -> GraphNode:
    description = (
        step.valid_state
        or step.expected_state
        or step.target
        or f"{skill.name} step {index + 1}"
    )
    contract = normalize_state_contract(step.state_contract)
    if contract is None and step.action_type not in {"open_app", "wait"}:
        contract = _state_contract_from_retrieval_profile(
            retrieval_profile,
            app=app,
            platform=platform,
            target=step.target,
            require_clickable=step.action_type in {"tap", "long_press", "double_tap"},
        )
    kind = NODE_KIND_STATE if _is_canonical_state_contract(contract) else NODE_KIND_AUXILIARY
    fingerprint = state_contract_fingerprint(contract) or _stable_id(
        "node-desc",
        platform,
        app,
        description,
        index,
    )
    return GraphNode(
        node_id=_stable_id("node", platform, app, fingerprint, 1),
        app=app,
        platform=platform,
        description=description,
        state_contract=contract,
        version=1,
        status=NODE_STATUS_ACTIVE,
        kind=kind,
        skill_ids=(skill.skill_id,),
        fingerprint=fingerprint,
        retrieval_profile=retrieval_profile,
    )


def _terminal_node_from_step(
    skill: Skill,
    step: SkillStep,
    *,
    app: str,
    platform: str,
    retrieval_profile: dict[str, Any] | None = None,
) -> GraphNode:
    description = step.expected_state or step.target or skill.description or skill.name
    contract = _state_contract_from_retrieval_profile(
        retrieval_profile,
        app=app,
        platform=platform,
        target=step.target or step.expected_state or skill.description,
        require_clickable=False,
    )
    kind = NODE_KIND_STATE if _is_canonical_state_contract(contract) else NODE_KIND_AUXILIARY
    fingerprint = state_contract_fingerprint(contract) or _stable_id("terminal", platform, app, description)
    return GraphNode(
        node_id=_stable_id("node", platform, app, fingerprint, 1),
        app=app,
        platform=platform,
        description=description,
        state_contract=contract,
        version=1,
        status=NODE_STATUS_ACTIVE,
        kind=kind,
        skill_ids=(skill.skill_id,),
        fingerprint=fingerprint,
        retrieval_profile=retrieval_profile,
    )


def _state_contract_from_retrieval_profile(
    profile: dict[str, Any] | None,
    *,
    app: str,
    platform: str,
    target: str | None,
    require_clickable: bool,
) -> dict[str, Any] | None:
    normalized = _normalize_retrieval_profile(profile)
    if not normalized:
        return None
    profile_app = normalized.get("foreground_app") or normalized.get("app")
    if profile_app and normalize_app_identifier(platform, str(profile_app)) != app:
        return None
    target_text = _normalize_profile_text(target)
    if not target_text or _looks_like_abstract_target(target_text):
        target_text = _normalize_profile_text(normalized.get("page_title"))
    selector = _profile_selector_for_label(
        normalized,
        target_text,
        require_clickable=require_clickable,
    )
    if selector is None and not require_clickable:
        selector = _profile_selector_for_label(
            normalized,
            _first_profile_label(normalized),
            require_clickable=False,
        )
    if selector is None:
        return None
    states = ["visible", "clickable"] if require_clickable else ["visible"]
    return normalize_state_contract({
        "anchor": {"app_package": app},
        "signature": {
            "required": [{"selector": selector, "state": states}],
            "forbidden": [],
        },
        "mask_rules": ["counter", "temporary_recommendation"],
    })


def _profile_selector_for_label(
    profile: dict[str, Any],
    label: str | None,
    *,
    require_clickable: bool,
) -> dict[str, str] | None:
    label_norm = _normalize_profile_text(label)
    if not label_norm:
        return None
    for control in profile.get("stable_controls") or []:
        if not isinstance(control, dict):
            continue
        control_labels = [
            _normalize_profile_text(control.get("text")),
            _normalize_profile_text(control.get("content_desc")),
        ]
        if label_norm not in control_labels:
            continue
        resource_id = _normalize_profile_text(control.get("resource_id"))
        content_desc = _normalize_profile_text(control.get("content_desc"))
        text = _normalize_profile_text(control.get("text"))
        if resource_id:
            return {"resource_id": resource_id}
        if content_desc:
            return {"content_desc": content_desc}
        if text:
            return {"text": text}

    visible = set(filter_static_texts(profile.get("visible_text"), limit=80))
    clickable = set(filter_static_texts(profile.get("clickable_text"), limit=80))
    content_desc = set(filter_static_texts(profile.get("content_desc"), limit=80))
    if label_norm in content_desc and (not require_clickable or label_norm in clickable):
        return {"content_desc": label_norm}
    if label_norm in visible and (not require_clickable or label_norm in clickable):
        return {"text": label_norm}
    return None


def _first_profile_label(profile: dict[str, Any]) -> str | None:
    for key in ("page_title", "visible_text", "content_desc", "clickable_text"):
        value = profile.get(key)
        if isinstance(value, str):
            text = _normalize_profile_text(value)
            if text:
                return text
        if isinstance(value, list):
            for item in value:
                text = _normalize_profile_text(item)
                if text:
                    return text
    return None


def _looks_like_abstract_target(text: str) -> bool:
    lowered = text.lower()
    abstract_markers = (
        "launch ",
        "open ",
        "button",
        "tab",
        "navigation",
        "bottom",
        "page",
        "screen",
        "no need",
        "verify",
    )
    return any(marker in lowered for marker in abstract_markers)


def _normalize_retrieval_profile(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(profile, dict):
        return None
    normalized: dict[str, Any] = {}
    for key in ("foreground_app", "app", "platform", "page_title", "page_summary"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            normalized[key] = value.strip()
    for key in ("visible_text", "clickable_text", "content_desc"):
        values = filter_static_texts(profile.get(key), limit=40)
        if values:
            normalized[key] = values
    values = filter_static_resource_ids(profile.get("resource_ids"), limit=40)
    if values:
        normalized["resource_ids"] = values
    stable_controls = _normalize_stable_controls(profile.get("stable_controls"))
    if stable_controls:
        normalized["stable_controls"] = stable_controls
    return normalized or None


def _normalize_stable_controls(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return filter_static_controls(value, limit=12)


def _normalize_profile_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _merge_retrieval_profiles(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any] | None,
) -> dict[str, Any] | None:
    existing_norm = _normalize_retrieval_profile(existing)
    incoming_norm = _normalize_retrieval_profile(incoming)
    if existing_norm is None:
        return incoming_norm
    if incoming_norm is None:
        return existing_norm
    merged: dict[str, Any] = dict(existing_norm)
    for key in ("foreground_app", "app", "platform", "page_title", "page_summary"):
        if not merged.get(key) and incoming_norm.get(key):
            merged[key] = incoming_norm[key]
    for key in ("visible_text", "clickable_text", "content_desc", "resource_ids"):
        merged[key] = _merge_text_lists(merged.get(key), incoming_norm.get(key), limit=40)
    merged["stable_controls"] = _merge_stable_controls(merged.get("stable_controls"), incoming_norm.get("stable_controls"))
    return _normalize_retrieval_profile(merged)


def _merge_text_lists(existing: Any, incoming: Any, *, limit: int) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for source in (existing, incoming):
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            values.append(text)
            if len(values) >= limit:
                return values
    return values


def _merge_stable_controls(existing: Any, incoming: Any) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for source in (existing, incoming):
        for control in filter_static_controls(source, limit=12):
            key = (control.get("text"), control.get("content_desc"), control.get("resource_id"))
            if key in seen or not any(key):
                continue
            seen.add(key)
            merged.append(control)
            if len(merged) >= 12:
                return merged
    return merged


def _profile_texts(profile: dict[str, Any] | None) -> list[str]:
    normalized = _normalize_retrieval_profile(profile)
    if not normalized:
        return []
    texts: list[str] = []
    for key in ("page_title", "page_summary"):
        value = normalized.get(key)
        if isinstance(value, str) and value.strip():
            texts.append(value.strip())
    for key in ("visible_text", "clickable_text", "content_desc", "resource_ids"):
        values = normalized.get(key)
        if isinstance(values, list):
            texts.extend(str(item).strip() for item in values if isinstance(item, str) and item.strip())
    controls = normalized.get("stable_controls")
    if isinstance(controls, list):
        for control in controls:
            if not isinstance(control, dict):
                continue
            label = (
                control.get("text")
                or control.get("content_desc")
                or control.get("resource_id")
            )
            if isinstance(label, str) and label.strip():
                texts.append(label.strip())
    return _dedupe_strings(texts)


def _profile_similarity(left: dict[str, Any] | None, right: dict[str, Any] | None) -> float:
    left_texts = set(_profile_texts(left))
    right_texts = set(_profile_texts(right))
    if not left_texts or not right_texts:
        return 0.0
    return len(left_texts & right_texts) / len(left_texts | right_texts)


def _best_text_score(needle: str, haystack: list[str]) -> float:
    needle_norm = _normalize_profile_text(needle)
    if not needle_norm:
        return 0.0
    needle_casefold = needle_norm.casefold()
    best = 0.0
    needle_tokens = set(_tokens(needle_casefold))
    for item in haystack:
        item_norm = _normalize_profile_text(item)
        if not item_norm:
            continue
        item_casefold = item_norm.casefold()
        if needle_casefold == item_casefold:
            return 1.0
        if needle_casefold in item_casefold or item_casefold in needle_casefold:
            best = max(best, 0.92)
            continue
        item_tokens = set(_tokens(item_casefold))
        if needle_tokens and item_tokens:
            overlap = len(needle_tokens & item_tokens) / len(needle_tokens | item_tokens)
            if overlap:
                best = max(best, 0.55 + 0.35 * overlap)
    return best


def _profile_recall_score(query: str, profile: dict[str, Any] | None) -> float:
    texts = _profile_texts(profile)
    if not texts:
        return 0.0
    return max((_best_text_score(query, [text]) for text in texts), default=0.0)


def _observation_profile_query_text(
    observation: Any | None,
    observation_extra: dict[str, Any] | None,
) -> str:
    extra = observation_extra
    if not isinstance(extra, dict):
        extra = getattr(observation, "extra", None)
        if not isinstance(extra, dict):
            extra = {}

    parts: list[str] = []
    for key in ("page_title", "title", "toolbar_title"):
        value = extra.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    for key in ("visible_text", "clickable_text", "content_desc"):
        parts.extend(filter_static_texts(extra.get(key), limit=40))
    parts.extend(filter_static_resource_ids(extra.get("resource_ids"), limit=40))
    ui_tree = extra.get("ui_tree")
    if isinstance(ui_tree, list):
        for control in filter_static_controls(ui_tree, limit=40):
            for key in ("text", "content_desc", "resource_id"):
                value = control.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
    return " ".join(_dedupe_strings(parts))


async def _embed_query(store: SkillGraphStore, text: str) -> np.ndarray | None:
    if store.embedding_provider is None:
        return None
    try:
        vector = (await store.embedding_provider.embed([text]))[0]
        return np.asarray(vector, dtype=np.float32)
    except Exception as exc:
        logger.warning("Failed to embed goal intent: %s", exc)
        return None


def _description_score(
    intent: str,
    node: GraphNode,
    store: SkillGraphStore,
    query_vec: np.ndarray | None,
) -> float:
    if query_vec is not None and node.node_id in store._embeddings:
        return _cosine_similarity(query_vec, store._embeddings[node.node_id])
    return _token_similarity(intent, node.description)


def _rerank_goal_score(desc_score: float, node: GraphNode) -> float:
    reach = 1.0 - math.exp(-max(0, node.stats.reach_count) / 10.0)
    match = node.stats.contract_match_rate
    recency = _recency_score(node.stats.last_seen_at or node.stats.last_verified_at)
    return 0.70 * desc_score + 0.15 * reach + 0.10 * match + 0.05 * recency


def _rank_retrieval_profile_candidates(
    nodes: list[GraphNode],
    query_text: str,
    *,
    reason: str,
    resolve_active_node: Any | None = None,
) -> list[GraphCandidate]:
    ranked: list[GraphCandidate] = []
    if not query_text.strip():
        return ranked
    for node in nodes:
        candidate_node = node
        if callable(resolve_active_node):
            active = resolve_active_node(node.node_id)
            if active is None:
                continue
            candidate_node = active
        profile_score = _profile_recall_score(query_text, node.retrieval_profile)
        if profile_score <= 0:
            continue
        ranked.append(GraphCandidate(node=candidate_node, score=_rerank_goal_score(profile_score, candidate_node), reason=reason))
    ranked.sort(key=lambda c: (-c.score, c.node.node_id))
    return _dedupe_candidates(ranked)


def _dedupe_candidates(candidates: list[GraphCandidate]) -> list[GraphCandidate]:
    by_id: dict[str, GraphCandidate] = {}
    for candidate in candidates:
        existing = by_id.get(candidate.node.node_id)
        if existing is None or candidate.score > existing.score:
            by_id[candidate.node.node_id] = candidate
    out = list(by_id.values())
    out.sort(key=lambda c: (-c.score, c.node.node_id))
    return out


def _merge_candidate_groups(*groups: list[GraphCandidate]) -> list[GraphCandidate]:
    merged: list[GraphCandidate] = []
    seen: set[str] = set()
    for group in groups:
        for candidate in group:
            if candidate.node.node_id in seen:
                continue
            seen.add(candidate.node.node_id)
            merged.append(candidate)
    return merged


def _edge_score(edge: GraphEdge) -> float:
    recency = _recency_score(edge.stats.last_success_at or edge.stats.last_attempt_at)
    precondition = 1.0 if edge.precondition else 0.92
    return max(0.0, min(1.0, edge.stats.success_rate * recency * precondition))


def _recency_score(timestamp: float | None) -> float:
    if timestamp is None:
        return 0.5
    age_days = max(0.0, (time.time() - timestamp) / 86400.0)
    return 1.0 / (1.0 + age_days / 14.0)


def _merge_nodes(existing: GraphNode, incoming: GraphNode) -> GraphNode:
    skill_ids = tuple(_dedupe_strings(existing.skill_ids + incoming.skill_ids))
    description = incoming.description if len(incoming.description) > len(existing.description) else existing.description
    stats = NodeStats(
        reach_count=max(existing.stats.reach_count, incoming.stats.reach_count),
        contract_match_count=max(existing.stats.contract_match_count, incoming.stats.contract_match_count),
        contract_miss_count=max(existing.stats.contract_miss_count, incoming.stats.contract_miss_count),
        last_seen_at=max(
            [value for value in (existing.stats.last_seen_at, incoming.stats.last_seen_at) if value is not None],
            default=None,
        ),
        last_verified_at=max(
            [value for value in (existing.stats.last_verified_at, incoming.stats.last_verified_at) if value is not None],
            default=None,
        ),
    )
    return GraphNode(
        node_id=existing.node_id,
        app=existing.app,
        platform=existing.platform,
        description=description,
        state_contract=existing.state_contract or incoming.state_contract,
        version=existing.version,
        status=existing.status if existing.status != NODE_STATUS_ARCHIVED else incoming.status,
        superseded_by=existing.superseded_by,
        stats=stats,
        kind=existing.kind,
        skill_ids=skill_ids,
        fingerprint=existing.fingerprint or incoming.fingerprint,
        dismiss_action=existing.dismiss_action or incoming.dismiss_action,
        resume_policy=existing.resume_policy or incoming.resume_policy,
        retrieval_profile=_merge_retrieval_profiles(existing.retrieval_profile, incoming.retrieval_profile),
    )


def _merge_edges(existing: GraphEdge, incoming: GraphEdge) -> GraphEdge:
    return GraphEdge(
        edge_id=existing.edge_id,
        app=existing.app,
        platform=existing.platform,
        source_node_id=existing.source_node_id,
        target_node_id=existing.target_node_id,
        action_type=existing.action_type or incoming.action_type,
        target=incoming.target or existing.target,
        parameters=incoming.parameters or existing.parameters,
        precondition=incoming.precondition or existing.precondition,
        status=existing.status,
        stats=existing.stats if existing.stats.attempt_count >= incoming.stats.attempt_count else incoming.stats,
        skill_id=incoming.skill_id or existing.skill_id,
        kind=existing.kind or incoming.kind,
    )


def _stable_id(*parts: Any) -> str:
    text = "|".join(str(part) for part in parts)
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-12:
        return 0.0
    return float(np.dot(a, b) / denom)


def _token_similarity(a: str, b: str) -> float:
    at = set(_tokens(a))
    bt = set(_tokens(b))
    if not at or not bt:
        return 0.0
    return len(at & bt) / len(at | bt)


def _tokens(text: str) -> list[str]:
    import re

    return re.findall(r"\w+", text.lower())


def _normalize_description(value: str) -> str:
    return " ".join(_tokens(value))


def _dedupe_strings(values: tuple[str, ...] | list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        out.append(text)
        seen.add(text)
    return out
