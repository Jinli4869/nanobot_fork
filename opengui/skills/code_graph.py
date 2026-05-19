"""
opengui.skills.code_graph
~~~~~~~~~~~~~~~~~~~~~~~~~
Declarative Python source helpers for OpenGUI skill graph code.

The helpers in this module are metadata carriers. They make Python source an
editable representation of skills and graph transitions without making authored
function bodies part of the runtime execution path.
"""

from __future__ import annotations

import ast
import keyword
import pprint
import re
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Callable, Literal

from opengui.skills.data import Skill, SkillStep
from opengui.skills.graph import (
    EDGE_STATUS_ACTIVE,
    NODE_KIND_STATE,
    NODE_STATUS_ACTIVE,
    GraphEdge,
    GraphNode,
    SkillGraphStore,
)
from opengui.skills.state_contract import normalize_state_contract

if TYPE_CHECKING:
    from opengui.skills.legacy_json import SkillLibrary


_STATE_FLAGS = ("visible", "clickable", "enabled", "focused", "scrollable")
_SELECTOR_KEYS = ("text", "content_desc", "resource_id", "class", "xpath")
_R_ALLOWED_KEYS = frozenset((*_STATE_FLAGS, *_SELECTOR_KEYS, "class_"))
_C_ALLOWED_KEYS = frozenset(("required", "forbidden", "app", "activity"))
_PLACEHOLDER_RE = re.compile(r"\{\{([^{}]+)\}\}")


@dataclass(frozen=True)
class CodeState:
    name: str
    contract: dict[str, Any] | None
    app: str | None = None
    platform: str | None = None
    activity: str | None = None
    node_id: str | None = None
    description: str = ""
    version: int = 1
    status: str = NODE_STATUS_ACTIVE
    kind: str = NODE_KIND_STATE
    skill_ids: tuple[str, ...] = ()
    fingerprint: str = ""
    retrieval_profile: dict[str, Any] | None = None
    source_ref: dict[str, Any] | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CodeTransition:
    name: str
    src: Callable[..., Any]
    dst: Callable[..., Any]
    edge_id: str | None = None
    skill_id: str | None = None
    version: int | None = None
    status: str | None = None
    kind: str = "action"
    source_ref: dict[str, Any] | None = None
    tags: tuple[str, ...] = ()
    unchecked: bool = False


@dataclass(frozen=True)
class CodeAction:
    action_type: str
    target: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    expected_state: str | None = None
    valid_state: str | None = None
    state_contract: dict[str, Any] | None = None
    fixed: bool = False
    fixed_values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CodeSkill:
    name: str
    app: str
    platform: str
    tags: tuple[str, ...] = ()
    skill_id: str | None = None
    description: str = ""


@dataclass(frozen=True)
class CodeGraphCompileResult:
    skills: tuple[Skill, ...] = ()
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()
    errors: list[str] = field(default_factory=list)


class UnsupportedCodeExpressionError(ValueError):
    """Raised when declarative source uses an unsupported AST expression."""


def R(**kwargs: Any) -> dict[str, Any]:  # noqa: N802
    """Build a canonical state-contract selector element."""
    unsupported = _unsupported_r_fields(kwargs)
    if unsupported:
        raise ValueError(_unsupported_r_field_message(unsupported))
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


def _unsupported_r_fields(keys: Any) -> tuple[str, ...]:
    return tuple(str(key) for key in keys if str(key) not in _R_ALLOWED_KEYS)


def _unsupported_r_field_message(fields: tuple[str, ...]) -> str:
    field_text = ", ".join(fields)
    return (
        f"unsupported R() field: {field_text}; "
        "R() only accepts selector/state fields. Use C(app=...) for app anchors."
    )


def C(  # noqa: N802
    *,
    required: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    forbidden: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    app: str | None = None,
    activity: str | None = None,
) -> dict[str, Any] | None:
    """Build and normalize an OpenGUI state contract."""
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


def _get_tags(func: Callable[..., Any]) -> tuple[str, ...]:
    return tuple(getattr(func, "__opengui_tags__", ()))


