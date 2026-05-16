"""
opengui.skills.code_graph_projection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Project repaired flat skill code into graph-native ``@state``/``@transition``
declarations when trace evidence is strong enough.
"""

from __future__ import annotations

import ast
import hashlib
import json
import pprint
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opengui.skills.code_graph import compile_code_skills
from opengui.skills.data import Skill, SkillStep
from opengui.skills.normalization import normalize_app_identifier
from opengui.skills.state_contract import normalize_state_contract, state_contract_fingerprint
from opengui.skills.static_selector_filter import (
    filter_static_controls,
    filter_static_resource_ids,
    filter_static_texts,
    is_dynamic_resource_id,
    is_dynamic_text,
    is_static_resource_id,
    is_static_text,
    selector_is_static,
)

_CODE_HEADER = "from opengui.skills.code_graph import C, R, action, skill, state, tag, transition"
_SKIP_TRANSITION_ACTIONS = {"open_app", "close_app", "wait", "done", "request_intervention", "back", "home"}


@dataclass(frozen=True)
class GraphProjection:
    source: str
    emitted_states: tuple[dict[str, Any], ...] = ()
    emitted_transitions: tuple[dict[str, Any], ...] = ()
    skipped_transitions: tuple[dict[str, Any], ...] = ()
    quality: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "quality": self.quality,
            "emitted_states": list(self.emitted_states),
            "emitted_transitions": list(self.emitted_transitions),
            "skipped_transitions": list(self.skipped_transitions),
        }


@dataclass(frozen=True)
class _TraceStep:
    index: int
    action_type: str
    action: dict[str, Any]
    text_blob: str
    pre_observation: dict[str, Any] | None
    post_observation: dict[str, Any] | None
    action_selector: dict[str, Any] | None = None


@dataclass(frozen=True)
class _StateSpec:
    function_name: str
    node_id: str
    app: str
    platform: str
    description: str
    contract: dict[str, Any]
    skill_id: str
    step_index: int
    role: str
    retrieval_profile: dict[str, Any] | None = None


@dataclass(frozen=True)
class _TransitionSpec:
    function_name: str
    edge_id: str
    skill_id: str
    src: _StateSpec
    dst: _StateSpec
    step: SkillStep
    step_index: int


def project_graph_code_from_trace(source: str, trace_path: Path) -> GraphProjection:
    events = _load_events(trace_path) if trace_path.exists() else []
    return project_graph_code_from_events(source, events)


