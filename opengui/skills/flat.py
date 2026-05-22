"""
opengui.skills.flat
~~~~~~~~~~~~~~~~~~~
Minimal Python-backed GUI skills.

The only persistent skill source is ``skills.py``.  It contains declarative
``@skill`` functions made of awaited ``action(...)`` calls.  No graph cache,
JSON skill bucket, transition evidence, or legacy store is involved.
"""

from __future__ import annotations

import ast
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

import numpy as np

from opengui.skills.data import Skill, SkillStep
from opengui.skills.normalization import normalize_app_identifier, normalize_skill_app
from opengui.skills.state_contract import normalize_state_contract

logger = logging.getLogger(__name__)

CANONICAL_SKILLS_FILENAME = "skills.py"
CODE_HEADER = "from opengui.skills.flat import C, R, action, skill, tag"

_STATE_FLAGS = ("visible", "clickable", "enabled", "focused", "scrollable")
_SELECTOR_KEYS = ("text", "content_desc", "resource_id", "class", "xpath")
_R_ALLOWED_KEYS = frozenset((*_STATE_FLAGS, *_SELECTOR_KEYS, "class_"))
_C_ALLOWED_KEYS = frozenset(("required", "forbidden", "app", "activity"))
_PLACEHOLDER_RE = re.compile(r"\{\{([^{}]+)\}\}")
_STOPWORDS = frozenset({
    "a",
    "an",
    "the",
    "to",
    "in",
    "on",
    "of",
    "for",
    "and",
    "or",
    "is",
    "it",
    "with",
    "from",
    "by",
    "at",
    "be",
    "this",
    "that",
    "do",
    "does",
    "did",
})


@dataclass(frozen=True)
class FlatAction:
    action_type: str
    target: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    expected_state: str | None = None
    valid_state: str | None = None
    state_contract: dict[str, Any] | None = None
    fixed: bool = False
    fixed_values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FlatSkillMeta:
    name: str
    app: str
    platform: str
    tags: tuple[str, ...] = ()
    skill_id: str | None = None
    description: str = ""
    created_at: float | None = None
    success_count: int = 0
    failure_count: int = 0
    success_streak: int = 0
    failure_streak: int = 0


@dataclass(frozen=True)
class FlatCompileResult:
    skills: tuple[Skill, ...] = ()
    errors: tuple[str, ...] = ()


class UnsupportedSkillSourceError(ValueError):
    """Raised when declarative skill source uses unsupported Python."""


def R(**kwargs: Any) -> dict[str, Any]:  # noqa: N802
    unsupported = tuple(str(key) for key in kwargs if str(key) not in _R_ALLOWED_KEYS)
    if unsupported:
        raise ValueError(
            "unsupported R() field: "
            + ", ".join(unsupported)
            + "; R() only accepts selector/state fields."
        )
    selector: dict[str, Any] = {}
    state_flags: list[str] = []
    for key, value in kwargs.items():
        normalized_key = "class" if key == "class_" else key
        if normalized_key in _STATE_FLAGS:
            if value:
                state_flags.append(normalized_key)
            continue
        if normalized_key in _SELECTOR_KEYS and value is not None:
            selector[normalized_key] = value
    element: dict[str, Any] = {"selector": selector}
    if state_flags:
        element["state"] = state_flags
    return element


def C(  # noqa: N802
    *,
    required: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    forbidden: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    app: str | None = None,
    activity: str | None = None,
) -> dict[str, Any] | None:
    anchor: dict[str, Any] = {}
    if app:
        anchor["app_package"] = app
    if activity:
        anchor["activity_class"] = activity
    return normalize_state_contract({
        "anchor": anchor,
        "signature": {
            "required": list(required or ()),
            "forbidden": list(forbidden or ()),
        },
    })


def _contract_from_dict(contract: dict[str, Any]) -> dict[str, Any] | None:
    return normalize_state_contract(contract)


C.from_dict = _contract_from_dict  # type: ignore[attr-defined]


