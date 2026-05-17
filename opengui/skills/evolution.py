"""
opengui.skills.evolution
~~~~~~~~~~~~~~~~~~~~~~~~
Failure-grounded evolution for code-first GUI skills.

This module handles only reuse failures.  It does not run general skill
extraction and it never asks an LLM to rewrite the whole skill graph source.
It records the failed example, applies small deterministic patches when the
trace evidence proves the patch, and otherwise quarantines the candidate.
"""

from __future__ import annotations

import ast
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from opengui.skills.code_graph import compile_code_skills
from opengui.skills.state_contract import (
    evaluate_state_contract,
    infer_state_contract,
    normalize_state_contract,
)

EVOLUTION_DIRNAME = "evolution"
FEEDBACK_FILENAME = "skill_feedback.json"
FAILURE_CASES_FILENAME = "failure_cases.jsonl"

_ENTRY_ACTIONS = frozenset({"open_app", "open_deeplink", "open_intent"})
_REUSABLE_GAP_ACTIONS = frozenset({
    "tap",
    "long_press",
    "double_tap",
    "input_text",
    "swipe",
    "scroll",
    "back",
    "enter",
})
_VOLATILE_STATE_FLAGS = frozenset({"clickable", "enabled", "focused"})


@dataclass
class SkillFailureCase:
    trace: str
    task: str
    platform: str
    skill_id: str
    skill_name: str
    failed_step_index: int
    failed_action_type: str
    failed_target: str
    failed_state_contract: dict[str, Any] | None
    failure_observation: dict[str, Any] | None
    failure_screenshot_path: str | None
    contract_eval_detail: dict[str, Any] | None
    fallback_actions: list[dict[str, Any]] = field(default_factory=list)
    deeplink: dict[str, Any] | None = None


@dataclass
class EvolutionDecision:
    decision_type: str
    skill_id: str | None = None
    promoted: bool = False
    reason: str = ""
    updated_functions: list[str] = field(default_factory=list)
    preferred_skill_ids: list[str] = field(default_factory=list)
    quarantine_path: str | None = None
    errors: list[str] = field(default_factory=list)


def load_skill_feedback(store_root: Path) -> dict[str, Any]:
    path = Path(store_root).expanduser() / FEEDBACK_FILENAME
    try:
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                loaded.setdefault("version", 1)
                loaded.setdefault("skills", {})
                return loaded
    except (json.JSONDecodeError, OSError):
        pass
    return {"version": 1, "skills": {}}


def feedback_for_skill(store_root: Path, skill_id: str) -> dict[str, Any]:
    feedback = load_skill_feedback(store_root)
    skills = feedback.get("skills") if isinstance(feedback.get("skills"), dict) else {}
    value = skills.get(skill_id)
    return dict(value) if isinstance(value, dict) else {}


def feedback_task_similarity(query: str, examples: Any) -> float:
    if not isinstance(examples, list):
        return 0.0
    query_norm = _normalize_task(query)
    if not query_norm:
        return 0.0
    best = 0.0
    for example in examples:
        example_norm = _normalize_task(str(example or ""))
        if not example_norm:
            continue
        if query_norm == example_norm:
            return 1.0
        if query_norm in example_norm or example_norm in query_norm:
            best = max(best, 0.9)
            continue
        left = set(query_norm.split())
        right = set(example_norm.split())
        if left and right:
            best = max(best, len(left & right) / max(1, min(len(left), len(right))))
    return best


def feedback_summary_for_prompt(feedback: dict[str, Any]) -> str:
    parts: list[str] = []
    positives = [str(v) for v in feedback.get("positive_tasks", []) if str(v).strip()]
    negatives = [str(v) for v in feedback.get("negative_tasks", []) if str(v).strip()]
    preferred = [str(v) for v in feedback.get("preferred_for_tasks", []) if str(v).strip()]
    if positives:
        parts.append("positive_tasks=" + "; ".join(positives[:3]))
    if negatives:
        parts.append("negative_tasks=" + "; ".join(negatives[:3]))
    if preferred:
        parts.append("preferred_for_tasks=" + "; ".join(preferred[:3]))
    failure_counts = feedback.get("failure_counts")
    if isinstance(failure_counts, dict) and failure_counts:
        parts.append(
            "failure_counts="
            + ", ".join(f"{key}:{value}" for key, value in sorted(failure_counts.items())[:4])
        )
    return " | ".join(parts)