def project_graph_code_from_events(source: str, events: list[dict[str, Any]]) -> GraphProjection:
    """Append graph-native declarations derived from repaired code and trace evidence."""
    base_source = _strip_code_fences(source).strip()
    compiled = compile_code_skills(base_source)
    if compiled.errors or not compiled.skills:
        return GraphProjection(source=source)
    skill_names = {skill.name for skill in compiled.skills}
    base_source = _strip_graph_declarations_for_skills(base_source, skill_names)

    trace = _TraceIndex(events)
    states_by_fingerprint: dict[str, _StateSpec] = {}
    state_order: list[_StateSpec] = []
    transitions: list[_TransitionSpec] = []
    skipped: list[dict[str, Any]] = []

    def intern_state(
        *,
        skill: Skill,
        step_index: int,
        role: str,
        description: str,
        contract: dict[str, Any] | None,
        retrieval_profile: dict[str, Any] | None = None,
    ) -> _StateSpec | None:
        normalized = normalize_state_contract(contract)
        if not _is_canonical_contract(normalized):
            return None
        if not _contract_app_matches(normalized, app=skill.app, platform=skill.platform):
            return None
        fingerprint = state_contract_fingerprint(normalized) or _hash_key(skill.skill_id, step_index, role)
        existing = states_by_fingerprint.get(fingerprint)
        if existing is not None:
            return existing
        base_name = _safe_identifier(f"state_{skill.name}_{step_index}_{role}")
        func_name = _dedupe_name(base_name, {state.function_name for state in state_order})
        spec = _StateSpec(
            function_name=func_name,
            node_id=f"code:{func_name}:{_hash_key(fingerprint)[:10]}",
            app=skill.app,
            platform=skill.platform,
            description=description,
            contract=normalized or {},
            skill_id=skill.skill_id,
            step_index=step_index,
            role=role,
            retrieval_profile=_filter_retrieval_profile_to_contract(retrieval_profile, normalized),
        )
        states_by_fingerprint[fingerprint] = spec
        state_order.append(spec)
        return spec

    for skill in compiled.skills:
        trace_cursor = -1
        previous_trace_step: _TraceStep | None = None
        previous_target_state: _StateSpec | None = None
        pending_targetless: list[tuple[SkillStep, int, _StateSpec]] = []
        for index, step in enumerate(skill.steps):
            if step.action_type in _SKIP_TRANSITION_ACTIONS:
                previous_trace_step = None
                previous_target_state = None
                continue
            trace_step = trace.match(step, after=trace_cursor)
            if trace_step is not None:
                trace_cursor = trace_step.index
            source_dynamic_values = _dynamic_input_values(trace_step)
            if index > 0 and _step_has_parameterized_input_text(skill.steps[index - 1]):
                source_dynamic_values = (*source_dynamic_values, *_dynamic_input_values(previous_trace_step))
            source_contract = step.state_contract
            source_role_description = step.valid_state or step.target or f"{skill.name} step {index} source"
            if trace_step is not None and trace_step.pre_observation is None:
                source_contract = None
                source_role_description = f"{skill.name} step {index} source"
            elif not _is_strong_canonical_contract(source_contract):
                source_contract = (
                    _contract_from_action_evidence(
                        trace_step,
                        app=skill.app,
                        platform=skill.platform,
                        target=step.target,
                    )
                    or _contract_from_observation(
                        trace_step.pre_observation if trace_step is not None else None,
                        app=skill.app,
                        platform=skill.platform,
                        target=step.target,
                    )
                    or source_contract
                )
                source_role_description = f"{skill.name} step {index} source"
            if _step_has_parameterized_input_text(step):
                source_contract = _strip_dynamic_selector_text_from_contract(
                    source_contract,
                    dynamic_values=source_dynamic_values,
                    drop_identity_text=True,
                )
            source_profile = _retrieval_profile_from_observation(
                trace_step.pre_observation if trace_step is not None else None,
                dynamic_values=source_dynamic_values,
                drop_identity_text=_step_has_parameterized_input_text(step),
            )
            source_state = intern_state(
                skill=skill,
                step_index=index,
                role="src",
                description=source_role_description,
                contract=source_contract,
                retrieval_profile=source_profile,
            )
            edge_source_state = source_state or previous_target_state
            if (
                previous_target_state is not None
                and source_state is not None
                and previous_target_state.node_id != source_state.node_id
            ):
                edge_source_state = previous_target_state
            if source_state is not None and pending_targetless:
                resolved_pending = False
                for pending_step, pending_index, pending_source in pending_targetless:
                    if pending_source.node_id == source_state.node_id:
                        skipped.append(_skip_record(skill, pending_step, pending_index, "no_state_change"))
                        continue
                    transitions.append(_TransitionSpec(
                        function_name=_safe_identifier(
                            f"transition_{skill.name}_{pending_index}_{pending_step.action_type}"
                        ),
                        edge_id=(
                            "code:edge:"
                            + _hash_key(
                                skill.skill_id,
                                pending_index,
                                pending_source.node_id,
                                source_state.node_id,
                                pending_step.action_type,
                                pending_step.target,
                            )[:16]
                        ),
                        skill_id=skill.skill_id,
                        src=pending_source,
                        dst=source_state,
                        step=pending_step,
                        step_index=pending_index,
                    ))
                    resolved_pending = True
                pending_targetless.clear()
                if resolved_pending:
                    previous_target_state = source_state
                    edge_source_state = source_state
            target_observation = trace.target_observation_for(
                trace_step,
                app=skill.app,
                platform=skill.platform,
                source_contract=source_contract,
            )
            target_contract = _contract_from_observation(
                target_observation,
                app=skill.app,
                platform=skill.platform,
                target=None,
            )
            if _step_has_parameterized_input_text(step):
                target_contract = _strip_dynamic_selector_text_from_contract(
                    target_contract,
                    dynamic_values=_dynamic_input_values(trace_step),
                )
            elif _next_step_has_parameterized_input_text(skill, index):
                target_contract = _strip_dynamic_selector_text_from_contract(
                    target_contract,
                    drop_identity_text=True,
                )
            target_profile = _retrieval_profile_from_observation(
                target_observation,
                dynamic_values=_dynamic_input_values(trace_step),
                drop_identity_text=_next_step_has_parameterized_input_text(skill, index),
            )
            target_state = intern_state(
                skill=skill,
                step_index=index,
                role="dst",
                description=_target_state_description(skill, step, index),
                contract=target_contract,
                retrieval_profile=target_profile,
            )
            if edge_source_state is None:
                skipped.append(_skip_record(skill, step, index, "weak_source_state"))
                continue
            if target_state is None:
                if _trace_step_crosses_app(trace_step, app=skill.app, platform=skill.platform):
                    skipped.append(_skip_record(skill, step, index, "cross_app_target_state"))
                else:
                    pending_targetless.append((step, index, edge_source_state))
                continue
            if edge_source_state.node_id == target_state.node_id:
                skipped.append(_skip_record(skill, step, index, "no_state_change"))
                previous_target_state = target_state
                continue
            edge_key = _hash_key(
                skill.skill_id,
                index,
                edge_source_state.node_id,
                target_state.node_id,
                step.action_type,
                step.target,
            )
            transitions.append(_TransitionSpec(
                function_name=_safe_identifier(f"transition_{skill.name}_{index}_{step.action_type}"),
                edge_id=f"code:edge:{edge_key[:16]}",
                skill_id=skill.skill_id,
                src=edge_source_state,
                dst=target_state,
                step=step,
                step_index=index,
            ))
            previous_trace_step = trace_step
            previous_target_state = target_state
        for pending_step, pending_index, _pending_source in pending_targetless:
            skipped.append(_skip_record(skill, pending_step, pending_index, "weak_target_state"))

    graph_block = _graph_source_block(state_order, transitions)
    output_source = _ensure_graph_imports(base_source)
    if graph_block:
        output_source = output_source.rstrip() + "\n\n\n" + graph_block
    quality = "canonical" if transitions and not skipped else "partial" if state_order or transitions else "none"
    return GraphProjection(
        source=output_source.rstrip() + "\n",
        emitted_states=tuple(_state_record(state) for state in state_order),
        emitted_transitions=tuple(_transition_record(transition) for transition in transitions),
        skipped_transitions=tuple(skipped),
        quality=quality,
    )