def _contract_with_anchor(
    contract: dict[str, Any] | None,
    *,
    app: str | None = None,
    activity: str | None = None,
) -> dict[str, Any] | None:
    raw: dict[str, Any] = dict(contract or {})
    anchor = dict(raw.get("anchor") or {})
    if app and not anchor.get("app_package"):
        anchor["app_package"] = app
    if activity and not anchor.get("activity_class"):
        anchor["activity_class"] = activity
    if anchor:
        raw["anchor"] = anchor
    return normalize_state_contract(raw)


def tag(*tags: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    clean_tags = tuple(str(t) for t in tags if str(t))

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        existing = tuple(getattr(func, "__opengui_tags__", ()))
        merged = tuple(dict.fromkeys((*existing, *clean_tags)))
        setattr(func, "__opengui_tags__", merged)
        return func

    return decorator


def skill(
    *,
    app: str,
    platform: str,
    tags: list[str] | tuple[str, ...] | None = None,
    skill_id: str | None = None,
    name: str | None = None,
    description: str = "",
    created_at: float | None = None,
    success_count: int = 0,
    failure_count: int = 0,
    success_streak: int = 0,
    failure_streak: int = 0,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        merged_tags = tuple(dict.fromkeys((*getattr(func, "__opengui_tags__", ()), *(tags or ()))))
        setattr(
            func,
            "__opengui_skill__",
            FlatSkillMeta(
                name=name or func.__name__,
                app=app,
                platform=platform,
                tags=merged_tags,
                skill_id=skill_id,
                description=description,
                created_at=created_at,
                success_count=success_count,
                failure_count=failure_count,
                success_streak=success_streak,
                failure_streak=failure_streak,
            ),
        )
        setattr(func, "__opengui_tags__", merged_tags)
        return func

    return decorator


async def action(action_type: str, target: str = "", **parameters: Any) -> FlatAction:
    expected_state = parameters.pop("expected_state", None)
    valid_state = parameters.pop("valid_state", None)
    state_contract = parameters.pop("state_contract", None)
    fixed = bool(parameters.pop("fixed", False))
    fixed_values = parameters.pop("fixed_values", {}) or {}
    explicit_parameters = parameters.pop("parameters", None)
    if isinstance(explicit_parameters, dict):
        parameters.update(explicit_parameters)
    return FlatAction(
        action_type=action_type,
        target=target,
        parameters=parameters,
        expected_state=expected_state,
        valid_state=valid_state,
        state_contract=normalize_state_contract(state_contract),
        fixed=fixed,
        fixed_values=dict(fixed_values),
    )


def compile_flat_skills(source: str) -> FlatCompileResult:
    try:
        tree = ast.parse(source or "")
    except SyntaxError as exc:
        return FlatCompileResult(errors=(f"syntax error: {exc}",))

    errors = _validate_source_ast(tree)
    if errors:
        return FlatCompileResult(errors=tuple(errors))

    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }
    skills: list[Skill] = []
    for func in functions.values():
        if not isinstance(func, ast.AsyncFunctionDef) or not _has_decorator(func, "skill"):
            continue
        try:
            meta = _decorator_kwargs(func, "skill")
            app = str(meta.get("app") or "")
            platform = str(meta.get("platform") or "unknown")
            steps = _extract_steps(func, functions, stack=(), bindings=_self_bindings(func))
            steps = _anchor_skill_step_contracts(steps, app=app)
            skill_kwargs: dict[str, Any] = {
                "skill_id": str(meta.get("skill_id") or f"flat:{func.name}"),
                "name": str(meta.get("name") or func.name),
                "description": str(meta.get("description") or ""),
                "app": normalize_app_identifier(platform, app),
                "platform": platform,
                "tags": tuple(str(t) for t in (meta.get("tags") or ())),
                "parameters": _used_step_parameters(func, steps),
                "steps": steps,
            }
            if meta.get("created_at") is not None:
                skill_kwargs["created_at"] = float(meta["created_at"])
            for count_field in (
                "success_count",
                "failure_count",
                "success_streak",
                "failure_streak",
            ):
                if count_field in meta:
                    skill_kwargs[count_field] = int(meta[count_field])
            skill_obj = Skill(
                **skill_kwargs,
            )
            skills.append(normalize_skill_app(skill_obj))
        except UnsupportedSkillSourceError as exc:
            errors.append(str(exc))
    if errors:
        return FlatCompileResult(errors=tuple(errors))
    return FlatCompileResult(skills=tuple(skills))


class FlatSkillRepository:
    """Manage the canonical ``skills.py`` source file."""

    def __init__(self, store_dir: Path) -> None:
        self.store_dir = Path(store_dir).expanduser()
        self.source_path = self.store_dir / CANONICAL_SKILLS_FILENAME

    def read_source(self) -> str:
        if not self.source_path.exists():
            return CODE_HEADER + "\n"
        return self.source_path.read_text(encoding="utf-8")

    def list_all(self, *, platform: str | None = None, app: str | None = None) -> list[Skill]:
        result = compile_flat_skills(self.read_source())
        if result.errors:
            logger.warning("Cannot list flat skills: %s", result.errors)
            return []
        normalized_app = _normalize_app_filter(platform, app)
        return [
            skill
            for skill in result.skills
            if (platform is None or skill.platform == platform)
            and (normalized_app is None or skill.app == normalized_app)
        ]

    def add(self, skill_obj: Skill) -> str:
        skills = self.list_all()
        replaced = False
        updated: list[Skill] = []
        for existing in skills:
            if existing.skill_id == skill_obj.skill_id:
                updated.append(normalize_skill_app(skill_obj))
                replaced = True
            else:
                updated.append(existing)
        if not replaced:
            updated.append(normalize_skill_app(skill_obj))
        self._write_atomic(export_skills_to_source(updated))
        return skill_obj.skill_id

    def update(self, skill_id: str, updated_skill: Skill) -> bool:
        skills = self.list_all()
        found = False
        updated: list[Skill] = []
        for existing in skills:
            if existing.skill_id == skill_id:
                updated.append(replace(normalize_skill_app(updated_skill), skill_id=skill_id))
                found = True
            else:
                updated.append(existing)
        if found:
            self._write_atomic(export_skills_to_source(updated))
        return found

    def remove(self, skill_id: str) -> bool:
        skills = self.list_all()
        kept = [skill for skill in skills if skill.skill_id != skill_id]
        if len(kept) == len(skills):
            return False
        self._write_atomic(export_skills_to_source(kept))
        return True

    def _write_atomic(self, source: str) -> None:
        self.store_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.source_path.name}.",
            suffix=".tmp",
            dir=str(self.store_dir),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(source.rstrip() + "\n")
            os.replace(tmp_name, self.source_path)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass


class FlatSkillLibrary:
    """Search adapter over ``skills.py`` flat skills."""

    def __init__(
        self,
        *,
        store_dir: Path,
        embedding_provider: Any | None = None,
        merge_llm: Any | None = None,
        embedding_signature: str | None = None,
    ) -> None:
        self.store_dir = Path(store_dir).expanduser()
        self.embedding_provider = embedding_provider
        self.merge_llm = merge_llm
        self.embedding_signature = embedding_signature
        self._repository = FlatSkillRepository(self.store_dir)
        self._source_mtime: float | None = _mtime(self._repository.source_path)

    def refresh_if_stale(self) -> bool:
        current = _mtime(self._repository.source_path)
        changed = current != self._source_mtime
        self._source_mtime = current
        return changed

    def load_all(self) -> None:
        self.refresh_if_stale()

    def list_all(self, *, platform: str | None = None, app: str | None = None) -> list[Skill]:
        return self._repository.list_all(platform=platform, app=app)

    def count(self) -> int:
        return len(self.list_all())

    def add(self, skill_obj: Skill) -> str:
        self._source_mtime = None
        return self._repository.add(skill_obj)

    async def add_or_merge(self, skill_obj: Skill) -> tuple[str, str | None]:
        existing = self.get(skill_obj.skill_id)
        if existing is not None:
            self.update(existing.skill_id, skill_obj)
            return "KEEP_NEW", existing.skill_id
        for candidate in self.list_all(platform=skill_obj.platform, app=skill_obj.app):
            if _normalized_name(candidate.name) == _normalized_name(skill_obj.name):
                self.update(candidate.skill_id, replace(skill_obj, skill_id=candidate.skill_id))
                return "KEEP_NEW", candidate.skill_id
        return "ADD", self.add(skill_obj)

    async def search(
        self,
        query: str,
        *,
        platform: str | None = None,
        app: str | None = None,
        top_k: int = 5,
    ) -> list[tuple[Skill, float]]:
        if not query.strip() or top_k <= 0:
            return []
        skills = self.list_all()
        normalized_app = _normalize_app_filter(platform, app)
        candidates = [
            skill
            for skill in skills
            if (platform is None or skill.platform == platform)
            and (normalized_app is None or skill.app == normalized_app)
        ]
        if not candidates:
            return []

        from opengui.memory.retrieval import _BM25Index

        documents = [_skill_search_text(skill) for skill in candidates]
        bm25 = _BM25Index()
        bm25.build(documents)
        scores = np.array(bm25.score(query), dtype=np.float32)
        #max_score = float(scores.max()) if scores.size else 0.0
        #if max_score > 0:
        #    scores = scores / max_score
        ranked = np.argsort(-scores)
        results: list[tuple[Skill, float]] = []
        for index in ranked:
            score = float(scores[int(index)])
            if score <= 0:
                break
            results.append((candidates[int(index)], score))
            if len(results) >= top_k:
                break
        return results

    def get(self, skill_id: str) -> Skill | None:
        for skill_obj in self.list_all():
            if skill_obj.skill_id == skill_id:
                return skill_obj
        return None

    def feedback_for_skill(self, skill_id: str) -> dict[str, Any]:
        del skill_id
        return {}

    def update(self, skill_id: str, updated_skill: Skill) -> bool:
        self._source_mtime = None
        return self._repository.update(skill_id, updated_skill)

    def remove(self, skill_id: str) -> bool:
        self._source_mtime = None
        return self._repository.remove(skill_id)