def tag(*tags: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Attach classification tags to a declarative source function."""
    clean_tags = tuple(str(t) for t in tags if str(t))

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        existing = tuple(getattr(func, "__opengui_tags__", ()))
        merged = tuple(dict.fromkeys((*existing, *clean_tags)))
        setattr(func, "__opengui_tags__", merged)
        return func

    return decorator


def state(
    *,
    app: str | None = None,
    platform: str | None = None,
    activity: str | None = None,
    node_id: str | None = None,
    description: str = "",
    version: int = 1,
    status: str = NODE_STATUS_ACTIVE,
    kind: str = NODE_KIND_STATE,
    skill_ids: list[str] | tuple[str, ...] | None = None,
    fingerprint: str = "",
    retrieval_profile: dict[str, Any] | None = None,
    source_ref: dict[str, Any] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a function as a graph state declaration."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        contract = _contract_with_anchor(func(), app=app, activity=activity)
        setattr(
            func,
            "__opengui_state__",
            CodeState(
                name=func.__name__,
                contract=contract,
                app=app,
                platform=platform,
                activity=activity,
                node_id=node_id,
                description=description,
                version=version,
                status=status,
                kind=kind,
                skill_ids=tuple(skill_ids or ()),
                fingerprint=fingerprint,
                retrieval_profile=retrieval_profile,
                source_ref=source_ref,
                tags=_get_tags(func),
            ),
        )
        return func

    return decorator


def transition(
    *,
    src: Callable[..., Any],
    dst: Callable[..., Any],
    edge_id: str | None = None,
    skill_id: str | None = None,
    version: int | None = None,
    status: str | None = None,
    kind: str = "action",
    source_ref: dict[str, Any] | None = None,
    unchecked: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a function as a graph transition declaration."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        setattr(
            func,
            "__opengui_transition__",
            CodeTransition(
                name=func.__name__,
                src=src,
                dst=dst,
                edge_id=edge_id,
                skill_id=skill_id,
                version=version,
                status=status,
                kind=kind,
                source_ref=source_ref,
                tags=_get_tags(func),
                unchecked=unchecked,
            ),
        )
        return func

    return decorator


def skill(
    *,
    app: str,
    platform: str,
    tags: list[str] | tuple[str, ...] | None = None,
    skill_id: str | None = None,
    description: str = "",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Mark a function as a top-level skill declaration."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        merged_tags = tuple(dict.fromkeys((*_get_tags(func), *(tags or ()))))
        setattr(
            func,
            "__opengui_skill__",
            CodeSkill(
                name=func.__name__,
                app=app,
                platform=platform,
                tags=merged_tags,
                skill_id=skill_id,
                description=description,
            ),
        )
        setattr(func, "__opengui_tags__", merged_tags)
        return func

    return decorator


async def action(
    action_type: str,
    target: str = "",
    **parameters: Any,
) -> CodeAction:
    """Declare one GUI action inside a source function."""
    expected_state = parameters.pop("expected_state", None)
    valid_state = parameters.pop("valid_state", None)
    state_contract = parameters.pop("state_contract", None)
    fixed = bool(parameters.pop("fixed", False))
    fixed_values = parameters.pop("fixed_values", {}) or {}
    explicit_parameters = parameters.pop("parameters", None)
    if isinstance(explicit_parameters, dict):
        parameters.update(explicit_parameters)
    return CodeAction(
        action_type=action_type,
        target=target,
        parameters=parameters,
        expected_state=expected_state,
        valid_state=valid_state,
        state_contract=normalize_state_contract(state_contract),
        fixed=fixed,
        fixed_values=dict(fixed_values),
    )


def compile_code_skills(source: str) -> CodeGraphCompileResult:
    """Compile declarative code source into existing ``Skill`` objects."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return CodeGraphCompileResult(errors=[f"syntax error: {exc}"])

    errors = _validate_code_ast(tree)
    if errors:
        return CodeGraphCompileResult(errors=errors)

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
            skill_id = str(meta.get("skill_id") or f"code:{func.name}")
            tags = tuple(str(t) for t in (meta.get("tags") or ()))
            app = str(meta.get("app") or "")
            steps = _extract_steps(
                func,
                functions,
                stack=(),
                bindings=_self_bindings(func),
            )
            steps = _anchor_skill_step_contracts(steps, app=app)
        except UnsupportedCodeExpressionError as exc:
            errors.append(str(exc))
            continue
        skills.append(Skill(
            skill_id=skill_id,
            name=func.name,
            description=str(meta.get("description") or ""),
            app=app,
            platform=str(meta.get("platform") or "unknown"),
            tags=tags,
            parameters=_used_step_parameters(func, steps),
            steps=steps,
        ))
    if errors:
        return CodeGraphCompileResult(errors=errors)
    return CodeGraphCompileResult(skills=tuple(skills), errors=[])


def _used_step_parameters(func: ast.AsyncFunctionDef, steps: tuple[SkillStep, ...]) -> tuple[str, ...]:
    """Return function parameters that survive into executable step payloads."""
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


def _validate_code_ast(tree: ast.Module) -> list[str]:
    """Return validation errors for unsafe or unsupported source constructs."""
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
            if node.module != "opengui.skills.code_graph":
                errors.append(f"unsupported import: {node.module}")
            continue
        if isinstance(node, ast.Import):
            errors.append("only from opengui.skills.code_graph imports are allowed")
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


def _extract_skill_steps(func: ast.AsyncFunctionDef) -> tuple[SkillStep, ...]:
    functions = {func.name: func}
    return _extract_steps(func, functions, stack=(), bindings=_self_bindings(func))


def _extract_steps(
    func: ast.AsyncFunctionDef,
    functions: dict[str, ast.AST],
    *,
    stack: tuple[str, ...],
    bindings: dict[str, ast.AST],
) -> tuple[SkillStep, ...]:
    if func.name in stack:
        cycle = " -> ".join((*stack, func.name))
        raise UnsupportedCodeExpressionError(f"recursive helper call: {cycle}")
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


def _skill_step_from_action_call(
    call: ast.Call,
    bindings: dict[str, ast.AST],
) -> SkillStep:
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


def _contract_from_ast(
    node: ast.AST,
    bindings: dict[str, ast.AST],
) -> dict[str, Any] | None:
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
        raise UnsupportedCodeExpressionError("C() does not support **kwargs")
    unsupported = tuple(
        str(kw.arg)
        for kw in node.keywords
        if kw.arg is not None and kw.arg not in _C_ALLOWED_KEYS
    )
    if unsupported:
        field_text = ", ".join(unsupported)
        raise UnsupportedCodeExpressionError(f"unsupported C() field: {field_text}")
    kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
    required = _selector_list_from_ast(kwargs.get("required"), bindings)
    forbidden = _selector_list_from_ast(kwargs.get("forbidden"), bindings)
    app = _literal_or_placeholder(kwargs["app"], bindings) if "app" in kwargs else None
    activity = (
        _literal_or_placeholder(kwargs["activity"], bindings)
        if "activity" in kwargs
        else None
    )
    return C(required=required, forbidden=forbidden, app=app, activity=activity)


def _selector_list_from_ast(
    node: ast.AST | None,
    bindings: dict[str, ast.AST],
) -> list[dict[str, Any]]:
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


def _selector_from_r_call(
    call: ast.Call,
    bindings: dict[str, ast.AST],
) -> dict[str, Any]:
    if any(kw.arg is None for kw in call.keywords):
        raise UnsupportedCodeExpressionError("R() does not support **kwargs")
    unsupported = _unsupported_r_fields(kw.arg for kw in call.keywords if kw.arg is not None)
    if unsupported:
        raise UnsupportedCodeExpressionError(_unsupported_r_field_message(unsupported))
    kwargs = {
        kw.arg: _literal_or_placeholder(kw.value, bindings)
        for kw in call.keywords
        if kw.arg is not None
    }
    try:
        return R(**kwargs)
    except ValueError as exc:
        raise UnsupportedCodeExpressionError(str(exc)) from exc


def _anchor_skill_step_contracts(
    steps: tuple[SkillStep, ...],
    *,
    app: str | None,
) -> tuple[SkillStep, ...]:
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
            return _literal_or_placeholder(
                bindings[node.id],
                bindings,
                seen=seen | {node.id},
            )
        return f"{{{{{node.id}}}}}"
    return _literal_value(node)


def _literal_value(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError) as exc:
        raise UnsupportedCodeExpressionError(
            f"unsupported expression: {ast.unparse(node)}"
        ) from exc


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


def export_skills_to_code(skills: list[Skill]) -> str:
    """Export existing JSON-backed skills to editable Python source code."""
    lines: list[str] = [
        "from opengui.skills.code_graph import C, action, skill",
        "",
        "",
    ]
    names = _stable_function_names(skills)
    for skill_obj in skills:
        func_name = names[skill_obj.skill_id]
        decorator_parts = [
            f"app={_code_literal(skill_obj.app)}",
            f"platform={_code_literal(skill_obj.platform)}",
            f"tags={_code_literal(list(skill_obj.tags))}",
            f"skill_id={_code_literal(skill_obj.skill_id)}",
        ]
        if skill_obj.description:
            decorator_parts.append(f"description={_code_literal(skill_obj.description)}")
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


def export_skill_library_to_code(
    library: "SkillLibrary",
    *,
    platform: str | None = None,
    app: str | None = None,
) -> str:
    """Export skills from a legacy/list_all-compatible library."""
    return export_skills_to_code(library.list_all(platform=platform, app=app))


def export_graph_to_code(
    store: SkillGraphStore,
    *,
    platform: str | None = None,
    app: str | None = None,
) -> str:
    """Export a ``SkillGraphStore`` to editable state/transition source code."""
    lines: list[str] = [
        "from opengui.skills.code_graph import C, action, state, transition",
        "",
        "",
    ]
    nodes = store.list_nodes(platform=platform, app=app)
    edges = store.list_edges(platform=platform, app=app)
    node_names = _graph_function_names(
        nodes,
        prefix="state",
        id_getter=lambda node: node.node_id,
    )
    edge_names = _graph_function_names(
        edges,
        prefix="edge",
        id_getter=lambda edge: edge.edge_id,
    )

    for node in nodes:
        func_name = node_names[node.node_id]
        source_ref = node.source_ref or _generated_source_ref(
            func_name,
            "state",
            line=len(lines) + 2,
        )
        decorator_parts = [
            f"app={_code_literal(node.app)}",
            f"platform={_code_literal(node.platform)}",
            f"node_id={_code_literal(node.node_id)}",
            f"description={_code_literal(node.description)}",
            f"version={int(node.version or 1)}",
            f"status={_code_literal(node.status)}",
            f"kind={_code_literal(node.kind)}",
            f"skill_ids={_code_literal(list(node.skill_ids))}",
            f"fingerprint={_code_literal(node.fingerprint)}",
            f"retrieval_profile={_code_literal(node.retrieval_profile)}",
            f"source_ref={_code_literal(source_ref)}",
        ]
        lines.append(f"@state({', '.join(decorator_parts)})")
        lines.append(f"def {func_name}():")
        if node.state_contract:
            lines.append(f"    return C.from_dict({_code_literal(node.state_contract)})")
        else:
            lines.append("    return None")
        lines.extend(["", ""])

    for edge in edges:
        source_name = node_names.get(edge.source_node_id)
        target_name = node_names.get(edge.target_node_id)
        if not source_name or not target_name:
            continue
        func_name = edge_names[edge.edge_id]
        source_ref = edge.source_ref or _generated_source_ref(
            func_name,
            "transition",
            line=len(lines) + 2,
        )
        decorator_parts = [
            f"src={source_name}",
            f"dst={target_name}",
            f"edge_id={_code_literal(edge.edge_id)}",
            f"skill_id={_code_literal(edge.skill_id)}",
            f"status={_code_literal(edge.status)}",
            f"kind={_code_literal(edge.kind)}",
            f"source_ref={_code_literal(source_ref)}",
        ]
        if edge.precondition is None:
            decorator_parts.append("unchecked=True")
        lines.append(f"@transition({', '.join(decorator_parts)})")
        lines.append(f"async def {func_name}(device):")
        lines.append(f"    {_graph_action_call_source(edge)}")
        lines.extend(["", ""])
    return "\n".join(lines).rstrip() + "\n"


async def compile_code_graph(
    source: str,
    store: SkillGraphStore,
) -> CodeGraphCompileResult:
    """Compile declarative graph code into a ``SkillGraphStore``."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return CodeGraphCompileResult(errors=[f"syntax error: {exc}"])

    errors = _validate_code_ast(tree)
    if errors:
        return CodeGraphCompileResult(errors=errors)

    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }
    nodes_by_func: dict[str, GraphNode] = {}
    node_defs: list[GraphNode] = []
    edge_defs: list[GraphEdge] = []

    for func in functions.values():
        if not isinstance(func, ast.FunctionDef) or not _has_decorator(func, "state"):
            continue
        try:
            meta = _decorator_kwargs(func, "state")
            contract = _state_contract_from_function(func)
        except UnsupportedCodeExpressionError as exc:
            errors.append(str(exc))
            continue
        source_ref = meta.get("source_ref") or _source_ref_from_function(func, "state")
        node = GraphNode(
            node_id=str(meta.get("node_id") or f"code:{func.name}"),
            app=str(meta.get("app") or "unknown"),
            platform=str(meta.get("platform") or "unknown"),
            description=str(meta.get("description") or func.name),
            state_contract=contract,
            version=int(meta.get("version") or 1),
            status=str(meta.get("status") or NODE_STATUS_ACTIVE),
            kind=str(meta.get("kind") or NODE_KIND_STATE),
            skill_ids=tuple(str(sid) for sid in (meta.get("skill_ids") or ())),
            fingerprint=str(meta.get("fingerprint") or ""),
            retrieval_profile=meta.get("retrieval_profile") if isinstance(meta.get("retrieval_profile"), dict) else None,
            source_ref=source_ref,
        ).normalized()
        nodes_by_func[func.name] = node
        node_defs.append(node)

    for func in functions.values():
        if not isinstance(func, ast.AsyncFunctionDef) or not _has_decorator(func, "transition"):
            continue
        try:
            info = _transition_decorator_info(func)
            source_node = nodes_by_func.get(str(info.get("src") or ""))
            target_node = nodes_by_func.get(str(info.get("dst") or ""))
            if source_node is None or target_node is None:
                errors.append(f"transition {func.name} references unknown state")
                continue
            steps = _extract_steps(
                func,
                functions,
                stack=(),
                bindings=_self_bindings(func),
            )
            if len(steps) != 1:
                errors.append(f"transition {func.name} must contain exactly one action")
                continue
            if steps[0].state_contract is None and not bool(info.get("unchecked")):
                errors.append(
                    f"transition {func.name} missing state_contract; "
                    "add action(..., state_contract=...) or @transition(..., unchecked=True)"
                )
                continue
        except UnsupportedCodeExpressionError as exc:
            errors.append(str(exc))
            continue
        step = steps[0]
        source_ref = info.get("source_ref") or _source_ref_from_function(func, "transition")
        edge = GraphEdge(
            edge_id=str(info.get("edge_id") or f"code:{func.name}"),
            app=source_node.app,
            platform=source_node.platform,
            source_node_id=source_node.node_id,
            target_node_id=target_node.node_id,
            action_type=step.action_type,
            target=step.target,
            parameters=step.parameters,
            precondition=step.state_contract,
            status=str(info.get("status") or EDGE_STATUS_ACTIVE),
            skill_id=info.get("skill_id"),
            kind=str(info.get("kind") or "action"),
            source_ref=source_ref,
        ).normalized()
        edge_defs.append(edge)

    if errors:
        return CodeGraphCompileResult(errors=errors)
    compiled_nodes = [store.upsert_node(node, save=False) for node in node_defs]
    node_aliases = {
        declared.node_id: compiled.node_id
        for declared, compiled in zip(node_defs, compiled_nodes, strict=False)
        if declared.node_id != compiled.node_id
    }
    compiled_edges = [
        store.upsert_edge(_rewrite_edge_node_ids(edge, node_aliases, store), save=False)
        for edge in edge_defs
    ]
    store.save()
    return CodeGraphCompileResult(
        nodes=tuple(compiled_nodes),
        edges=tuple(compiled_edges),
        errors=[],
    )


def _rewrite_edge_node_ids(
    edge: GraphEdge,
    node_aliases: dict[str, str],
    store: SkillGraphStore,
) -> GraphEdge:
    source_node_id = node_aliases.get(edge.source_node_id, edge.source_node_id)
    target_node_id = node_aliases.get(edge.target_node_id, edge.target_node_id)
    if source_node_id == edge.source_node_id and target_node_id == edge.target_node_id:
        return edge
    source = store.get_node(source_node_id)
    return replace(
        edge,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        precondition=source.state_contract if source and source.state_contract else edge.precondition,
    )


def render_code_tree(
    source: str,
    *,
    format: Literal["text", "mermaid"] = "text",
) -> str:
    """Render the static containment tree for code graph source."""
    tree = ast.parse(source)
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
    }
    kinds = {name: _function_kind(func) for name, func in functions.items()}
    roots = [
        func
        for func in functions.values()
        if isinstance(func, ast.AsyncFunctionDef) and kinds[func.name] == "skill"
    ]
    graph_links = _graph_transition_links(functions)
    graph_state_names = [name for name in functions if kinds.get(name) == "state"]
    if not roots and graph_state_names:
        return _render_graph_tree(functions, kinds, graph_links, format=format)
    edges: list[tuple[str, str]] = []
    ordered_nodes: list[str] = []
    for root in roots:
        if root.name not in ordered_nodes:
            ordered_nodes.append(root.name)
        for callee in _awaited_function_calls(root, functions):
            edges.append((root.name, callee))
            if callee not in ordered_nodes:
                ordered_nodes.append(callee)
    if format == "mermaid":
        lines = ["graph TD"]
        for name in ordered_nodes:
            lines.append(f'  {name}["{name} ({kinds.get(name, "helper")})"]')
        for source_name, target_name in edges:
            lines.append(f"  {source_name} --> {target_name}")
        if graph_state_names:
            graph_lines = _render_graph_tree(functions, kinds, graph_links, format=format).splitlines()
            for line in graph_lines[1:]:
                if line not in lines:
                    lines.append(line)
        return "\n".join(lines)
    if format != "text":
        raise ValueError(f"unsupported code tree format: {format}")
    lines: list[str] = []
    for root in roots:
        lines.append(f"{root.name} [{kinds[root.name]}]")
        for callee in _awaited_function_calls(root, functions):
            lines.append(f"  {callee} [{kinds.get(callee, 'helper')}]")
    if graph_state_names:
        graph_text = _render_graph_tree(functions, kinds, graph_links, format=format)
        if graph_text:
            lines.extend(graph_text.splitlines())
    return "\n".join(lines)


def _graph_transition_links(
    functions: dict[str, ast.AsyncFunctionDef | ast.FunctionDef],
) -> list[tuple[str, str, str]]:
    links: list[tuple[str, str, str]] = []
    for func in functions.values():
        if not isinstance(func, ast.AsyncFunctionDef) or not _has_decorator(func, "transition"):
            continue
        endpoints = _transition_decorator_endpoints(func)
        source = endpoints.get("src")
        target = endpoints.get("dst")
        if source and target and source in functions and target in functions:
            links.append((source, func.name, target))
    return links


def _render_graph_tree(
    functions: dict[str, ast.AsyncFunctionDef | ast.FunctionDef],
    kinds: dict[str, str],
    graph_links: list[tuple[str, str, str]],
    *,
    format: Literal["text", "mermaid"],
) -> str:
    outgoing: dict[str, list[tuple[str, str]]] = {}
    targets: set[str] = set()
    for source, transition_name, target in graph_links:
        outgoing.setdefault(source, []).append((transition_name, target))
        targets.add(target)
    source_names = {source for source, _, _ in graph_links}
    state_names = [name for name in functions if kinds.get(name) == "state"]
    roots = [
        name
        for name in functions
        if kinds.get(name) == "state" and name in source_names and name not in targets
    ]
    if not roots:
        roots = [name for name in state_names if name in source_names]
    if not roots:
        roots = [name for name in state_names if name not in targets] or state_names

    if format == "mermaid":
        ordered_nodes: list[str] = []
        mermaid_edges: list[tuple[str, str]] = []

        def add_node(name: str) -> None:
            if name not in ordered_nodes:
                ordered_nodes.append(name)

        def add_edge(source_name: str, target_name: str) -> None:
            edge = (source_name, target_name)
            if edge not in mermaid_edges:
                mermaid_edges.append(edge)

        def visit_state(name: str, seen: frozenset[str]) -> None:
            add_node(name)
            if name in seen:
                return
            for transition_name, target in outgoing.get(name, ()):
                add_node(transition_name)
                add_node(target)
                add_edge(name, transition_name)
                add_edge(transition_name, target)
                visit_state(target, seen | {name})

        for root in roots:
            visit_state(root, frozenset())
        lines = ["graph TD"]
        for name in ordered_nodes:
            lines.append(f'  {name}["{name} ({kinds.get(name, "helper")})"]')
        for source_name, target_name in mermaid_edges:
            lines.append(f"  {source_name} --> {target_name}")
        return "\n".join(lines)
    if format != "text":
        raise ValueError(f"unsupported code tree format: {format}")

    lines: list[str] = []

    def append_state(name: str, indent: int, seen: frozenset[str]) -> None:
        lines.append(f"{'  ' * indent}{name} [{kinds.get(name, 'state')}]")
        if name in seen:
            return
        for transition_name, target in outgoing.get(name, ()):
            lines.append(f"{'  ' * (indent + 1)}{transition_name} [{kinds.get(transition_name, 'transition')}]")
            append_state(target, indent + 2, seen | {name})

    for root in roots:
        append_state(root, 0, frozenset())
    return "\n".join(lines)


def _function_kind(func: ast.AsyncFunctionDef | ast.FunctionDef) -> str:
    if _has_decorator(func, "skill"):
        return "skill"
    if _has_decorator(func, "transition"):
        return "transition"
    if _has_decorator(func, "state"):
        return "state"
    if isinstance(func, ast.AsyncFunctionDef) and _contains_action_call(func):
        return "transition"
    return "helper"


def _contains_action_call(func: ast.AsyncFunctionDef) -> bool:
    return any(
        isinstance(node, ast.Call) and _call_name(node.func) == "action"
        for node in ast.walk(func)
    )


def _awaited_function_calls(
    func: ast.AsyncFunctionDef,
    functions: dict[str, ast.AsyncFunctionDef | ast.FunctionDef],
) -> list[str]:
    calls: list[str] = []
    for stmt in func.body:
        if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Await):
            continue
        call = stmt.value.value
        if not isinstance(call, ast.Call):
            continue
        call_name = _call_name(call.func)
        if call_name in functions and call_name not in calls:
            calls.append(call_name)
    return calls


def _graph_function_names(
    items: list[Any],
    *,
    prefix: str,
    id_getter: Callable[[Any], str],
) -> dict[str, str]:
    used: set[str] = set()
    names: dict[str, str] = {}
    for item in items:
        item_id = id_getter(item)
        source_ref = getattr(item, "source_ref", None)
        source_symbol = source_ref.get("symbol") if isinstance(source_ref, dict) else None
        base = _safe_identifier(str(source_symbol or f"{prefix}_{item_id}"))
        candidate = base
        index = 2
        while candidate in used:
            candidate = f"{base}_{index}"
            index += 1
        used.add(candidate)
        names[item_id] = candidate
    return names


def _generated_source_ref(symbol: str, kind: str, *, line: int) -> dict[str, Any]:
    return {
        "path": "skill_graph_code.py",
        "symbol": symbol,
        "line": line,
        "kind": kind,
    }


def _source_ref_from_function(
    func: ast.AsyncFunctionDef | ast.FunctionDef,
    kind: str,
) -> dict[str, Any]:
    return _generated_source_ref(func.name, kind, line=func.lineno)


def _graph_action_call_source(edge: GraphEdge) -> str:
    parts = [
        _code_literal(edge.action_type),
        f"target={_code_literal(edge.target)}",
    ]
    if edge.parameters:
        parts.append(f"parameters={_code_literal(edge.parameters)}")
    if edge.precondition:
        parts.append(f"state_contract=C.from_dict({_code_literal(edge.precondition)})")
    return f"await action({', '.join(parts)})"


def _state_contract_from_function(func: ast.FunctionDef) -> dict[str, Any] | None:
    for stmt in func.body:
        if isinstance(stmt, ast.Return):
            if stmt.value is None:
                return None
            if isinstance(stmt.value, ast.Constant) and stmt.value.value is None:
                return None
            return _contract_from_ast(stmt.value, {})
    return None


def _transition_decorator_info(func: ast.AsyncFunctionDef) -> dict[str, Any]:
    for decorator in func.decorator_list:
        if not isinstance(decorator, ast.Call) or _call_name(decorator.func) != "transition":
            continue
        info: dict[str, Any] = {}
        for kw in decorator.keywords:
            if kw.arg is None:
                continue
            if kw.arg in {"src", "dst"}:
                info[kw.arg] = _call_name(kw.value)
            else:
                info[kw.arg] = _literal_value(kw.value)
        return info
    return {}


def _transition_decorator_endpoints(func: ast.AsyncFunctionDef) -> dict[str, str]:
    for decorator in func.decorator_list:
        if not isinstance(decorator, ast.Call) or _call_name(decorator.func) != "transition":
            continue
        endpoints: dict[str, str] = {}
        for kw in decorator.keywords:
            if kw.arg in {"src", "dst"}:
                endpoints[kw.arg] = _call_name(kw.value)
        return endpoints
    return {}


def _stable_function_names(skills: list[Skill]) -> dict[str, str]:
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    for skill_obj in skills:
        base = _safe_identifier(skill_obj.name or skill_obj.skill_id or "skill")
        index = counts.get(base, 0)
        counts[base] = index + 1
        names[skill_obj.skill_id] = base if index == 0 else f"{base}_{index + 1}"
    return names


def _safe_identifier(value: str) -> str:
    name = re.sub(r"\W+", "_", value.strip()).strip("_").lower()
    if not name:
        name = "skill"
    if name[0].isdigit():
        name = f"skill_{name}"
    if keyword.iskeyword(name):
        name = f"{name}_skill"
    return name


def _parameter_placeholder_map(parameters: tuple[str, ...]) -> dict[str, str]:
    used: set[str] = {"device"}
    mapping: dict[str, str] = {}
    for parameter in parameters:
        raw = str(parameter)
        base = _safe_parameter_identifier(raw)
        candidate = base
        index = 2
        while candidate in used:
            candidate = f"{base}_{index}"
            index += 1
        used.add(candidate)
        mapping[raw] = candidate
    return mapping


def _safe_parameter_identifier(value: str) -> str:
    name = re.sub(r"\W+", "_", value.strip()).strip("_")
    if not name:
        name = "param"
    if name[0].isdigit():
        name = f"param_{name}"
    if keyword.iskeyword(name):
        name = f"{name}_"
    return name


def _rewrite_placeholders(value: Any, placeholder_map: dict[str, str]) -> Any:
    if isinstance(value, str):
        return re.sub(
            r"\{\{([^{}]+)\}\}",
            lambda match: "{{" + placeholder_map.get(match.group(1), match.group(1)) + "}}",
            value,
        )
    if isinstance(value, dict):
        return {
            key: _rewrite_placeholders(item, placeholder_map)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(_rewrite_placeholders(item, placeholder_map) for item in value)
    if isinstance(value, list):
        return [_rewrite_placeholders(item, placeholder_map) for item in value]
    return value


def _action_call_source(step: SkillStep, placeholder_map: dict[str, str]) -> str:
    parts = [
        _code_literal(step.action_type),
        f"target={_code_literal(_rewrite_placeholders(step.target, placeholder_map))}",
    ]
    for key in sorted(step.parameters):
        value = _rewrite_placeholders(step.parameters[key], placeholder_map)
        parts.append(f"{key}={_code_literal(value)}")
    if step.expected_state is not None:
        expected_state = _rewrite_placeholders(step.expected_state, placeholder_map)
        parts.append(f"expected_state={_code_literal(expected_state)}")
    if step.valid_state is not None:
        valid_state = _rewrite_placeholders(step.valid_state, placeholder_map)
        parts.append(f"valid_state={_code_literal(valid_state)}")
    if step.state_contract:
        contract = normalize_state_contract(step.state_contract)
        contract = _rewrite_placeholders(contract, placeholder_map)
        parts.append(f"state_contract=C.from_dict({_code_literal(contract)})")
    if step.fixed:
        parts.append("fixed=True")
    if step.fixed_values:
        fixed_values = _rewrite_placeholders(step.fixed_values, placeholder_map)
        parts.append(f"fixed_values={_code_literal(fixed_values)}")
    return f"await action({', '.join(parts)})"


def _code_literal(value: Any) -> str:
    return pprint.pformat(_sort_jsonish(value), width=88, sort_dicts=True)


def _sort_jsonish(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sort_jsonish(value[key]) for key in sorted(value)}
    if isinstance(value, tuple):
        return [_sort_jsonish(item) for item in value]
    if isinstance(value, list):
        return [_sort_jsonish(item) for item in value]
    return value