class _TraceIndex:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._steps: list[_TraceStep] = []
        latest_observation: dict[str, Any] | None = None
        for event in events:
            if not isinstance(event, dict):
                continue
            event_type = event.get("type") or event.get("event")
            if event_type != "step":
                continue
            action = event.get("action") if isinstance(event.get("action"), dict) else {}
            action_type = str(action.get("action_type") or "").strip()
            post_observation = event.get("observation") if isinstance(event.get("observation"), dict) else None
            pre_observation = _event_pre_observation(event, latest_observation)
            self._steps.append(_TraceStep(
                index=int(event.get("step_index") or len(self._steps)),
                action_type=action_type,
                action=dict(action),
                text_blob=_trace_text_blob(event, action),
                pre_observation=pre_observation,
                post_observation=post_observation,
                action_selector=_action_selector_from_point(action, pre_observation),
            ))
            if post_observation is not None:
                latest_observation = post_observation
            elif action_type not in {"", "screenshot", "wait"}:
                latest_observation = None

    def match(self, step: SkillStep, *, after: int) -> _TraceStep | None:
        if not self._steps:
            return None
        target = str(step.target or "").strip().casefold()
        candidates = [
            candidate
            for candidate in self._steps
            if candidate.index > after and candidate.action_type == step.action_type
        ]
        if not candidates:
            return None
        scored: list[tuple[int, int, _TraceStep]] = []
        for candidate in candidates:
            score = 0
            if candidate.action_type == step.action_type:
                score += 4
            if _step_coordinates_match_trace_action(step, candidate.action):
                score += 20
            if target and _blob_mentions_target(candidate.text_blob, target):
                score += 3
            if target and _selector_mentions_target(candidate.action_selector, target):
                score += 3
            if target and (
                _observation_mentions(candidate.pre_observation, target)
                or _observation_mentions(candidate.post_observation, target)
            ):
                score += 2
            if score > 0:
                scored.append((-score, candidate.index, candidate))
        if not scored:
            return candidates[0]
        scored.sort(key=lambda item: (item[0], item[1]))
        return scored[0][2]

    def target_observation_for(
        self,
        trace_step: _TraceStep | None,
        *,
        app: str,
        platform: str,
        source_contract: dict[str, Any] | None,
        max_lookahead: int = 4,
    ) -> dict[str, Any] | None:
        """Find the first canonical post-state UI tree for this action.

        Some Android traces have an empty observation immediately after an
        action and only expose the loaded screen on the following wait or
        repeated-input event. Graph transitions should use that post UI tree
        instead of dropping the transition as weak.
        """
        if trace_step is None:
            return None
        source_fingerprint = state_contract_fingerprint(normalize_state_contract(source_contract))
        fallback: dict[str, Any] | None = None
        seen = 0
        for candidate in self._post_observations_for_action(trace_step):
            if fallback is None:
                fallback = candidate
            contract = _contract_from_observation(
                candidate,
                app=app,
                platform=platform,
                target=None,
            )
            if _is_canonical_contract(contract):
                candidate_fingerprint = state_contract_fingerprint(normalize_state_contract(contract))
                if not source_fingerprint or candidate_fingerprint != source_fingerprint:
                    return candidate
            seen += 1
            if seen >= max_lookahead:
                break
        return fallback

    def _post_observations_for_action(self, trace_step: _TraceStep) -> list[dict[str, Any]]:
        observations: list[dict[str, Any]] = []
        for step in self._steps:
            if step.index < trace_step.index:
                continue
            if step.index > trace_step.index and not _is_post_state_continuation(trace_step, step):
                break
            if isinstance(step.post_observation, dict):
                observations.append(step.post_observation)
        return observations


def _is_post_state_continuation(source: _TraceStep, candidate: _TraceStep) -> bool:
    if candidate.action_type in {"wait", "screenshot"}:
        return True
    return (
        candidate.action_type == source.action_type
        and bool(candidate.text_blob)
        and candidate.text_blob == source.text_blob
    )


def _event_pre_observation(
    event: dict[str, Any],
    fallback: dict[str, Any] | None,
) -> dict[str, Any] | None:
    for key in ("pre_observation", "before_observation", "observation_before"):
        value = event.get(key)
        if isinstance(value, dict):
            return value
    return fallback


def _contract_from_action_evidence(
    trace_step: _TraceStep | None,
    *,
    app: str,
    platform: str,
    target: str | None,
) -> dict[str, Any] | None:
    del platform, target
    if trace_step is None or not isinstance(trace_step.pre_observation, dict):
        return None
    selector = trace_step.action_selector
    if not isinstance(selector, dict):
        return None
    identity = _selector_without_state_flags(selector)
    if not identity:
        return None
    anchor_app = str(
        trace_step.pre_observation.get("foreground_app")
        or trace_step.pre_observation.get("app")
        or app
        or ""
    ).strip()
    if not anchor_app:
        return None
    contract = normalize_state_contract({
        "anchor": {"app_package": anchor_app},
        "signature": {
            "required": [{"selector": identity, "state": _selector_states(selector)}],
            "forbidden": [],
        },
    })
    return contract if _is_canonical_contract(contract) else None