def export_skills_to_source(skills: list[Skill] | tuple[Skill, ...]) -> str:
    lines: list[str] = [CODE_HEADER, "", ""]
    names = _stable_function_names(skills)
    for skill_obj in skills:
        func_name = names[skill_obj.skill_id]
        decorator_parts = [
            f"app={_code_literal(skill_obj.app)}",
            f"platform={_code_literal(skill_obj.platform)}",
            f"tags={_code_literal(list(skill_obj.tags))}",
            f"skill_id={_code_literal(skill_obj.skill_id)}",
            f"name={_code_literal(skill_obj.name)}",
        ]
        if skill_obj.description:
            decorator_parts.append(f"description={_code_literal(skill_obj.description)}")
        decorator_parts.append(f"created_at={_code_literal(skill_obj.created_at)}")
        if skill_obj.success_count:
            decorator_parts.append(f"success_count={skill_obj.success_count}")
        if skill_obj.failure_count:
            decorator_parts.append(f"failure_count={skill_obj.failure_count}")
        if skill_obj.success_streak:
            decorator_parts.append(f"success_streak={skill_obj.success_streak}")
        if skill_obj.failure_streak:
            decorator_parts.append(f"failure_streak={skill_obj.failure_streak}")
        lines.append(f"@skill({', '.join(decorator_parts)})")
        placeholder_map = _parameter_placeholder_map(skill_obj.parameters)
        parameters = [placeholder_map[str(parameter)] for parameter in skill_obj.parameters]
        signature = ", ".join(["device", *parameters])
        lines.append(f"async def {func_name}({signature}):")
        if skill_obj.steps:
            for step in skill_obj.steps:
                lines.append(f"    {_action_call_source(step, placeholder_map)}")
        else:
            lines.append("    pass")
        lines.extend(["", ""])
    return "\n".join(lines).rstrip() + "\n"


