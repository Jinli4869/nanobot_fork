"""
opengui.skills.graph_runtime
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runtime executor for graph-compiled GUI skills.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from opengui.action import Action, parse_action
from opengui.interfaces import DeviceBackend
from opengui.observation import Observation
from opengui.skills.executor import ExecutionState
from opengui.skills.graph import (
    NODE_KIND_STATE,
    GoalNodeResolver,
    GraphCandidate,
    GraphEdge,
    GraphNode,
    GraphSessionCursor,
    PathCompilation,
    PathCompiler,
    SkillGraphStore,
    StateIdentificationResult,
    StateIdentifier,
)
from opengui.skills.normalization import normalize_app_identifier
from opengui.skills.state_contract import evaluate_state_contract

if TYPE_CHECKING:
    from opengui.trajectory.recorder import TrajectoryRecorder


def _normalize_runtime_app(platform: str | None, app: str | None) -> str | None:
    if not app:
        return None
    normalized = normalize_app_identifier(platform or "", app)
    return None if normalized == "unknown" else normalized


def _same_runtime_app(platform: str | None, left: str | None, right: str | None) -> bool:
    left_norm = _normalize_runtime_app(platform, left)
    right_norm = _normalize_runtime_app(platform, right)
    return bool(left_norm and right_norm and left_norm == right_norm)


_PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z_]\w*)\}\}")


@dataclass(frozen=True)
class GraphStepResult:
    edge_id: str
    action: Action | None
    state: ExecutionState
    backend_result: str = ""
    error: str | None = None
    failure_reason: str | None = None
    duration_s: float = 0.0


@dataclass(frozen=True)
class GraphRuntimeResult:
    state: ExecutionState
    goal_resolution: Any | None = None
    state_identification: StateIdentificationResult | None = None
    path: PathCompilation | None = None
    step_results: tuple[GraphStepResult, ...] = ()
    execution_summary: str | None = None
    error: str | None = None
    candidates: tuple[GraphCandidate, ...] = ()
    token_usage: dict[str, int] = field(default_factory=dict)
    prefix_only: bool = False
    prefix_terminal_node_id: str | None = None


class GraphRuntimeExecutor:
    def __init__(
        self,
        *,
        store: SkillGraphStore,
        backend: DeviceBackend,
        artifacts_root: Path | str,
        trajectory_recorder: TrajectoryRecorder | None = None,
        timeout: float = 5.0,
        session_cursor: GraphSessionCursor | None = None,
    ) -> None:
        self.store = store
        self.backend = backend
        self.artifacts_root = Path(artifacts_root)
        self.trajectory_recorder = trajectory_recorder
        self.timeout = timeout
        self.session_cursor = session_cursor or GraphSessionCursor()
        self.goal_resolver = GoalNodeResolver(store)
        self.state_identifier = StateIdentifier(store)
        self.path_compiler = PathCompiler(store)

    async def execute(
        self,
        task: str,
        *,
        platform: str | None = None,
        app_hint: str | None = None,
    ) -> GraphRuntimeResult:
        try:
            return await self._execute_impl(task, platform=platform, app_hint=app_hint)
        finally:
            self.store.save()

    async def _execute_impl(
        self,
        task: str,
        *,
        platform: str | None = None,
        app_hint: str | None = None,
    ) -> GraphRuntimeResult:
        observation = await self._observe("graph_initial")
        platform_filter = platform or observation.platform or self.backend.platform
        app_filter = _normalize_runtime_app(platform_filter, app_hint) or observation.foreground_app
        if app_filter and not _same_runtime_app(platform_filter, observation.foreground_app, app_filter):
            observation = await self._launch_target_app(app_filter, platform=platform_filter)
        observation = await self._clear_interrupts(
            observation,
            platform=platform_filter,
            app_hint=app_filter,
        )
        identified = await self.align_entry(
            observation,
            platform=platform_filter,
            app_hint=app_filter,
        )
        if identified.status == "unknown":
            identified, observation = await self._recover_unknown(
                observation,
                platform=platform_filter,
                app_hint=app_filter,
            )
        self._record(
            "graph_state_identification",
            status=identified.status,
            confidence=identified.confidence,
            current_node_id=identified.current_node.node_id if identified.current_node else None,
            candidate_count=len(identified.candidates),
        )
        if identified.status != "matched" or identified.current_node is None:
            if identified.status == "unknown":
                self._enqueue_refresh_trigger(
                    reason=identified.reason or "state_identification_miss",
                    observation=observation,
                    candidates=identified.candidates,
                    node_id=None,
                )
            return GraphRuntimeResult(
                state=ExecutionState.FAILED,
                state_identification=identified,
                candidates=identified.candidates,
                error=identified.reason or identified.status,
            )

        resolution = await self.goal_resolver.resolve(
            task,
            platform=platform_filter,
            app=app_filter,
        )
        self._record(
            "graph_goal_resolution",
            status=resolution.status,
            confidence=resolution.confidence,
            goal_node_id=resolution.goal_node.node_id if resolution.goal_node else None,
            candidate_count=len(resolution.candidates),
        )
        if resolution.status == "confirmed" and resolution.goal_node is not None:
            path = self.path_compiler.compile(identified.current_node.node_id, resolution.goal_node.node_id)
            prefix_only = False
        elif app_filter:
            path = self.path_compiler.compile_deepest_prefix(
                identified.current_node.node_id,
                task,
                platform=platform_filter,
                app=app_filter,
            )
            prefix_only = path.status == "ok"
        else:
            path = PathCompilation(status="blocked", reason="app_unavailable_for_prefix")
            prefix_only = False

        terminal = path.nodes[-1] if path.nodes else identified.current_node
        self._record(
            "graph_path_compiled",
            status=path.status,
            edge_count=len(path.edges),
            total_cost=path.total_cost,
            prefix_only=prefix_only,
            terminal_node_id=terminal.node_id if path.status == "ok" and terminal else None,
            reason=path.reason,
        )
        if path.status != "ok":
            return GraphRuntimeResult(
                state=ExecutionState.FAILED,
                goal_resolution=resolution,
                state_identification=identified,
                path=path,
                error=path.reason or path.status,
            )
        self._record(
            "graph_prefix_result",
            prefix_only=prefix_only,
            terminal_node_id=terminal.node_id if terminal else None,
            prefix_terminal_node_id=terminal.node_id if terminal else None,
            edge_count=len(path.edges),
        )

        placeholder_names = _path_placeholder_names(path)
        runtime_params = _infer_runtime_params(task, placeholder_names)
        missing_params = sorted(name for name in placeholder_names if name not in runtime_params)
        if placeholder_names:
            self._record(
                "graph_runtime_parameters",
                parameters=sorted(runtime_params),
                missing=missing_params,
            )

        step_results: list[GraphStepResult] = []
        current_observation = observation
        for edge in path.edges:
            step_result, current_observation = await self._execute_edge(
                edge,
                current_observation,
                params=runtime_params,
            )
            step_results.append(step_result)
            if step_result.state != ExecutionState.SUCCEEDED:
                return GraphRuntimeResult(
                    state=ExecutionState.FAILED,
                    goal_resolution=resolution,
                    state_identification=identified,
                    path=path,
                    step_results=tuple(step_results),
                    execution_summary=self._summary(step_results, prefix_only=prefix_only),
                    error=step_result.error or step_result.failure_reason,
                    prefix_only=prefix_only,
                    prefix_terminal_node_id=terminal.node_id if terminal else None,
                )

        if terminal is not None:
            final_observation = current_observation
            can_probe = (
                terminal.kind == NODE_KIND_STATE
                and terminal.state_contract is not None
                and len(path.nodes) >= 2
                and (not prefix_only or self.trajectory_recorder is None)
                and not any(
                    item.action is not None and item.action.action_type == "request_intervention"
                    for item in step_results
                )
            )
            if can_probe:
                final_observation, restored = await self._probe_and_restore_terminal(
                    terminal=terminal,
                    path=path,
                )
                if not restored:
                    post_probe = await self._identify_current(
                        final_observation,
                        platform=final_observation.platform or self.backend.platform,
                        app_hint=final_observation.foreground_app,
                    )
                    if post_probe.status == "matched" and post_probe.current_node is not None:
                        self.session_cursor.set(post_probe.current_node)
                    else:
                        self.session_cursor.clear("navigation_probe_restore_failed")
                else:
                    self.session_cursor.set(terminal)
            else:
                self.store.append_transition_evidence(
                    {
                        "platform": current_observation.platform or self.backend.platform or terminal.platform,
                        "app": current_observation.foreground_app or terminal.app,
                        "source_node_id": terminal.node_id,
                        "action_type": "back",
                        "edge_kind": "navigation_back",
                        "target_node_id": None,
                        "reason": "probe_skipped",
                        "candidate_node_ids": [],
                    }
                )
                self._record("graph_navigation_probe", status="skipped", reason="probe_skipped")
                self.session_cursor.set(terminal)
        return GraphRuntimeResult(
            state=ExecutionState.SUCCEEDED,
            goal_resolution=resolution,
            state_identification=identified,
            path=path,
            step_results=tuple(step_results),
            execution_summary=self._summary(step_results, prefix_only=prefix_only),
            prefix_only=prefix_only,
            prefix_terminal_node_id=terminal.node_id if terminal else None,
        )

    async def align_entry(
        self,
        observation: Observation,
        *,
        platform: str | None,
        app_hint: str | None,
    ) -> StateIdentificationResult:
        platform_filter = platform or observation.platform or self.backend.platform
        observation_app = observation.foreground_app
        requested_app = app_hint
        app_filter = observation_app or requested_app

        cached = self._matched_cached_cursor(
            observation,
            platform=platform_filter,
            app_hint=app_filter,
        )
        if cached is not None:
            self._record(
                "graph_entry_alignment",
                source="session_cursor",
                status="matched",
                current_node_id=cached.node_id,
                candidate_count=1,
                scan_count=0,
            )
            return StateIdentificationResult(
                status="matched",
                current_node=cached,
                candidates=(GraphCandidate(node=cached, score=1.0, reason="session_cursor"),),
                confidence=1.0,
            )

        identified = await self._identify_current(
            observation,
            platform=platform_filter,
            app_hint=app_filter,
        )
        if identified.status == "matched" and identified.current_node is not None:
            self.session_cursor.set(identified.current_node)
        self._record(
            "graph_entry_alignment",
            source="stable_anchor_bucket",
            status=identified.status,
            current_node_id=identified.current_node.node_id if identified.current_node else None,
            candidate_count=len(identified.candidates),
            scan_count=self.store.index_stats().get("stable_anchor_scan_count", 0),
        )
        return identified

    async def _execute_edge(
        self,
        edge: GraphEdge,
        observation: Observation,
        *,
        params: dict[str, str] | None = None,
    ) -> tuple[GraphStepResult, Observation]:
        started = time.monotonic()
        precondition = evaluate_state_contract(
            edge.precondition,
            observation=observation,
            foreground_app=observation.foreground_app,
            observation_extra=observation.extra,
        )
        if precondition is False:
            self.store.record_edge_attempt(edge.edge_id, success=False, failure_reason="precondition_miss")
            step_result = GraphStepResult(
                edge_id=edge.edge_id,
                action=None,
                state=ExecutionState.FAILED,
                error="precondition_miss",
                failure_reason="precondition_miss",
                duration_s=time.monotonic() - started,
            )
            self._record_graph_step(edge, step_result)
            return step_result, observation

        observation = await self._clear_interrupts(
            observation,
            platform=observation.platform or self.backend.platform,
            app_hint=observation.foreground_app,
        )
        try:
            action = self._action_from_edge(edge, params=params or {})
            backend_result = await self.backend.execute(action, timeout=self.timeout)
            if action.action_type not in {"wait", "done", "request_intervention"}:
                await asyncio.sleep(0.5)
            next_observation = await self._observe(f"graph_edge_{edge.edge_id}")
            target = self.store.get_node(edge.target_node_id)
            if target is None or not target.state_contract:
                self.store.record_edge_attempt(edge.edge_id, success=False, failure_reason="target_contract_miss")
                step_result = GraphStepResult(
                    edge_id=edge.edge_id,
                    action=action,
                    state=ExecutionState.FAILED,
                    backend_result=backend_result,
                    error="target_contract_miss",
                    failure_reason="target_contract_miss",
                    duration_s=time.monotonic() - started,
                )
                self._record_graph_step(edge, step_result)
                return step_result, next_observation
            target_match = evaluate_state_contract(
                target.state_contract,
                observation=next_observation,
                foreground_app=next_observation.foreground_app,
                observation_extra=next_observation.extra,
            )
            if target_match is not True:
                self.store.record_edge_attempt(edge.edge_id, success=False, failure_reason="target_contract_miss")
                step_result = GraphStepResult(
                    edge_id=edge.edge_id,
                    action=action,
                    state=ExecutionState.FAILED,
                    backend_result=backend_result,
                    error="target_contract_miss",
                    failure_reason="target_contract_miss",
                    duration_s=time.monotonic() - started,
                )
                self._record_graph_step(edge, step_result)
                return step_result, next_observation
            latency_ms = (time.monotonic() - started) * 1000.0
            self.store.record_edge_attempt(edge.edge_id, success=True, latency_ms=latency_ms)
            source_node = self.store.get_node(edge.source_node_id)
            navigation_kind = self._navigation_transition_kind(action, edge_target=edge.target)
            if navigation_kind is not None and source_node is not None:
                await self._capture_navigation_transition(
                    action=action,
                    source_node=source_node,
                    observation_after=next_observation,
                    edge_target=edge.target,
                )
            step_result = GraphStepResult(
                edge_id=edge.edge_id,
                action=action,
                state=ExecutionState.SUCCEEDED,
                backend_result=backend_result,
                duration_s=time.monotonic() - started,
            )
            self._record_graph_step(edge, step_result)
            return step_result, next_observation
        except Exception as exc:
            self.store.record_edge_attempt(edge.edge_id, success=False, failure_reason="action_error")
            action = None
            try:
                action = self._action_from_edge(edge, params=params or {})
            except Exception:
                pass
            step_result = GraphStepResult(
                edge_id=edge.edge_id,
                action=action,
                state=ExecutionState.FAILED,
                backend_result=str(exc),
                error=str(exc),
                failure_reason="action_error",
                duration_s=time.monotonic() - started,
            )
            self._record_graph_step(edge, step_result)
            return step_result, observation

    def _action_from_edge(self, edge: GraphEdge, *, params: dict[str, str] | None = None) -> Action:
        runtime_params = params or {}
        target = _ground_template_value(edge.target, runtime_params)
        parameters = _ground_template_value(dict(edge.parameters or {}), runtime_params)
        if not isinstance(parameters, dict):
            parameters = {}
        payload: dict[str, Any] = {"action_type": edge.action_type, **parameters}
        if edge.action_type in {"open_app", "close_app", "input_text"} and "text" not in payload:
            payload["text"] = target
        return parse_action(payload)

    def _navigation_transition_kind(self, action: Action, *, edge_target: str | None = None) -> str | None:
        if action.action_type == "back":
            return "navigation_back"
        if action.action_type == "home":
            return "navigation_home"
        if action.action_type != "tap":
            return None
        label = self._navigation_label(edge_target or action.text)
        if label in {"首页", "主页", "home", "main"}:
            return "navigation_reset"
        return None

    @staticmethod
    def _navigation_label(value: str | None) -> str:
        return " ".join((value or "").strip().split()).lower()

    async def _capture_navigation_transition(
        self,
        *,
        action: Action,
        source_node: GraphNode | None,
        observation_after: Observation,
        edge_target: str | None = None,
        identified: StateIdentificationResult | None = None,
        valid_target_node_ids: set[str] | None = None,
    ) -> StateIdentificationResult | None:
        if source_node is None or source_node.kind != NODE_KIND_STATE or source_node.state_contract is None:
            return identified
        navigation_kind = self._navigation_transition_kind(action, edge_target=edge_target)
        if navigation_kind is None:
            return identified
        started = time.monotonic()
        target = identified or await self._identify_current(
            observation_after,
            platform=observation_after.platform or self.backend.platform,
            app_hint=observation_after.foreground_app,
        )
        target_node = target.current_node if target.status == "matched" else None
        if (
            target_node is not None
            and target_node.node_id != source_node.node_id
            and (
                valid_target_node_ids is None
                or target_node.node_id in valid_target_node_ids
            )
        ):
            edge_id = f"nav:{source_node.node_id}:{target_node.node_id}:{action.action_type}:{navigation_kind}"
            self.store.upsert_edge(
                GraphEdge(
                    edge_id=edge_id,
                    app=source_node.app,
                    platform=source_node.platform,
                    source_node_id=source_node.node_id,
                    target_node_id=target_node.node_id,
                    action_type=action.action_type,
                    target=edge_target or action.text or action.action_type,
                    precondition=source_node.state_contract,
                    kind=navigation_kind,
                ),
                save=False,
            )
            self.store.record_edge_attempt(
                edge_id,
                success=True,
                latency_ms=(time.monotonic() - started) * 1000.0,
            )
            self._record(
                "graph_navigation_transition",
                action=action.action_type,
                source_node_id=source_node.node_id,
                target_node_id=target_node.node_id,
                kind=navigation_kind,
                matched=True,
            )
            return target

        reason = "navigation_target_unknown"
        target_node_id = None
        if target_node is not None:
            target_node_id = target_node.node_id
            if target_node.node_id == source_node.node_id:
                reason = "navigation_target_same"
            elif valid_target_node_ids is not None and target_node.node_id not in valid_target_node_ids:
                reason = "probe_restore_unavailable"
        self.store.append_transition_evidence(
            {
                "platform": observation_after.platform or self.backend.platform,
                "app": observation_after.foreground_app,
                "source_node_id": source_node.node_id,
                "action_type": action.action_type,
                "edge_kind": navigation_kind,
                "target_node_id": target_node_id,
                "reason": reason,
                "candidate_node_ids": [candidate.node.node_id for candidate in target.candidates],
            }
        )
        self._record(
            "graph_transition_evidence",
            action=action.action_type,
            source_node_id=source_node.node_id,
            candidate_count=len(target.candidates),
            reason=reason,
        )
        return target

    async def _launch_target_app(self, app: str, *, platform: str | None) -> Observation:
        self._record("graph_app_launch", app=app, platform=platform)
        await self.backend.execute(parse_action({"action_type": "open_app", "text": app}), timeout=self.timeout)
        current: Observation | None = None
        for attempt in range(3):
            if attempt:
                await asyncio.sleep(1.0)
            current = await self._observe(f"graph_launch_{attempt}")
            if _same_runtime_app(platform, current.foreground_app, app):
                return current
        return current if current is not None else await self._observe("graph_launch_final")

    async def _observe(self, stem: str) -> Observation:
        directory = self.artifacts_root / "graph_screenshots"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{stem}_{int(time.time() * 1000)}.png"
        return await self.backend.observe(path, timeout=self.timeout)

    def _record(self, event_type: str, **payload: Any) -> None:
        if self.trajectory_recorder is not None:
            self.trajectory_recorder.record_event(event_type, **payload)

    def _matched_cached_cursor(
        self,
        observation: Observation,
        *,
        platform: str | None,
        app_hint: str | None,
    ) -> GraphNode | None:
        effective_app = observation.foreground_app or app_hint
        if effective_app is None:
            self._record(
                "graph_entry_alignment",
                source="session_cursor",
                status="cached_app_unavailable",
                current_node_id=self.session_cursor.current_node_id,
                scan_count=0,
            )
            self.session_cursor.clear("cached_app_unavailable")
            return None
        if not self.session_cursor.compatible_with(platform=platform, app=effective_app):
            self._record(
                "graph_entry_alignment",
                source="session_cursor",
                status="cached_compatibility_miss",
                current_node_id=self.session_cursor.current_node_id,
                scan_count=0,
            )
            self.session_cursor.clear("cached_compatibility_miss")
            return None
        node = self.store.get_node(self.session_cursor.current_node_id or "")
        if node is None or not node.state_contract:
            self._record(
                "graph_entry_alignment",
                source="session_cursor",
                status="cached_contract_miss",
                current_node_id=self.session_cursor.current_node_id,
                scan_count=0,
            )
            self.session_cursor.clear("cached_contract_miss")
            return None
        active_node = self.store.resolve_active_node(node.node_id)
        if active_node is None or active_node.node_id != node.node_id:
            self._record(
                "graph_entry_alignment",
                source="session_cursor",
                status="cached_node_not_active",
                current_node_id=node.node_id,
                scan_count=0,
            )
            self.session_cursor.clear("cached_node_not_active")
            return None
        matched = evaluate_state_contract(
            node.state_contract,
            observation=observation,
            foreground_app=observation.foreground_app,
            observation_extra=observation.extra,
        )
        if matched is True:
            self.store.record_node_match(node.node_id, matched=True, save=False)
            return node
        self._record(
            "graph_entry_alignment",
            source="session_cursor",
            status="cached_contract_miss",
            current_node_id=node.node_id,
            scan_count=0,
        )
        self.session_cursor.clear("cached_contract_miss")
        self.store.record_node_match(node.node_id, matched=False, save=False)
        return None

    async def _identify_current(
        self,
        observation: Observation,
        *,
        platform: str | None,
        app_hint: str | None,
    ) -> StateIdentificationResult:
        identified = await self.state_identifier.identify(
            observation,
            foreground_app=observation.foreground_app,
            observation_extra=observation.extra,
            platform=platform,
            app=app_hint or observation.foreground_app,
        )
        self._record(
            "graph_state_identification_attempt",
            status=identified.status,
            confidence=identified.confidence,
            current_node_id=identified.current_node.node_id if identified.current_node else None,
            candidate_count=len(identified.candidates),
        )
        return identified

    async def _clear_interrupts(
        self,
        observation: Observation,
        *,
        platform: str | None,
        app_hint: str | None,
    ) -> Observation:
        current = observation
        for _ in range(2):
            identified = await self._identify_current(
                current,
                platform=platform,
                app_hint=app_hint,
            )
            if identified.status != "interrupt" or identified.current_node is None:
                return current
            current = await self._dismiss_interrupt(identified.current_node, current)
        return current

    async def _dismiss_interrupt(
        self,
        node: Any,
        observation: Observation,
    ) -> Observation:
        dismiss_action = getattr(node, "dismiss_action", None)
        if not dismiss_action:
            return observation
        action = parse_action(dismiss_action)
        self._record(
            "graph_interrupt_dismiss",
            node_id=getattr(node, "node_id", None),
            action=action.action_type,
        )
        await self.backend.execute(action, timeout=self.timeout)
        await asyncio.sleep(0.5)
        return await self._observe(f"graph_interrupt_{getattr(node, 'node_id', 'unknown')}")

    async def _probe_and_restore_terminal(
        self,
        *,
        terminal: GraphNode,
        path: PathCompilation,
    ) -> tuple[Observation, bool]:
        probe_action = parse_action({"action_type": "back"})
        await self.backend.execute(probe_action, timeout=self.timeout)
        await asyncio.sleep(0.5)
        probed = await self._observe("graph_navigation_probe")
        identified = await self._identify_current(
            probed,
            platform=probed.platform or self.backend.platform,
            app_hint=probed.foreground_app,
        )
        self._record(
            "graph_navigation_probe",
            status=identified.status,
            candidate_count=len(identified.candidates),
            current_node_id=identified.current_node.node_id if identified.current_node else None,
        )
        if identified.status != "matched" or identified.current_node is None:
            self.store.append_transition_evidence(
                {
                    "platform": probed.platform or self.backend.platform,
                    "app": probed.foreground_app,
                    "source_node_id": terminal.node_id,
                    "action_type": "back",
                    "edge_kind": "navigation_back",
                    "target_node_id": None,
                    "reason": "navigation_target_unknown",
                    "candidate_node_ids": [candidate.node.node_id for candidate in identified.candidates],
                }
            )
            self._record(
                "graph_transition_evidence",
                action="back",
                source_node_id=terminal.node_id,
                candidate_count=len(identified.candidates),
                reason="navigation_target_unknown",
            )
            return probed, False

        path_node_ids = {node.node_id for node in path.nodes}
        if identified.current_node.node_id not in path_node_ids:
            self.store.append_transition_evidence(
                {
                    "platform": probed.platform or self.backend.platform,
                    "app": probed.foreground_app,
                    "source_node_id": terminal.node_id,
                    "action_type": "back",
                    "edge_kind": "navigation_back",
                    "target_node_id": identified.current_node.node_id,
                    "reason": "probe_restore_unavailable",
                    "candidate_node_ids": [candidate.node.node_id for candidate in identified.candidates],
                }
            )
            self._record(
                "graph_transition_evidence",
                action="back",
                source_node_id=terminal.node_id,
                candidate_count=len(identified.candidates),
                reason="probe_restore_unavailable",
            )
            self._record(
                "graph_navigation_restore",
                status="skipped",
                reason="probe_restore_unavailable",
                current_node_id=identified.current_node.node_id,
            )
            return probed, False

        await self._capture_navigation_transition(
            action=probe_action,
            source_node=terminal,
            observation_after=probed,
            identified=identified,
            valid_target_node_ids=path_node_ids,
        )
        restore_path = self.path_compiler.compile(identified.current_node.node_id, terminal.node_id)
        if restore_path.status != "ok":
            self.store.append_transition_evidence(
                {
                    "platform": probed.platform or self.backend.platform,
                    "app": probed.foreground_app,
                    "source_node_id": terminal.node_id,
                    "action_type": "back",
                    "edge_kind": "navigation_back",
                    "target_node_id": identified.current_node.node_id,
                    "reason": "restore_failed",
                    "candidate_node_ids": [candidate.node.node_id for candidate in identified.candidates],
                }
            )
            self._record(
                "graph_transition_evidence",
                action="back",
                source_node_id=terminal.node_id,
                candidate_count=len(identified.candidates),
                reason="restore_failed",
            )
            self._record(
                "graph_navigation_restore",
                status="failed",
                reason="restore_failed",
                current_node_id=identified.current_node.node_id,
            )
            return probed, False

        restored = probed
        for edge in restore_path.edges:
            step_result, restored = await self._execute_edge(edge, restored)
            if step_result.state != ExecutionState.SUCCEEDED:
                self.store.append_transition_evidence(
                    {
                        "platform": restored.platform or self.backend.platform,
                        "app": restored.foreground_app,
                        "source_node_id": terminal.node_id,
                        "action_type": "back",
                        "edge_kind": "navigation_back",
                        "target_node_id": identified.current_node.node_id,
                        "reason": "restore_failed",
                        "candidate_node_ids": [candidate.node.node_id for candidate in identified.candidates],
                    }
                )
                self._record(
                    "graph_transition_evidence",
                    action="back",
                    source_node_id=terminal.node_id,
                    candidate_count=len(identified.candidates),
                    reason="restore_failed",
                )
                self._record(
                    "graph_navigation_restore",
                    status="failed",
                    reason="restore_failed",
                    current_node_id=identified.current_node.node_id,
                    failed_edge_id=edge.edge_id,
                )
                return restored, False
        self._record(
            "graph_navigation_restore",
            status="restored",
            terminal_node_id=terminal.node_id,
            restored_from_node_id=identified.current_node.node_id,
        )
        return restored, True

    async def _recover_unknown(
        self,
        observation: Observation,
        *,
        platform: str | None,
        app_hint: str | None,
    ) -> tuple[StateIdentificationResult, Observation]:
        resampled = await self._observe("graph_recovery_resample")
        resampled = await self._clear_interrupts(
            resampled,
            platform=platform,
            app_hint=app_hint,
        )
        identified = await self._identify_current(
            resampled,
            platform=platform,
            app_hint=app_hint,
        )
        self._record(
            "graph_recovery_attempt",
            strategy="resample",
            status=identified.status,
            confidence=identified.confidence,
        )
        return identified, resampled

    def _enqueue_refresh_trigger(
        self,
        *,
        reason: str,
        observation: Observation,
        candidates: tuple[GraphCandidate, ...],
        node_id: str | None = None,
    ) -> None:
        append = getattr(self.store, "append_refresh_trigger", None)
        if not callable(append):
            return
        append({
            "reason": reason,
            "platform": observation.platform or self.backend.platform,
            "app": observation.foreground_app,
            "node_id": node_id,
            "candidate_node_ids": [candidate.node.node_id for candidate in candidates],
        })
        self._record(
            "graph_refresh_trigger",
            reason=reason,
            node_id=node_id,
            candidate_count=len(candidates),
        )

    def _record_graph_step(self, edge: GraphEdge, step_result: GraphStepResult) -> None:
        self._record(
            "graph_step",
            edge_id=edge.edge_id,
            source_node_id=edge.source_node_id,
            target_node_id=edge.target_node_id,
            action=edge.action_type,
            target=edge.target,
            state=step_result.state.value,
            error=step_result.error,
            failure_reason=step_result.failure_reason,
            duration_s=round(step_result.duration_s, 3),
        )

    @staticmethod
    def _summary(step_results: list[GraphStepResult], *, prefix_only: bool = False) -> str:
        if not step_results:
            return "Graph prefix already at current target node." if prefix_only else "Graph path already at current target node."
        parts = [
            f"{item.edge_id}:{item.state.value}"
            for item in step_results
        ]
        prefix = "Graph prefix executed" if prefix_only else "Graph path executed"
        return prefix + ": " + "; ".join(parts)


def _path_placeholder_names(path: PathCompilation) -> set[str]:
    names: set[str] = set()
    for edge in path.edges:
        names.update(_placeholder_names(edge.target))
        names.update(_placeholder_names(edge.parameters))
    return names


def _placeholder_names(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(_PLACEHOLDER_RE.findall(value))
    if isinstance(value, dict):
        names: set[str] = set()
        for item in value.values():
            names.update(_placeholder_names(item))
        return names
    if isinstance(value, (list, tuple)):
        names: set[str] = set()
        for item in value:
            names.update(_placeholder_names(item))
        return names
    return set()


def _ground_template_value(value: Any, params: dict[str, str]) -> Any:
    if isinstance(value, str):
        grounded = value
        for key, replacement in params.items():
            grounded = grounded.replace(f"{{{{{key}}}}}", replacement)
        missing = sorted(set(_PLACEHOLDER_RE.findall(grounded)))
        if missing:
            raise ValueError(f"unresolved graph parameters: {', '.join(missing)}")
        return grounded
    if isinstance(value, dict):
        return {key: _ground_template_value(item, params) for key, item in value.items()}
    if isinstance(value, list):
        return [_ground_template_value(item, params) for item in value]
    if isinstance(value, tuple):
        return tuple(_ground_template_value(item, params) for item in value)
    return value


def _infer_runtime_params(task: str, names: set[str]) -> dict[str, str]:
    normalized = " ".join((task or "").split())
    if not normalized:
        return {}
    params: dict[str, str] = {}
    for name in names:
        value = _guess_runtime_param(normalized, name)
        if value:
            params[name] = value
    return params


def _guess_runtime_param(task: str, name: str) -> str | None:
    param = name.strip().casefold()
    if param in {"query", "keyword", "search_query", "search_term"}:
        quoted = re.search(r"[“\"']([^”\"']{1,80})[”\"']", task)
        if quoted is not None:
            return _clean_inferred_param(quoted.group(1))
        account = re.search(r"(?:找一下|找|搜索|搜)\s*([^，,。.!?；;、]{1,30}?)(?:的账号|账号)", task)
        if account is not None:
            return _clean_inferred_param(account.group(1))
        for pattern in (
            r"(?:搜索一下|搜一下|搜索|查找|搜)\s*([^\s，,。.!?；;、]+)",
            r"(?:search\s+for|search|find)\s*([^\s，,。.!?；;、]+)",
        ):
            match = re.search(pattern, task, flags=re.IGNORECASE)
            if match is not None:
                return _clean_inferred_param(match.group(1))
    if param in {"city", "location", "destination", "place", "area"}:
        for pattern in (
            r"(?:搜索一下|搜一下|搜索|查找|找一下)\s*([^，,。.!?；;、]{2,30}?)(?:周边|附近|的酒店|酒店|民宿)",
            r"(?:去|到)\s*([^，,。.!?；;、]{2,16}?)(?:附近|周边|住|的|，|,|要)",
            r"住在\s*([^，,。.!?；;、]{2,16}?)(?:附近|周边|，|,|要)",
        ):
            for match in re.finditer(pattern, task, flags=re.IGNORECASE):
                value = _clean_inferred_param(match.group(1))
                if value and not _looks_like_date_param(value):
                    return value
    return None


def _clean_inferred_param(value: str) -> str:
    return value.strip().strip('`"\'“”‘’').strip()


def _looks_like_date_param(value: str) -> bool:
    return bool(re.search(r"\d+\s*(?:月|号|日|/|-)", value))