def _contract_from_observation(
    observation: dict[str, Any] | None,
    *,
    app: str,
    platform: str,
    target: str | None = None,
) -> dict[str, Any] | None:
    del platform
    if not isinstance(observation, dict):
        return None
    anchor_app = str(observation.get("foreground_app") or observation.get("app") or app or "").strip()
    if not anchor_app:
        return None
    selectors = _selectors_from_observation(observation)
    target_selector = _target_identity_selector(selectors, target)
    if target_selector is not None:
        selector = _selector_without_state_flags(target_selector)
        return normalize_state_contract({
            "anchor": {"app_package": anchor_app},
            "signature": {
                "required": [{"selector": selector, "state": _selector_states(target_selector)}],
                "forbidden": [],
            },
        })
    identity_selectors = [
        selector
        for selector in selectors
        if selector.get("resource_id") or selector.get("content_desc")
    ]
    if len(identity_selectors) >= 2:
        return normalize_state_contract({
            "anchor": {"app_package": anchor_app},
            "signature": {
                "required": [
                    {
                        "selector": _selector_without_state_flags(selector),
                        "state": _selector_states(selector),
                    }
                    for selector in identity_selectors[:3]
                ],
                "forbidden": [],
            },
        })
    text_values = _text_values_from_selectors(selectors, target)
    if len(text_values) >= 2:
        return normalize_state_contract({
            "anchor": {"app_package": anchor_app},
            "signature": {
                "required": [
                    {"selector": {"text": text}, "state": ["visible"]}
                    for text in text_values[:4]
                ],
                "forbidden": [],
            },
        })
    if identity_selectors:
        selector = _selector_without_state_flags(identity_selectors[0])
        return normalize_state_contract({
            "anchor": {"app_package": anchor_app},
            "signature": {
                "required": [{"selector": selector, "state": _selector_states(identity_selectors[0])}],
                "forbidden": [],
            },
        })
    if text_values:
        text_selector = next(
            (
                selector
                for selector in selectors
                if isinstance(selector.get("text"), str)
                and selector.get("text") == text_values[0]
            ),
            {"text": text_values[0]},
        )
        text_states = _selector_states(text_selector)
        if not any(state in text_states for state in ("clickable", "focused", "scrollable")):
            return None
        return normalize_state_contract({
            "anchor": {"app_package": anchor_app},
            "signature": {
                "required": [
                    {
                        "selector": {"text": text_values[0]},
                        "state": text_states,
                    }
                ],
                "forbidden": [],
            },
        })
    return None


def _selectors_from_observation(observation: dict[str, Any]) -> list[dict[str, Any]]:
    extra = observation.get("extra") if isinstance(observation.get("extra"), dict) else {}
    selectors: list[dict[str, Any]] = []
    ui_tree = extra.get("ui_tree")
    if isinstance(ui_tree, list):
        for node in ui_tree:
            if not isinstance(node, dict):
                continue
            selector = _stable_selector_from_node(node)
            if selector and selector_is_static(selector):
                selectors.append(selector)
    for resource_id in filter_static_resource_ids(extra.get("resource_ids"), limit=20):
        selectors.append({"resource_id": resource_id})
    for content_desc in filter_static_texts(extra.get("content_desc"), limit=20):
        selectors.append({"content_desc": content_desc})
    for text in [
        *filter_static_texts(extra.get("clickable_text"), limit=20),
        *filter_static_texts(extra.get("visible_text"), limit=20),
    ]:
        selectors.append({"text": text})
    return _dedupe_selectors(selectors)


def _action_selector_from_point(
    action: dict[str, Any],
    observation: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if str(action.get("action_type") or "").strip() not in {"tap", "long_press", "double_tap"}:
        return None
    if not isinstance(observation, dict):
        return None
    try:
        raw_x = float(action.get("x"))
        raw_y = float(action.get("y"))
    except (TypeError, ValueError):
        return None
    extra = observation.get("extra") if isinstance(observation.get("extra"), dict) else {}
    ui_tree = extra.get("ui_tree")
    if not isinstance(ui_tree, list):
        return None
    bounded_nodes: list[tuple[dict[str, Any], tuple[float, float, float, float]]] = []
    for node in ui_tree:
        if not isinstance(node, dict):
            continue
        bounds = _parse_bounds(node.get("bounds"))
        if bounds is not None:
            bounded_nodes.append((node, bounds))
    if not bounded_nodes:
        return None
    max_right = max(bounds[2] for _, bounds in bounded_nodes)
    max_bottom = max(bounds[3] for _, bounds in bounded_nodes)
    x, y = _point_in_ui_tree_coordinates(
        raw_x,
        raw_y,
        bool(action.get("relative", False)),
        observation=observation,
        max_right=max_right,
        max_bottom=max_bottom,
    )
    matches = [
        (node, bounds)
        for node, bounds in bounded_nodes
        if bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]
    ]
    if not matches:
        return None
    for node, _ in sorted(matches, key=_point_selector_rank):
        selector = _selector_from_action_node(node)
        if selector is not None and selector_is_static(selector):
            return selector
    return None


def _point_in_ui_tree_coordinates(
    x: float,
    y: float,
    relative: bool,
    *,
    observation: dict[str, Any],
    max_right: float,
    max_bottom: float,
) -> tuple[float, float]:
    width = _observation_extent(observation, "screen_width") or max_right
    height = _observation_extent(observation, "screen_height") or max_bottom
    if relative:
        x = x / 999.0 * max(width - 1.0, 1.0)
        y = y / 999.0 * max(height - 1.0, 1.0)
    if width > 0 and max_right > width:
        x *= max_right / width
    if height > 0 and max_bottom > height:
        y *= max_bottom / height
    return x, y


def _observation_extent(observation: dict[str, Any], key: str) -> float:
    value = observation.get(key)
    if value is None and isinstance(observation.get("extra"), dict):
        value = observation["extra"].get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _point_selector_rank(
    item: tuple[dict[str, Any], tuple[float, float, float, float]],
) -> tuple[int, int, float]:
    node, bounds = item
    left, top, right, bottom = bounds
    area = max(0.0, right - left) * max(0.0, bottom - top)
    selector = _selector_from_action_node(node)
    identity_rank = 0 if selector and (selector.get("resource_id") or selector.get("content_desc")) else 1
    clickable_rank = 0 if node.get("clickable") else 1
    return (identity_rank, clickable_rank, area)