def _validate_source_ast(tree: ast.Module) -> list[str]:
    errors: list[str] = []
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }
    function_names = set(functions)
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.module == "__future__":
                continue
            if node.module != "opengui.skills.flat":
                errors.append(f"unsupported import: {node.module}")
            continue
        if isinstance(node, ast.Import):
            errors.append("only from opengui.skills.flat imports are allowed")
            continue
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        errors.append(f"unsupported top-level statement: {type(node).__name__}")

    blocked_names = {"eval", "exec", "open", "subprocess", "os", "sys", "adb"}
    blocked_attrs = {"backend", "env", "adb"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            call_name = _call_name(node.func)
            root_name = call_name.split(".", 1)[0]
            if root_name in blocked_names:
                errors.append(f"unsafe call is not allowed: {call_name}")
        if isinstance(node, ast.Attribute):
            root = _attribute_root(node)
            if root in blocked_names or node.attr in blocked_attrs:
                errors.append(f"direct backend/env/adb access is not allowed: {ast.unparse(node)}")

    for func in functions.values():
        if _has_decorator(func, "skill"):
            if not isinstance(func, ast.AsyncFunctionDef):
                errors.append(f"skill function must be async: {func.name}")
            first_arg = func.args.args[0].arg if func.args.args else None
            if first_arg != "device":
                errors.append(f"skill function first argument must be device: {func.name}")
        if isinstance(func, ast.AsyncFunctionDef):
            _validate_function_body(func, function_names, errors)
    return errors


def _validate_function_body(
    func: ast.AsyncFunctionDef,
    function_names: set[str],
    errors: list[str],
) -> None:
    allowed_nested_calls = {"C", "C.from_dict", "R"}
    for stmt in func.body:
        if isinstance(stmt, ast.Pass):
            continue
        if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Await):
            for call in (node for node in ast.walk(stmt) if isinstance(node, ast.Call)):
                call_name = _call_name(call.func)
                if call_name == "action" or call_name in function_names:
                    errors.append(f"{func.name} must await {call_name}(...)")
            continue
        call = stmt.value.value
        if not isinstance(call, ast.Call):
            errors.append(f"{func.name} awaits a non-call expression")
            continue
        call_name = _call_name(call.func)
        if call_name == "action":
            for nested in ast.walk(call):
                if nested is call or not isinstance(nested, ast.Call):
                    continue
                nested_name = _call_name(nested.func)
                if nested_name not in allowed_nested_calls:
                    errors.append(f"{func.name} contains unsupported nested call: {nested_name}")
            continue
        if call_name in function_names:
            continue
        errors.append(f"{func.name} calls unknown function: {call_name}")


def _extract_steps(
    func: ast.AsyncFunctionDef,
    functions: dict[str, ast.AST],
    *,
    stack: tuple[str, ...],
    bindings: dict[str, ast.AST],
) -> tuple[SkillStep, ...]:
    if func.name in stack:
        cycle = " -> ".join((*stack, func.name))
        raise UnsupportedSkillSourceError(f"recursive helper call: {cycle}")
    steps: list[SkillStep] = []
    for stmt in func.body:
        if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Await):
            continue
        call = stmt.value.value
        if not isinstance(call, ast.Call):
            continue
        call_name = _call_name(call.func)
        if call_name == "action":
            steps.append(_skill_step_from_action_call(call, bindings))
            continue
        callee = functions.get(call_name)
        if isinstance(callee, ast.AsyncFunctionDef):
            steps.extend(_extract_steps(
                callee,
                functions,
                stack=(*stack, func.name),
                bindings=_bind_call_arguments(callee, call, bindings),
            ))
    return tuple(steps)