class SkillEvolutionEngine:
    def __init__(self, store_root: Path) -> None:
        self.store_root = Path(store_root).expanduser()
        self.source_path = self.store_root / "skill_graph_code.py"
        self.evolution_dir = self.store_root / EVOLUTION_DIRNAME

    def evolve_trace(
        self,
        trace_path: Path,
        *,
        task: str | None = None,
        platform: str = "unknown",
    ) -> dict[str, Any]:
        events = _load_jsonl(trace_path)
        failure_case = _build_failure_case(
            events,
            trace_path=trace_path,
            task=task,
            platform=platform,
        )
        if failure_case is None:
            return {
                "status": "no_failure_case",
                "trace": str(trace_path),
                "decisions": [],
                "updated_functions": [],
                "compiled_skill_ids": [],
            }

        self.evolution_dir.mkdir(parents=True, exist_ok=True)
        self._append_failure_case(failure_case)
        decisions: list[EvolutionDecision] = []

        intent_decision = self._prefer_verified_intent(failure_case)
        if intent_decision is not None:
            decisions.append(intent_decision)

        if _task_skill_conflict(failure_case.task, failure_case.skill_name):
            self._record_feedback(
                failure_case.skill_id,
                negative_task=failure_case.task,
                failure_reason="wrong_skill_selected",
            )
            decisions.append(EvolutionDecision(
                decision_type="negative_selection_feedback",
                skill_id=failure_case.skill_id,
                promoted=True,
                reason="task_skill_semantic_conflict",
            ))
        else:
            gap_decision = self._try_insert_missing_action_gap(failure_case)
            if gap_decision is not None:
                decisions.append(gap_decision)
            if not any(decision.promoted for decision in decisions):
                downgrade_decision = self._try_contract_downgrade(failure_case)
                if downgrade_decision is not None:
                    decisions.append(downgrade_decision)

        if not decisions:
            decisions.append(self._quarantine(
                failure_case,
                decision_type="quarantine",
                reason="no_deterministic_patch",
                payload={"failure_case": asdict(failure_case)},
            ))
            self._record_feedback(
                failure_case.skill_id,
                negative_task=failure_case.task,
                failure_reason="unpatched_reuse_failure",
            )

        compiled = compile_code_skills(self.source_path.read_text(encoding="utf-8")) if self.source_path.exists() else None
        compiled_skill_ids = [
            skill.skill_id for skill in compiled.skills
        ] if compiled is not None and not compiled.errors else []
        updated_functions: list[str] = []
        for decision in decisions:
            for name in decision.updated_functions:
                if name not in updated_functions:
                    updated_functions.append(name)
        return {
            "status": "processed_evolution",
            "trace": str(trace_path),
            "failure_case": asdict(failure_case),
            "decisions": [asdict(decision) for decision in decisions],
            "updated_functions": updated_functions,
            "compiled_skill_ids": compiled_skill_ids,
            "compile_errors": compiled.errors if compiled is not None else [],
        }

    def _prefer_verified_intent(self, failure_case: SkillFailureCase) -> EvolutionDecision | None:
        deeplink = failure_case.deeplink
        if not isinstance(deeplink, dict) or deeplink.get("status") != "processed_deeplink_code":
            return None
        candidate_kinds = {
            str(candidate.get("kind") or "")
            for candidate in deeplink.get("candidates") or []
            if isinstance(candidate, dict)
        }
        if candidate_kinds and not (
            candidate_kinds
            & {"shortcut_intent", "uri_deeplink", "deeplink", "manifest_deeplink", "router_payload"}
        ):
            return None
        updated_functions = [
            str(name)
            for name in deeplink.get("updated_functions") or []
            if str(name).strip()
        ]
        preferred = self._preferred_skill_ids_for_updated_functions(updated_functions)
        compiled_ids = [
            str(skill_id)
            for skill_id in deeplink.get("compiled_skill_ids") or []
            if str(skill_id).strip()
        ]
        if not preferred and not updated_functions:
            preferred = [
                skill_id
                for skill_id in compiled_ids
                if skill_id.startswith(("intent:", "deeplink:"))
            ]
        if not preferred:
            preferred = [
                str(skill_id)
                for skill_id in updated_functions
                if str(skill_id).startswith(("intent:", "deeplink:"))
            ]
        if not preferred:
            return None
        for skill_id in preferred:
            self._record_feedback(skill_id, preferred_task=failure_case.task)
        self._record_feedback(
            failure_case.skill_id,
            negative_task=failure_case.task,
            failure_reason="prefer_verified_intent",
        )
        return EvolutionDecision(
            decision_type="prefer_verified_intent",
            skill_id=failure_case.skill_id,
            promoted=True,
            reason="verified_intent_available",
            preferred_skill_ids=preferred,
        )

    def _preferred_skill_ids_for_updated_functions(self, updated_functions: list[str]) -> list[str]:
        if not updated_functions or not self.source_path.exists():
            return []
        try:
            compiled = compile_code_skills(self.source_path.read_text(encoding="utf-8"))
        except OSError:
            return []
        if compiled.errors:
            return []
        by_name = {skill.name: skill.skill_id for skill in compiled.skills if skill.skill_id}
        preferred: list[str] = []
        for name in updated_functions:
            skill_id = by_name.get(name)
            if skill_id and skill_id.startswith(("intent:", "deeplink:")) and skill_id not in preferred:
                preferred.append(skill_id)
        return preferred

    def _try_contract_downgrade(self, failure_case: SkillFailureCase) -> EvolutionDecision | None:
        if not failure_case.failed_state_contract or not failure_case.failure_observation:
            return None
        downgraded = _downgrade_contract(
            failure_case.failed_state_contract,
            failure_case.contract_eval_detail,
            target=failure_case.failed_target,
        )
        if not downgraded:
            return self._quarantine(
                failure_case,
                decision_type="contract_downgrade",
                reason="no_stable_target_selector_to_keep",
                payload={"candidate_contract": downgraded},
            )
        if evaluate_state_contract(downgraded, observation=failure_case.failure_observation) is not True:
            return self._quarantine(
                failure_case,
                decision_type="contract_downgrade",
                reason="downgraded_contract_does_not_match_failure_observation",
                payload={"candidate_contract": downgraded},
            )
        source = self.source_path.read_text(encoding="utf-8") if self.source_path.exists() else ""
        patched = _patch_step_contract(
            source,
            skill_id=failure_case.skill_id,
            step_index=failure_case.failed_step_index,
            contract=downgraded,
        )
        if patched is None:
            return self._quarantine(
                failure_case,
                decision_type="contract_downgrade",
                reason="skill_or_step_not_found",
                payload={"candidate_contract": downgraded},
            )
        compile_result = compile_code_skills(patched)
        if compile_result.errors:
            return self._quarantine(
                failure_case,
                decision_type="contract_downgrade",
                reason="compile_failed",
                payload={"candidate_contract": downgraded, "errors": compile_result.errors},
            )
        self._write_source(patched)
        self._record_feedback(failure_case.skill_id, positive_task=failure_case.task)
        return EvolutionDecision(
            decision_type="contract_downgrade",
            skill_id=failure_case.skill_id,
            promoted=True,
            reason="downgraded_contract_matches_failure_observation",
            updated_functions=[_function_name_from_skill_id(failure_case.skill_id)],
        )

    def _try_insert_missing_action_gap(self, failure_case: SkillFailureCase) -> EvolutionDecision | None:
        if not failure_case.failed_state_contract or not failure_case.fallback_actions:
            return None
        gap_events, target_observation = _find_gap_actions_for_contract(
            failure_case.failed_state_contract,
            failure_case.fallback_actions,
            start_observation=failure_case.failure_observation,
            app=_contract_app(failure_case.failed_state_contract) or "",
        )
        if not gap_events:
            return None
        if evaluate_state_contract(
            failure_case.failed_state_contract,
            observation=target_observation,
        ) is not True:
            return None
        source = self.source_path.read_text(encoding="utf-8") if self.source_path.exists() else ""
        patched = _patch_insert_actions(
            source,
            skill_id=failure_case.skill_id,
            before_step_index=failure_case.failed_step_index,
            events=gap_events,
            app=_contract_app(failure_case.failed_state_contract) or "",
        )
        if patched is None:
            return self._quarantine(
                failure_case,
                decision_type="insert_missing_action_gap",
                reason="skill_or_step_not_found",
                payload={"gap_events": gap_events},
            )
        compile_result = compile_code_skills(patched)
        if compile_result.errors:
            return self._quarantine(
                failure_case,
                decision_type="insert_missing_action_gap",
                reason="compile_failed",
                payload={"gap_events": gap_events, "errors": compile_result.errors},
            )
        self._write_source(patched)
        self._record_feedback(failure_case.skill_id, positive_task=failure_case.task)
        return EvolutionDecision(
            decision_type="insert_missing_action_gap",
            skill_id=failure_case.skill_id,
            promoted=True,
            reason="gap_actions_make_failed_contract_reachable",
            updated_functions=[_function_name_from_skill_id(failure_case.skill_id)],
        )

    def _append_failure_case(self, failure_case: SkillFailureCase) -> None:
        path = self.evolution_dir / FAILURE_CASES_FILENAME
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(failure_case), ensure_ascii=False) + "\n")

    def _record_feedback(
        self,
        skill_id: str,
        *,
        positive_task: str | None = None,
        negative_task: str | None = None,
        preferred_task: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        feedback = load_skill_feedback(self.store_root)
        skills = feedback.setdefault("skills", {})
        record = skills.setdefault(skill_id, {})
        record.setdefault("positive_tasks", [])
        record.setdefault("negative_tasks", [])
        record.setdefault("preferred_for_tasks", [])
        record.setdefault("failure_counts", {})
        _append_unique(record["positive_tasks"], positive_task)
        _append_unique(record["negative_tasks"], negative_task)
        _append_unique(record["preferred_for_tasks"], preferred_task)
        if failure_reason:
            counts = record["failure_counts"]
            counts[failure_reason] = int(counts.get(failure_reason, 0)) + 1
        record["updated_at"] = time.time()
        self._write_json_atomic(self.store_root / FEEDBACK_FILENAME, feedback)

    def _quarantine(
        self,
        failure_case: SkillFailureCase,
        *,
        decision_type: str,
        reason: str,
        payload: dict[str, Any],
    ) -> EvolutionDecision:
        quarantine_dir = self.evolution_dir / "quarantine"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        safe_skill = re.sub(r"[^A-Za-z0-9_.-]+", "_", failure_case.skill_id)
        path = quarantine_dir / f"{int(time.time() * 1000)}_{safe_skill}.json"
        data = {
            "decision_type": decision_type,
            "reason": reason,
            "failure_case": asdict(failure_case),
            **payload,
        }
        self._write_json_atomic(path, data)
        return EvolutionDecision(
            decision_type=decision_type,
            skill_id=failure_case.skill_id,
            promoted=False,
            reason=reason,
            quarantine_path=str(path),
        )

    def _write_source(self, source: str) -> None:
        self.source_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.source_path.with_suffix(self.source_path.suffix + ".tmp")
        tmp.write_text(source, encoding="utf-8")
        os.replace(tmp, self.source_path)

    @staticmethod
    def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for raw in handle:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    value = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    events.append(value)
    except OSError:
        return []
    return events


def _build_failure_case(
    events: list[dict[str, Any]],
    *,
    trace_path: Path,
    task: str | None,
    platform: str,
) -> SkillFailureCase | None:
    failed_result_index: int | None = None
    failed_result: dict[str, Any] | None = None
    for index, event in enumerate(events):
        if event.get("type") == "skill_execution_result" and event.get("state") == "failed":
            failed_result_index = index
            failed_result = event
            break
    if failed_result_index is None or failed_result is None:
        return None

    failed_skill_id = str(failed_result.get("skill_id") or "")
    candidate_steps = [
        event for event in events[:failed_result_index + 1]
        if event.get("type") == "skill_step"
        and (not failed_skill_id or str(event.get("skill_id") or "") == failed_skill_id)
        and (
            event.get("error")
            or event.get("valid_state_check") is False
            or (
                isinstance(event.get("contract_eval_detail"), dict)
                and event["contract_eval_detail"].get("passed") is False
            )
        )
    ]
    failed_step = candidate_steps[-1] if candidate_steps else None
    if failed_step is None:
        return None

    metadata = next((event for event in events if event.get("type") == "metadata"), {})
    fallback_actions = [
        event for event in events[failed_result_index + 1:]
        if event.get("type") == "step" and isinstance(event.get("action"), dict)
    ]
    deeplink = _load_sibling_json(trace_path, "deeplink_result.json")
    return SkillFailureCase(
        trace=str(trace_path),
        task=str(task or metadata.get("task") or ""),
        platform=str(platform or metadata.get("platform") or ""),
        skill_id=str(failed_step.get("skill_id") or failed_result.get("skill_id") or ""),
        skill_name=str(failed_step.get("skill_name") or failed_result.get("skill_name") or ""),
        failed_step_index=int(failed_step.get("step_index") or 0),
        failed_action_type=str((failed_step.get("action") or {}).get("action_type") or ""),
        failed_target=str(failed_step.get("target") or ""),
        failed_state_contract=normalize_state_contract(failed_step.get("state_contract")),
        failure_observation=failed_step.get("observation") if isinstance(failed_step.get("observation"), dict) else None,
        failure_screenshot_path=failed_step.get("screenshot_path") if isinstance(failed_step.get("screenshot_path"), str) else None,
        contract_eval_detail=failed_step.get("contract_eval_detail") if isinstance(failed_step.get("contract_eval_detail"), dict) else None,
        fallback_actions=fallback_actions,
        deeplink=deeplink if isinstance(deeplink, dict) else None,
    )


def _load_sibling_json(trace_path: Path, name: str) -> dict[str, Any] | None:
    path = trace_path.parent / name
    try:
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else None
    except (json.JSONDecodeError, OSError):
        return None
    return None


def _downgrade_contract(
    contract: dict[str, Any],
    detail: dict[str, Any] | None,
    *,
    target: str,
) -> dict[str, Any] | None:
    normalized = normalize_state_contract(contract)
    if not normalized:
        return None
    required = list(normalized.get("signature", {}).get("required", []) or [])
    target_norm = _normalize_task(target)
    keep: list[dict[str, Any]] = []

    for element in required:
        selector = element.get("selector") if isinstance(element.get("selector"), dict) else {}
        selector_text = _selector_text(selector)
        if target_norm and selector_text and (
            target_norm == _normalize_task(selector_text)
            or target_norm in _normalize_task(selector_text)
            or _normalize_task(selector_text) in target_norm
        ):
            keep.append(_strip_volatile_flags(element))

    if not keep and isinstance(detail, dict):
        for matched in detail.get("matched_required", []) or []:
            element = matched.get("element") if isinstance(matched, dict) else None
            if isinstance(element, dict) and element.get("selector"):
                keep.append(_strip_volatile_flags(element))

    keep = _dedupe_required(keep)
    if not keep:
        return None
    return normalize_state_contract({
        "anchor": dict(normalized.get("anchor", {})),
        "signature": {"required": keep, "forbidden": []},
        "mask_rules": list(normalized.get("mask_rules", []) or []),
    })


def _find_gap_actions_for_contract(
    contract: dict[str, Any],
    fallback_actions: list[dict[str, Any]],
    *,
    start_observation: dict[str, Any] | None,
    app: str,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    reusable: list[dict[str, Any]] = []
    pre_observation = start_observation
    for event in fallback_actions:
        raw_action = event.get("action") if isinstance(event.get("action"), dict) else {}
        action_type = str(raw_action.get("action_type") or raw_action.get("type") or "")
        post_observation = event.get("observation") if isinstance(event.get("observation"), dict) else None
        if action_type in _REUSABLE_GAP_ACTIONS:
            event_with_precondition = dict(event)
            if isinstance(pre_observation, dict):
                event_with_precondition["observation"] = pre_observation
            if _event_contract(event_with_precondition, app=app) is not None:
                reusable.append(event_with_precondition)
        if isinstance(post_observation, dict) and evaluate_state_contract(contract, observation=post_observation) is True:
            return reusable[-3:], post_observation
        if isinstance(post_observation, dict):
            pre_observation = post_observation
    return [], None


def _patch_step_contract(
    source: str,
    *,
    skill_id: str,
    step_index: int,
    contract: dict[str, Any],
) -> str | None:
    tree = ast.parse(source)
    func = _find_skill_function(tree, skill_id)
    if func is None:
        return None
    action_stmts = _direct_action_stmts(func)
    if not (0 <= step_index < len(action_stmts)):
        return None
    call = action_stmts[step_index][1]
    _set_keyword(call, "state_contract", _contract_expr(contract))
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def _patch_insert_actions(
    source: str,
    *,
    skill_id: str,
    before_step_index: int,
    events: list[dict[str, Any]],
    app: str,
) -> str | None:
    tree = ast.parse(source)
    func = _find_skill_function(tree, skill_id)
    if func is None:
        return None
    action_stmts = _direct_action_stmts(func)
    if not (0 <= before_step_index <= len(action_stmts)):
        return None
    insert_at = func.body.index(action_stmts[before_step_index][0]) if before_step_index < len(action_stmts) else len(func.body)
    stmts: list[ast.stmt] = []
    for event in events:
        stmt = _action_stmt_from_event(event, app=app)
        if stmt is not None:
            stmts.append(stmt)
    if not stmts:
        return None
    func.body[insert_at:insert_at] = stmts
    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def _action_stmt_from_event(event: dict[str, Any], *, app: str) -> ast.stmt | None:
    raw_action = event.get("action") if isinstance(event.get("action"), dict) else {}
    action_type = str(raw_action.get("action_type") or raw_action.get("type") or "")
    if action_type not in _REUSABLE_GAP_ACTIONS:
        return None
    contract = _event_contract(event, app=app)
    if contract is None:
        return None
    keywords: list[ast.keyword] = []
    target = _event_target(event)
    if target:
        keywords.append(ast.keyword(arg="target", value=ast.Constant(value=target)))
    for key in ("x", "y", "x2", "y2", "text", "duration_ms"):
        value = raw_action.get(key)
        if value is not None:
            keywords.append(ast.keyword(arg=key, value=ast.Constant(value=value)))
    if raw_action.get("relative") is True:
        keywords.append(ast.keyword(arg="relative", value=ast.Constant(value=True)))
    keywords.append(ast.keyword(arg="state_contract", value=_contract_expr(contract)))
    return ast.Expr(value=ast.Await(value=ast.Call(
        func=ast.Name(id="action", ctx=ast.Load()),
        args=[ast.Constant(value=action_type)],
        keywords=keywords,
    )))


def _event_contract(event: dict[str, Any], *, app: str) -> dict[str, Any] | None:
    raw_action = event.get("action") if isinstance(event.get("action"), dict) else {}
    observation = event.get("observation") if isinstance(event.get("observation"), dict) else {}
    extra = observation.get("extra") if isinstance(observation.get("extra"), dict) else {}
    step_payload = dict(raw_action)
    if "target" not in step_payload:
        step_payload["target"] = _event_target(event)
    if not step_payload.get("valid_state"):
        target = _event_target(event)
        step_payload["valid_state"] = f"{target or raw_action.get('action_type') or 'target'} is visible"
    foreground_app = str(observation.get("foreground_app") or observation.get("app") or app or "")
    return infer_state_contract(
        step_payload,
        observation_extra=extra,
        app=foreground_app,
    )


def _event_target(event: dict[str, Any]) -> str:
    raw_action = event.get("action") if isinstance(event.get("action"), dict) else {}
    for key in ("target", "text"):
        value = raw_action.get(key)
        if isinstance(value, str) and value.strip() and raw_action.get("action_type") != "input_text":
            return value.strip()
    summary = event.get("action_summary") or event.get("model_output")
    return str(summary or raw_action.get("action_type") or "target").strip()


def _find_skill_function(tree: ast.Module, skill_id: str) -> ast.AsyncFunctionDef | None:
    for node in tree.body:
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        if _skill_id_for_function(node) == skill_id:
            return node
    fallback_name = _function_name_from_skill_id(skill_id)
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == fallback_name:
            return node
    return None


def _skill_id_for_function(func: ast.AsyncFunctionDef) -> str:
    for decorator in func.decorator_list:
        if not isinstance(decorator, ast.Call) or _call_name(decorator.func) != "skill":
            continue
        for keyword in decorator.keywords:
            if keyword.arg == "skill_id" and isinstance(keyword.value, ast.Constant):
                return str(keyword.value.value or "")
    return f"code:{func.name}"


def _direct_action_stmts(func: ast.AsyncFunctionDef) -> list[tuple[ast.stmt, ast.Call]]:
    actions: list[tuple[ast.stmt, ast.Call]] = []
    for stmt in func.body:
        call = _awaited_action_call(stmt)
        if call is not None:
            actions.append((stmt, call))
    return actions


def _awaited_action_call(stmt: ast.stmt) -> ast.Call | None:
    if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Await):
        return None
    call = stmt.value.value
    if not isinstance(call, ast.Call) or _call_name(call.func) != "action":
        return None
    return call


def _set_keyword(call: ast.Call, name: str, value: ast.expr) -> None:
    for keyword in call.keywords:
        if keyword.arg == name:
            keyword.value = value
            return
    call.keywords.append(ast.keyword(arg=name, value=value))


def _contract_expr(contract: dict[str, Any]) -> ast.expr:
    return ast.Call(
        func=ast.Attribute(value=ast.Name(id="C", ctx=ast.Load()), attr="from_dict", ctx=ast.Load()),
        args=[ast.parse(repr(contract), mode="eval").body],
        keywords=[],
    )


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _strip_volatile_flags(element: dict[str, Any]) -> dict[str, Any]:
    selector = element.get("selector") if isinstance(element.get("selector"), dict) else {}
    states = [
        str(state)
        for state in (element.get("state") or [])
        if str(state) and str(state) not in _VOLATILE_STATE_FLAGS
    ]
    if "visible" not in states:
        states.append("visible")
    return {"selector": dict(selector), "state": states}


def _dedupe_required(required: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for element in required:
        key = json.dumps(element, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(element)
    return deduped


def _selector_text(selector: dict[str, Any]) -> str:
    for key in ("resource_id", "content_desc", "text"):
        value = selector.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _contract_app(contract: dict[str, Any]) -> str | None:
    normalized = normalize_state_contract(contract)
    anchor = normalized.get("anchor") if normalized else None
    app = anchor.get("app_package") if isinstance(anchor, dict) else None
    return str(app) if app else None


def _function_name_from_skill_id(skill_id: str) -> str:
    if skill_id.startswith("code:"):
        return skill_id.split(":", 1)[1]
    return re.sub(r"[^A-Za-z0-9_]+", "_", skill_id).strip("_") or "skill"


def _task_skill_conflict(task: str, skill_name: str) -> bool:
    task_norm = _normalize_task(task)
    skill_norm = _normalize_task(skill_name)
    if not task_norm or not skill_norm:
        return False
    task_tokens = set(task_norm.split())
    skill_tokens = set(skill_norm.split())
    run_terms = {"run", "running", "start", "started", "resume", "resumed"}
    pause_terms = {"pause", "paused", "stop", "stopped"}
    run_terms_cjk = {"启动", "运行", "开始", "继续"}
    pause_terms_cjk = {"暂停", "停止"}
    task_wants_run = bool(task_tokens & run_terms) or any(term in task_norm for term in run_terms_cjk)
    task_wants_pause = bool(task_tokens & pause_terms) or any(term in task_norm for term in pause_terms_cjk)
    skill_pause = bool(skill_tokens & pause_terms) or any(term in skill_norm for term in pause_terms_cjk)
    skill_run = bool(skill_tokens & run_terms) or any(term in skill_norm for term in run_terms_cjk)
    return (task_wants_run and skill_pause) or (task_wants_pause and skill_run)


def _normalize_task(value: str) -> str:
    normalized = str(value or "").casefold().replace("_", " ").replace("-", " ")
    return " ".join(re.findall(r"[a-z0-9\u4e00-\u9fff]+", normalized))


def _append_unique(values: list[Any], value: str | None) -> None:
    if not value or not str(value).strip():
        return
    text = str(value).strip()
    if text not in values:
        values.append(text)