def _selector_from_action_node(node: dict[str, Any]) -> dict[str, Any] | None:
    stable = _stable_selector_from_node(node)
    if stable:
        return stable
    selector: dict[str, Any] = {}
    for key in ("resource_id", "content_desc", "text"):
        value = node.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        if key == "text" and is_dynamic_text(value):
            continue
        if key == "resource_id" and is_dynamic_resource_id(value):
            continue
        if key == "content_desc" and not is_static_text(value):
            continue
        if key == "resource_id" and not is_static_resource_id(value):
            continue
        if key == "text" and not is_static_text(value):
            continue
        if value.strip():
            selector[key] = value.strip()
            break
    for flag in ("clickable", "enabled", "focused", "scrollable"):
        if node.get(flag):
            selector[flag] = True
    return selector or None


def _parse_bounds(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            left, top, right, bottom = (float(item) for item in value)
        except (TypeError, ValueError):
            return None
        return (left, top, right, bottom) if right > left and bottom > top else None
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"\[(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)\]"
        r"\[(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)\]",
        value.strip(),
    )
    if match is None:
        return None
    left, top, right, bottom = (float(match.group(index)) for index in range(1, 5))
    return (left, top, right, bottom) if right > left and bottom > top else None


def _stable_selector_from_node(node: dict[str, Any]) -> dict[str, Any] | None:
    selector: dict[str, Any] = {}
    resource_id = _clean_selector_text(node.get("resource_id"))
    content_desc = _clean_selector_text(node.get("content_desc"))
    text = _clean_selector_text(node.get("text"))
    if resource_id and (is_static_resource_id(resource_id) or not is_dynamic_resource_id(resource_id)):
        selector["resource_id"] = resource_id
    elif content_desc and is_static_text(content_desc):
        selector["content_desc"] = content_desc
    elif text and is_static_text(text):
        selector["text"] = text
    else:
        return None
    for flag in ("clickable", "enabled", "focused", "scrollable"):
        if node.get(flag):
            selector[flag] = True
    return selector or None


def _clean_selector_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()


def _target_identity_selector(selectors: list[dict[str, Any]], target: str | None) -> dict[str, Any] | None:
    needle = str(target or "").strip().casefold()
    if not needle:
        return None
    for selector in selectors:
        if not (selector.get("resource_id") or selector.get("content_desc")):
            continue
        values = [
            str(value).casefold()
            for value in (selector.get("text"), selector.get("content_desc"), selector.get("resource_id"))
            if value is not None
        ]
        if any(_value_mentions_target(value, needle) for value in values):
            return selector
    return None


def _text_values_from_selectors(selectors: list[dict[str, Any]], target: str | None) -> list[str]:
    needle = str(target or "").strip().casefold()
    matched: list[str] = []
    rest: list[str] = []
    for selector in selectors:
        text = selector.get("text")
        if not isinstance(text, str) or not text:
            continue
        bucket = matched if needle and _value_mentions_target(text, needle) else rest
        if text not in matched and text not in rest:
            bucket.append(text)
    return [*matched, *rest]


def _step_has_parameterized_input_text(step: SkillStep) -> bool:
    return step.action_type == "input_text" and _is_placeholder_value(step.parameters.get("text"))


def _next_step_has_parameterized_input_text(skill: Skill, index: int) -> bool:
    next_index = index + 1
    if next_index >= len(skill.steps):
        return False
    return _step_has_parameterized_input_text(skill.steps[next_index])


def _dynamic_input_values(trace_step: _TraceStep | None) -> tuple[str, ...]:
    if trace_step is None:
        return ()
    value = trace_step.action.get("text")
    if not isinstance(value, str) or not value.strip():
        return ()
    return (" ".join(value.split()).strip(),)


def _target_state_description(skill: Skill, step: SkillStep, index: int) -> str:
    if step.expected_state:
        return step.expected_state
    description = " ".join((skill.description or "").split()).strip()
    if description:
        target = f" {step.target}" if step.target else ""
        return f"{description} after {step.action_type}{target}".strip()
    return f"{skill.name} step {index} target"


def _retrieval_profile_from_observation(
    observation: dict[str, Any] | None,
    *,
    dynamic_values: tuple[str, ...] = (),
    drop_identity_text: bool = False,
) -> dict[str, Any] | None:
    if not isinstance(observation, dict):
        return None
    extra = observation.get("extra") if isinstance(observation.get("extra"), dict) else {}
    dynamic_value_set = {
        value.casefold()
        for value in dynamic_values
        if value.strip()
    }

    profile: dict[str, Any] = {}
    resource_ids = [
        resource_id
        for resource_id in filter_static_resource_ids(extra.get("resource_ids"), limit=20)
        if not _skip_profile_resource_id(resource_id)
    ]
    if resource_ids:
        profile["resource_ids"] = resource_ids
    stable_controls: list[dict[str, Any]] = []
    for control in filter_static_controls(extra.get("ui_tree"), limit=12):
        cleaned = dict(control)
        resource_id = cleaned.get("resource_id")
        if isinstance(resource_id, str) and _skip_profile_resource_id(resource_id):
            continue
        for key in ("text", "content_desc"):
            value = cleaned.get(key)
            if isinstance(value, str):
                normalized = " ".join(value.split()).strip().casefold()
                if (
                    _matches_dynamic_profile_value(normalized, dynamic_value_set)
                    or (drop_identity_text and cleaned.get("resource_id"))
                ):
                    cleaned.pop(key, None)
        if cleaned.get("resource_id") or cleaned.get("content_desc"):
            stable_controls.append(cleaned)
    if stable_controls:
        profile["stable_controls"] = stable_controls
    platform = observation.get("platform")
    if isinstance(platform, str) and platform.strip():
        profile["platform"] = platform.strip()
    app = observation.get("foreground_app") or observation.get("app")
    if isinstance(app, str) and app.strip():
        profile["foreground_app"] = app.strip()
    return profile or None