def _skill_step_from_action_call(call: ast.Call, bindings: dict[str, ast.AST]) -> SkillStep:
    action_type = _literal_value(call.args[0]) if call.args else ""
    target = ""
    parameters: dict[str, Any] = {}
    expected_state: str | None = None
    valid_state: str | None = None
    state_contract: dict[str, Any] | None = None
    fixed = False
    fixed_values: dict[str, Any] = {}
    for kw in call.keywords:
        if kw.arg is None:
            continue
        if kw.arg == "target":
            target = str(_literal_or_placeholder(kw.value, bindings))
            continue
        if kw.arg == "expected_state":
            expected_state = str(_literal_or_placeholder(kw.value, bindings))
            continue
        if kw.arg == "valid_state":
            valid_state = str(_literal_or_placeholder(kw.value, bindings))
            continue
        if kw.arg == "state_contract":
            state_contract = _contract_from_ast(kw.value, bindings)
            continue
        if kw.arg == "fixed":
            fixed = bool(_literal_or_placeholder(kw.value, bindings))
            continue
        if kw.arg == "fixed_values":
            fixed_value = _literal_or_placeholder(kw.value, bindings)
            fixed_values = dict(fixed_value or {})
            continue
        if kw.arg == "parameters":
            explicit_parameters = _literal_or_placeholder(kw.value, bindings)
            if isinstance(explicit_parameters, dict):
                parameters.update(explicit_parameters)
            continue
        parameters[kw.arg] = _literal_or_placeholder(kw.value, bindings)
    return SkillStep(
        action_type=str(action_type),
        target=target,
        parameters=parameters,
        expected_state=expected_state,
        valid_state=valid_state,
        state_contract=state_contract,
        fixed=fixed,
        fixed_values=fixed_values,
    )


def _contract_from_ast(node: ast.AST, bindings: dict[str, ast.AST]) -> dict[str, Any] | None:
    if not isinstance(node, ast.Call):
        return normalize_state_contract(_literal_value(node))
    call_name = _call_name(node.func)
    if call_name == "C.from_dict":
        if not node.args:
            return None
        return normalize_state_contract(_literal_value(node.args[0]))
    if call_name != "C":
        return None
    if any(kw.arg is None for kw in node.keywords):
        raise UnsupportedSkillSourceError("C() does not support **kwargs")
    unsupported = tuple(
        str(kw.arg)
        for kw in node.keywords
        if kw.arg is not None and kw.arg not in _C_ALLOWED_KEYS
    )
    if unsupported:
        raise UnsupportedSkillSourceError(f"unsupported C() field: {', '.join(unsupported)}")
    kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
    required = _selector_list_from_ast(kwargs.get("required"), bindings)
    forbidden = _selector_list_from_ast(kwargs.get("forbidden"), bindings)
    app = _literal_or_placeholder(kwargs["app"], bindings) if "app" in kwargs else None
    activity = _literal_or_placeholder(kwargs["activity"], bindings) if "activity" in kwargs else None
    return C(required=required, forbidden=forbidden, app=app, activity=activity)


def _selector_list_from_ast(node: ast.AST | None, bindings: dict[str, ast.AST]) -> list[dict[str, Any]]:
    if node is None:
        return []
    if not isinstance(node, (ast.List, ast.Tuple)):
        value = _literal_value(node)
        return list(value or ())
    selectors: list[dict[str, Any]] = []
    for element in node.elts:
        if isinstance(element, ast.Call) and _call_name(element.func) == "R":
            selectors.append(_selector_from_r_call(element, bindings))
        else:
            selectors.append(_literal_value(element))
    return selectors


def _selector_from_r_call(call: ast.Call, bindings: dict[str, ast.AST]) -> dict[str, Any]:
    if any(kw.arg is None for kw in call.keywords):
        raise UnsupportedSkillSourceError("R() does not support **kwargs")
    unsupported = tuple(str(kw.arg) for kw in call.keywords if kw.arg is not None and str(kw.arg) not in _R_ALLOWED_KEYS)
    if unsupported:
        raise UnsupportedSkillSourceError(f"unsupported R() field: {', '.join(unsupported)}")
    kwargs = {
        kw.arg: _literal_or_placeholder(kw.value, bindings)
        for kw in call.keywords
        if kw.arg is not None
    }
    try:
        return R(**kwargs)
    except ValueError as exc:
        raise UnsupportedSkillSourceError(str(exc)) from exc


def _anchor_skill_step_contracts(steps: tuple[SkillStep, ...], *, app: str | None) -> tuple[SkillStep, ...]:
    if not app:
        return steps
    anchored_steps: list[SkillStep] = []
    for step in steps:
        if not step.state_contract:
            anchored_steps.append(step)
            continue
        anchored_contract = _contract_with_anchor(step.state_contract, app=app)
        if anchored_contract != step.state_contract:
            step = replace(step, state_contract=anchored_contract)
        anchored_steps.append(step)
    return tuple(anchored_steps)


def _literal_or_placeholder(
    node: ast.AST,
    bindings: dict[str, ast.AST],
    *,
    seen: frozenset[str] = frozenset(),
) -> Any:
    if isinstance(node, ast.Name):
        if node.id in bindings and node.id not in seen:
            return _literal_or_placeholder(bindings[node.id], bindings, seen=seen | {node.id})
        return f"{{{{{node.id}}}}}"
    return _literal_value(node)


def _literal_value(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError) as exc:
        raise UnsupportedSkillSourceError(f"unsupported expression: {ast.unparse(node)}") from exc


def _self_bindings(func: ast.AsyncFunctionDef) -> dict[str, ast.AST]:
    return {arg.arg: ast.Name(id=arg.arg, ctx=ast.Load()) for arg in func.args.args}


def _bind_call_arguments(
    callee: ast.AsyncFunctionDef,
    call: ast.Call,
    caller_bindings: dict[str, ast.AST],
) -> dict[str, ast.AST]:
    bindings = _self_bindings(callee)
    for arg_def, arg_value in zip(callee.args.args, call.args, strict=False):
        bindings[arg_def.arg] = _resolve_bound_ast(arg_value, caller_bindings)
    for kw in call.keywords:
        if kw.arg is None:
            continue
        bindings[kw.arg] = _resolve_bound_ast(kw.value, caller_bindings)
    return bindings


def _resolve_bound_ast(node: ast.AST, bindings: dict[str, ast.AST]) -> ast.AST:
    if isinstance(node, ast.Name) and node.id in bindings:
        return bindings[node.id]
    return node


def _decorator_kwargs(func: ast.AsyncFunctionDef | ast.FunctionDef, name: str) -> dict[str, Any]:
    for decorator in func.decorator_list:
        if isinstance(decorator, ast.Call) and _call_name(decorator.func) == name:
            return {
                kw.arg: _literal_value(kw.value)
                for kw in decorator.keywords
                if kw.arg is not None
            }
    return {}


def _has_decorator(func: ast.AsyncFunctionDef | ast.FunctionDef, name: str) -> bool:
    return any(
        (isinstance(decorator, ast.Call) and _call_name(decorator.func) == name)
        or (isinstance(decorator, ast.Name) and decorator.id == name)
        for decorator in func.decorator_list
    )


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ast.unparse(node)


def _attribute_root(node: ast.Attribute) -> str:
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        current = current.value
    if isinstance(current, ast.Name):
        return current.id
    return ""


def _used_step_parameters(func: ast.AsyncFunctionDef, steps: tuple[SkillStep, ...]) -> tuple[str, ...]:
    declared = tuple(arg.arg for arg in func.args.args[1:])
    if not declared:
        return ()
    used = _placeholder_names_in_value([
        {
            "target": step.target,
            "parameters": step.parameters,
            "expected_state": step.expected_state,
            "valid_state": step.valid_state,
            "state_contract": step.state_contract,
            "fixed_values": step.fixed_values,
        }
        for step in steps
    ])
    return tuple(name for name in declared if name in used)


def _placeholder_names_in_value(value: Any) -> set[str]:
    if isinstance(value, str):
        return {match.group(1) for match in _PLACEHOLDER_RE.finditer(value)}
    if isinstance(value, dict):
        names: set[str] = set()
        for key, item in value.items():
            names.update(_placeholder_names_in_value(key))
            names.update(_placeholder_names_in_value(item))
        return names
    if isinstance(value, (list, tuple, set)):
        names: set[str] = set()
        for item in value:
            names.update(_placeholder_names_in_value(item))
        return names
    return set()