def _filter_retrieval_profile_to_contract(
    profile: dict[str, Any] | None,
    contract: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(profile, dict):
        return None
    normalized = normalize_state_contract(contract)
    signature = normalized.get("signature") if isinstance(normalized, dict) else None
    required = signature.get("required") if isinstance(signature, dict) else None
    if not isinstance(required, list):
        return profile
    allowed_resource_ids: set[str] = set()
    allowed_content_desc: set[str] = set()
    allowed_text: set[str] = set()
    for element in required:
        selector = element.get("selector") if isinstance(element, dict) else None
        if not isinstance(selector, dict):
            continue
        for key, bucket in (
            ("resource_id", allowed_resource_ids),
            ("content_desc", allowed_content_desc),
            ("text", allowed_text),
        ):
            value = selector.get(key)
            if isinstance(value, str) and value.strip():
                bucket.add(value.strip())
    if not (allowed_resource_ids or allowed_content_desc or allowed_text):
        return profile
    filtered: dict[str, Any] = {}
    resource_ids = [
        value
        for value in profile.get("resource_ids", [])
        if isinstance(value, str) and value in allowed_resource_ids
    ]
    if resource_ids:
        filtered["resource_ids"] = resource_ids
    stable_controls: list[dict[str, Any]] = []
    for control in profile.get("stable_controls", []):
        if not isinstance(control, dict):
            continue
        resource_id = control.get("resource_id")
        content_desc = control.get("content_desc")
        text = control.get("text")
        if (
            (isinstance(resource_id, str) and resource_id in allowed_resource_ids)
            or (isinstance(content_desc, str) and content_desc in allowed_content_desc)
            or (isinstance(text, str) and text in allowed_text and not resource_id)
        ):
            stable_controls.append(control)
    if stable_controls:
        filtered["stable_controls"] = stable_controls
    for key in ("foreground_app", "platform"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            filtered[key] = value
    return filtered or None


def _skip_profile_resource_id(resource_id: str) -> bool:
    lowered = resource_id.casefold()
    return "appbar_title" in lowered or "toolbar_title" in lowered or "titlebar" in lowered


def _matches_dynamic_profile_value(value: str, dynamic_values: set[str]) -> bool:
    if not value or not dynamic_values:
        return False
    return any(value == dynamic or dynamic in value or value in dynamic for dynamic in dynamic_values)


def _is_placeholder_value(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"\{\{[A-Za-z_]\w*\}\}", value.strip()) is not None


def _strip_dynamic_selector_text_from_contract(
    contract: dict[str, Any] | None,
    *,
    dynamic_values: tuple[str, ...] = (),
    drop_identity_text: bool = False,
) -> dict[str, Any] | None:
    normalized = normalize_state_contract(contract)
    if not normalized:
        return normalized
    signature = normalized.get("signature")
    required = signature.get("required") if isinstance(signature, dict) else None
    if not isinstance(required, list):
        return normalized
    dynamic_value_set = {
        value.casefold()
        for value in dynamic_values
        if value.strip()
    }
    changed = False
    sanitized_required: list[Any] = []
    for element in required:
        if not isinstance(element, dict):
            sanitized_required.append(element)
            continue
        selector = element.get("selector")
        if not isinstance(selector, dict):
            sanitized_required.append(element)
            continue
        updated_selector = dict(selector)
        if (
            drop_identity_text
            and "text" in updated_selector
            and (updated_selector.get("resource_id") or updated_selector.get("content_desc"))
        ):
            updated_selector.pop("text", None)
            changed = True
        for key in ("text", "content_desc"):
            value = updated_selector.get(key)
            if (
                isinstance(value, str)
                and dynamic_value_set
                and " ".join(value.split()).strip().casefold() in dynamic_value_set
            ):
                updated_selector.pop(key, None)
                changed = True
        if updated_selector == selector:
            sanitized_required.append(element)
            continue
        if not any(updated_selector.get(key) for key in ("resource_id", "content_desc", "text", "class", "xpath")):
            continue
        updated = dict(element)
        updated["selector"] = updated_selector
        sanitized_required.append(updated)
    if not changed:
        return normalized
    sanitized = dict(normalized)
    sanitized_signature = dict(signature)
    sanitized_signature["required"] = sanitized_required
    sanitized["signature"] = sanitized_signature
    return normalize_state_contract(sanitized)


def _graph_source_block(states: list[_StateSpec], transitions: list[_TransitionSpec]) -> str:
    lines: list[str] = []
    for state in states:
        lines.append(
            "@state("
            f"app={_code_literal(state.app)}, "
            f"platform={_code_literal(state.platform)}, "
            f"node_id={_code_literal(state.node_id)}, "
            f"description={_code_literal(state.description)}, "
            f"skill_ids={_code_literal([state.skill_id])}"
            + (
                f", retrieval_profile={_code_literal(state.retrieval_profile)}"
                if state.retrieval_profile
                else ""
            )
            + ")"
        )
        lines.append(f"def {state.function_name}():")
        lines.append(f"    return C.from_dict({_code_literal(state.contract)})")
        lines.append("")
        lines.append("")
    used_transition_names: set[str] = set()
    for transition in transitions:
        func_name = _dedupe_name(transition.function_name, used_transition_names)
        used_transition_names.add(func_name)
        lines.append(
            "@transition("
            f"src={transition.src.function_name}, "
            f"dst={transition.dst.function_name}, "
            f"edge_id={_code_literal(transition.edge_id)}, "
            f"skill_id={_code_literal(transition.skill_id)}"
            ")"
        )
        lines.append(f"async def {func_name}(device):")
        parts = [
            _code_literal(transition.step.action_type),
            f"target={_code_literal(transition.step.target)}",
        ]
        if transition.step.parameters:
            parts.append(f"parameters={_code_literal(transition.step.parameters)}")
        parts.append(f"state_contract=C.from_dict({_code_literal(transition.src.contract)})")
        lines.append(f"    await action({', '.join(parts)})")
        lines.append("")
        lines.append("")
    return "\n".join(lines).rstrip()


def _is_canonical_contract(contract: Any) -> bool:
    normalized = normalize_state_contract(contract)
    if not normalized:
        return False
    anchor = normalized.get("anchor")
    if not isinstance(anchor, dict) or not anchor.get("app_package"):
        return False
    signature = normalized.get("signature")
    required = signature.get("required") if isinstance(signature, dict) else None
    if not isinstance(required, list):
        return False
    for element in required:
        selector = element.get("selector") if isinstance(element, dict) else None
        if not isinstance(selector, dict):
            continue
        if _selector_is_input_identity(selector, element):
            return True
        if not selector_is_static(selector):
            continue
        if selector.get("resource_id") or selector.get("content_desc"):
            return True
        if any(
            _clean_selector_value(selector.get(key))
            for key in ("text", "class", "xpath")
        ):
            return True
    return False


def _is_strong_canonical_contract(contract: Any) -> bool:
    normalized = normalize_state_contract(contract)
    if not normalized:
        return False
    anchor = normalized.get("anchor")
    if not isinstance(anchor, dict) or not anchor.get("app_package"):
        return False
    signature = normalized.get("signature")
    required = signature.get("required") if isinstance(signature, dict) else None
    if not isinstance(required, list):
        return False
    text_selectors: set[str] = set()
    for element in required:
        selector = element.get("selector") if isinstance(element, dict) else None
        if not isinstance(selector, dict):
            continue
        if _selector_is_input_identity(selector, element):
            return True
        if not selector_is_static(selector):
            continue
        if selector.get("resource_id") or selector.get("content_desc"):
            return True
        text = _clean_selector_value(selector.get("text"))
        if text:
            text_selectors.add(text)
    return len(text_selectors) >= 2


def _selector_is_input_identity(selector: dict[str, Any], element: dict[str, Any]) -> bool:
    selector_class = str(selector.get("class") or "").casefold()
    state = element.get("state") if isinstance(element.get("state"), list) else []
    return bool(
        selector.get("resource_id")
        and ("edittext" in selector_class or "input" in selector_class)
        and any(item in state for item in ("focused", "enabled", "clickable"))
    )


def _clean_selector_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _contract_app_matches(contract: dict[str, Any], *, app: str, platform: str) -> bool:
    anchor = contract.get("anchor") if isinstance(contract.get("anchor"), dict) else {}
    anchor_app = str(anchor.get("app_package") or anchor.get("app") or "").strip()
    if not anchor_app or not app:
        return True
    left = normalize_app_identifier(platform or "", anchor_app)
    right = normalize_app_identifier(platform or "", app)
    return bool(left and right and left != "unknown" and right != "unknown" and left == right)


def _trace_step_crosses_app(trace_step: _TraceStep | None, *, app: str, platform: str) -> bool:
    if trace_step is None or not isinstance(trace_step.post_observation, dict):
        return False
    actual_app = str(
        trace_step.post_observation.get("foreground_app")
        or trace_step.post_observation.get("app")
        or ""
    ).strip()
    if not actual_app or not app:
        return False
    left = normalize_app_identifier(platform or "", actual_app)
    right = normalize_app_identifier(platform or "", app)
    return bool(left and right and left != "unknown" and right != "unknown" and left != right)


def _trace_text_blob(event: dict[str, Any], action: dict[str, Any]) -> str:
    parts: list[str] = []
    for value in (
        action.get("target"),
        action.get("text"),
        event.get("target"),
        event.get("action_summary"),
        event.get("summary"),
        event.get("model_output"),
    ):
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts).casefold()


def _observation_mentions(observation: dict[str, Any] | None, target: str) -> bool:
    if not isinstance(observation, dict):
        return False
    extra = observation.get("extra") if isinstance(observation.get("extra"), dict) else {}
    values: list[str] = []
    for key in ("visible_text", "clickable_text", "content_desc", "resource_ids"):
        raw = extra.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw if item is not None)
    ui_tree = extra.get("ui_tree")
    if isinstance(ui_tree, list):
        for node in ui_tree:
            if isinstance(node, dict):
                values.extend(
                    str(value)
                    for value in (node.get("text"), node.get("content_desc"), node.get("resource_id"))
                    if value is not None
                )
    return any(_value_mentions_target(value, target) for value in values)