def _skill_search_text(skill_obj: Skill) -> str:
    step_text = " ".join(
        " ".join([
            step.action_type,
            step.target,
            " ".join(str(v) for v in step.parameters.values()),
            step.expected_state or "",
            step.valid_state or "",
        ])
        for step in skill_obj.steps
    )
    return " ".join([
        skill_obj.name,
        skill_obj.description,
        skill_obj.app,
        skill_obj.platform,
        " ".join(skill_obj.tags),
        " ".join(skill_obj.preconditions),
        step_text,
    ])


def _normalized_name(name: str) -> str:
    tokens = re.findall(r"\w+", name.lower())
    return " ".join(t for t in tokens if t not in _STOPWORDS)


def _normalize_app_filter(platform: str | None, app: str | None) -> str | None:
    if app is None:
        return None
    return normalize_app_identifier(platform or "unknown", app)


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return None


def _stable_function_names(skills: list[Skill] | tuple[Skill, ...]) -> dict[str, str]:
    used: set[str] = set()
    names: dict[str, str] = {}
    for skill_obj in skills:
        base = _safe_identifier(skill_obj.name or skill_obj.skill_id or "skill")
        candidate = base
        suffix = 2
        while candidate in used:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate)
        names[skill_obj.skill_id] = candidate
    return names


def _safe_identifier(value: str) -> str:
    text = re.sub(r"\W+", "_", value.strip().lower()).strip("_")
    if not text:
        text = "skill"
    if text[0].isdigit():
        text = f"skill_{text}"
    if text in {"class", "def", "return", "async", "await", "from", "import"}:
        text = f"{text}_skill"
    return text


def _parameter_placeholder_map(parameters: tuple[str, ...] | list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: set[str] = {"device"}
    for parameter in parameters:
        key = str(parameter)
        name = _safe_identifier(key)
        candidate = name
        suffix = 2
        while candidate in used:
            candidate = f"{name}_{suffix}"
            suffix += 1
        used.add(candidate)
        mapping[key] = candidate
    return mapping


def _action_call_source(step: SkillStep, placeholder_map: dict[str, str]) -> str:
    args = [_code_literal(step.action_type)]
    kwargs: list[str] = []
    if step.target:
        kwargs.append(f"target={_template_literal(step.target, placeholder_map)}")
    if step.parameters:
        for key, value in step.parameters.items():
            if _safe_identifier(str(key)) == str(key):
                kwargs.append(f"{key}={_template_literal(value, placeholder_map)}")
            else:
                kwargs.append(f"parameters={_code_literal(step.parameters)}")
                break
    if step.expected_state is not None:
        kwargs.append(f"expected_state={_template_literal(step.expected_state, placeholder_map)}")
    if step.valid_state is not None:
        kwargs.append(f"valid_state={_template_literal(step.valid_state, placeholder_map)}")
    if step.state_contract:
        kwargs.append(f"state_contract=C.from_dict({_code_literal(step.state_contract)})")
    if step.fixed:
        kwargs.append("fixed=True")
    if step.fixed_values:
        kwargs.append(f"fixed_values={_code_literal(step.fixed_values)}")
    return f"await action({', '.join([*args, *kwargs])})"


def _template_literal(value: Any, placeholder_map: dict[str, str]) -> str:
    if isinstance(value, str):
        parts: list[str] = []
        cursor = 0
        for match in _PLACEHOLDER_RE.finditer(value):
            if match.start() > cursor:
                parts.append(_code_literal(value[cursor:match.start()]))
            name = match.group(1)
            replacement = placeholder_map.get(name)
            if replacement is None:
                parts.append(_code_literal(match.group(0)))
            else:
                parts.append(replacement)
            cursor = match.end()
        if cursor < len(value):
            parts.append(_code_literal(value[cursor:]))
        if not parts:
            return _code_literal(value)
        if len(parts) == 1:
            return parts[0]
        return " + ".join(parts)
    return _code_literal(value)


def _code_literal(value: Any) -> str:
    return repr(value)


__all__ = [
    "CANONICAL_SKILLS_FILENAME",
    "CODE_HEADER",
    "C",
    "FlatCompileResult",
    "FlatSkillLibrary",
    "FlatSkillRepository",
    "R",
    "action",
    "compile_flat_skills",
    "export_skills_to_source",
    "skill",
    "tag",
]