def _selector_mentions_target(selector: dict[str, Any] | None, target: str) -> bool:
    if not isinstance(selector, dict):
        return False
    return any(
        _value_mentions_target(str(value), target)
        for value in (
            selector.get("text"),
            selector.get("content_desc"),
            selector.get("resource_id"),
        )
        if value is not None
    )


def _step_coordinates_match_trace_action(step: SkillStep, action: dict[str, Any]) -> bool:
    if step.action_type not in {"tap", "long_press", "double_tap", "drag", "swipe"}:
        return False
    if "x" not in step.parameters or "y" not in step.parameters:
        return False
    try:
        step_x = float(step.parameters.get("x"))
        step_y = float(step.parameters.get("y"))
        action_x = float(action.get("x"))
        action_y = float(action.get("y"))
    except (TypeError, ValueError):
        return False
    if abs(step_x - action_x) > 1e-3 or abs(step_y - action_y) > 1e-3:
        return False
    if "relative" in step.parameters and bool(step.parameters.get("relative")) != bool(action.get("relative", False)):
        return False
    for key in ("x2", "y2"):
        if key not in step.parameters:
            continue
        try:
            step_value = float(step.parameters.get(key))
            action_value = float(action.get(key))
        except (TypeError, ValueError):
            return False
        if abs(step_value - action_value) > 1e-3:
            return False
    return True


def _blob_mentions_target(blob: str, target: str) -> bool:
    needle = target.strip().casefold()
    if not needle:
        return False
    blob = blob.casefold()
    if any(line.strip() == needle for line in blob.splitlines()):
        return True
    quoted = (f'"{needle}"', f"'{needle}'", f"“{needle}”", f"‘{needle}’")
    if any(mark in blob for mark in quoted):
        return True
    return len(needle) > 1 and needle in blob


def _value_mentions_target(value: str, target: str) -> bool:
    value_clean = value.strip().casefold()
    needle = target.strip().casefold()
    if not value_clean or not needle:
        return False
    if value_clean == needle:
        return True
    return len(needle) > 1 and needle in value_clean


def _selector_without_state_flags(selector: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in selector.items()
        if key in {"text", "content_desc", "resource_id", "class", "xpath"}
    }


def _selector_states(selector: dict[str, Any]) -> list[str]:
    states = ["visible"]
    if selector.get("clickable"):
        states.append("clickable")
    if selector.get("enabled"):
        states.append("enabled")
    if selector.get("focused"):
        states.append("focused")
    if selector.get("scrollable"):
        states.append("scrollable")
    return states


def _dedupe_selectors(selectors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for selector in selectors:
        key = json.dumps(selector, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        out.append(selector)
    return out


def _skip_record(skill: Skill, step: SkillStep, index: int, reason: str) -> dict[str, Any]:
    return {
        "skill_id": skill.skill_id,
        "function": skill.name,
        "step_index": index,
        "action_type": step.action_type,
        "target": step.target,
        "reason": reason,
    }


def _state_record(state: _StateSpec) -> dict[str, Any]:
    return {
        "function": state.function_name,
        "node_id": state.node_id,
        "description": state.description,
        "step_index": state.step_index,
        "role": state.role,
    }


def _transition_record(transition: _TransitionSpec) -> dict[str, Any]:
    return {
        "function": transition.function_name,
        "edge_id": transition.edge_id,
        "skill_id": transition.skill_id,
        "step_index": transition.step_index,
        "action_type": transition.step.action_type,
        "target": transition.step.target,
        "src": transition.src.function_name,
        "dst": transition.dst.function_name,
    }


def _ensure_graph_imports(source: str) -> str:
    if "from opengui.skills.code_graph import" not in source:
        return _CODE_HEADER + "\n\n" + source
    return re.sub(
        r"from opengui\.skills\.code_graph import .+",
        _CODE_HEADER,
        source,
        count=1,
    )


def _strip_graph_declarations_for_skills(source: str, skill_names: set[str]) -> str:
    if not skill_names:
        return source
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    lines = source.splitlines()
    remove_lines: set[int] = set()
    for node in tree.body:
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if not (_has_decorator(node, "state") or _has_decorator(node, "transition")):
            continue
        starts = [node.lineno, *(decorator.lineno for decorator in node.decorator_list)]
        start = min(starts) - 1
        end = node.end_lineno or node.lineno
        segment = "\n".join(lines[start:end])
        if not _graph_declaration_belongs_to_skill(node.name, segment, skill_names):
            continue
        remove_lines.update(range(start, end))
    if not remove_lines:
        return source
    return "\n".join(
        line
        for index, line in enumerate(lines)
        if index not in remove_lines
    ).strip() + "\n"


def _has_decorator(func: ast.AsyncFunctionDef | ast.FunctionDef, name: str) -> bool:
    return any(
        (
            isinstance(decorator, ast.Call)
            and (
                (isinstance(decorator.func, ast.Name) and decorator.func.id == name)
                or (isinstance(decorator.func, ast.Attribute) and decorator.func.attr == name)
            )
        )
        or (isinstance(decorator, ast.Name) and decorator.id == name)
        for decorator in func.decorator_list
    )


def _graph_declaration_belongs_to_skill(
    function_name: str,
    source_segment: str,
    skill_names: set[str],
) -> bool:
    for skill_name in skill_names:
        if function_name.startswith((f"state_{skill_name}_", f"transition_{skill_name}_")):
            return True
        if f"code:{skill_name}" in source_segment:
            return True
    return False


def _safe_identifier(value: str) -> str:
    clean = re.sub(r"[^0-9A-Za-z_]+", "_", value).strip("_").lower()
    if not clean:
        clean = "graph_item"
    if clean[0].isdigit():
        clean = f"_{clean}"
    return clean


def _dedupe_name(base: str, used: set[str]) -> str:
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    return candidate


def _hash_key(*parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _code_literal(value: Any) -> str:
    return pprint.pformat(value, width=100, sort_dicts=True)


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _strip_code_fences(code: str) -> str:
    code = code.strip()
    for fence in ("```python3", "```python", "```"):
        code = code.replace(fence, "")
    return code.strip()
