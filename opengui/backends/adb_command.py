
"""Whitelisted parameterized ADB command-skill execution."""

from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any, Awaitable, Callable

from opengui.action import Action

RunAdb = Callable[..., Awaitable[str]]
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)(?::([A-Za-z0-9_*]+))?\s*\}\}")
_SAFE_INT_LIST_RE = re.compile(r"^[0-9]+(?:,[0-9]+)*$")


class AdbCommandError(RuntimeError):
    """Raised when a whitelisted adb command skill fails."""


class AdbCommandRunner:
    """Execute registry-defined ADB command skills without accepting raw shell."""

    def __init__(self, run_adb: RunAdb, *, registry_path: str | Path | None = None) -> None:
        self._run_adb = run_adb
        self._registry_path = Path(registry_path).expanduser() if registry_path else None
        self._registry: dict[str, dict[str, Any]] | None = None

    async def execute(self, action: Action, *, timeout: float) -> str:
        command_id = (action.command_id or action.text or "").strip()
        if not command_id:
            raise ValueError("adb_command action requires command_id or text")
        skill = self._load_registry().get(command_id)
        if skill is None:
            raise ValueError(f"Unknown adb command skill: {command_id}")
        params = self._prepare_params(skill, action)
        executor = skill.get("executor") or {}
        output = await self._execute_executor(executor, params, timeout=timeout)
        verifier = skill.get("verifier")
        if skill.get("kind") == "write" and verifier:
            await self._verify(verifier, params, timeout=timeout)
        return f"adb_command {command_id} succeeded" + (f"\n{output}" if output else "")

    def _load_registry(self) -> dict[str, dict[str, Any]]:
        if self._registry is not None:
            return self._registry
        path = self._registry_path or _find_registry_path()
        if path is None:
            raise FileNotFoundError(
                "ADB command skill registry not found. Set OPENGUI_ADB_COMMAND_SKILLS_PATH."
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        self._registry = {str(item["id"]): item for item in data.get("skills", [])}
        return self._registry

    def _prepare_params(self, skill: dict[str, Any], action: Action) -> dict[str, Any]:
        raw: dict[str, Any] = dict(action.params or {})
        for key, value in action.extras:
            raw.setdefault(str(key), value)
        schema = skill.get("params") or {}
        params: dict[str, Any] = {}
        for name, spec in schema.items():
            if name in raw:
                params[name] = _coerce_param(name, raw[name], spec)
            elif "default" in spec:
                params[name] = spec["default"]
            elif spec.get("required"):
                raise ValueError(f"adb command {skill.get('id')} missing required param {name!r}")
        for name, value in raw.items():
            if name not in params:
                params[name] = value
        _add_derived_params(params)
        _validate_param_constraints(params, schema)
        return params

    async def _execute_executor(self, executor: dict[str, Any], params: dict[str, Any], *, timeout: float) -> str:
        kind = executor.get("type")
        if kind == "adb_template":
            if "templates" in executor:
                enabled = bool(params.get("enabled"))
                template = executor["templates"]["enabled_true" if enabled else "enabled_false"]
            else:
                template = str(executor.get("template") or "")
            return await self._run_adb_template(template, params, timeout=timeout, root=bool(executor.get("root_required")))
        if kind == "adb_sequence":
            if executor.get("root_required"):
                await self._try_root(timeout=timeout)
            outputs: list[str] = []
            for step in executor.get("steps") or []:
                if not _condition_passes(str(step.get("condition") or ""), params):
                    continue
                outputs.append(await self._run_adb_template(str(step.get("template") or ""), params, timeout=timeout))
            return "\n".join(part for part in outputs if part)
        if kind == "adb_sqlite":
            sql = _render_template(str(executor.get("sql_template") or ""), params)
            db_path = str(executor.get("db_path") or "")
            return await self._run_sqlite(db_path, sql, timeout=timeout)
        if kind == "python_helper":
            raise ValueError("python_helper adb command skills are not enabled in the OpenGUI backend")
        raise ValueError(f"Unsupported adb command executor type: {kind!r}")

    async def _verify(self, verifier: dict[str, Any], params: dict[str, Any], *, timeout: float) -> None:
        kind = verifier.get("type")
        if kind == "skill_ref":
            ref = str(verifier.get("skill_id") or "")
            if not ref:
                raise ValueError("skill_ref verifier missing skill_id")
            verify_params = dict(params)
            if ref == "files.unzip_list" and "archive_path" not in verify_params:
                directory = str(verify_params.get("directory") or "").rstrip("/")
                archive = str(verify_params.get("archive_name") or "")
                verify_params["archive_path"] = f"{directory}/{archive}"
            if ref == "media.query_image_path" and "image_name" not in verify_params:
                verify_params["image_name"] = Path(str(verify_params.get("path") or "")).name
            output = await self._execute_executor(self._load_registry()[ref].get("executor") or {}, verify_params, timeout=timeout)
            if not output.strip():
                raise AdbCommandError(f"adb command verifier {ref} returned empty output")
            return
        if kind == "adb_template":
            output = await self._run_adb_template(str(verifier.get("template") or ""), params, timeout=timeout)
            success = str(verifier.get("success") or "").lower()
            if "stdout is empty" in success and output.strip():
                raise AdbCommandError(f"adb command verifier expected empty stdout, got: {output}")
            if "equals '1'" in success:
                expected = "1" if bool(params.get("enabled")) else "0"
                if output.strip() != expected:
                    raise AdbCommandError(f"adb command verifier expected {expected}, got: {output}")
            return

    async def _run_adb_template(self, template: str, params: dict[str, Any], *, timeout: float, root: bool = False) -> str:
        if not template.strip():
            raise ValueError("empty adb command template")
        if root:
            await self._try_root(timeout=timeout)
        return await self._run_adb_string(_render_template(template, params), timeout=timeout)

    async def _run_adb_string(self, command: str, *, timeout: float) -> str:
        parts = shlex.split(command)
        if not parts:
            raise ValueError("empty adb command")
        if parts[0] == "adb":
            parts = parts[1:]
        if not parts:
            raise ValueError("adb command has no arguments")
        return await self._run_adb(*parts, timeout=timeout)

    async def _run_sqlite(self, db_path: str, sql: str, *, timeout: float) -> str:
        if not db_path or not sql:
            raise ValueError("adb_sqlite requires db_path and sql")
        commands = [
            f"adb shell su 0 sqlite3 {shlex.quote(db_path)} {shlex.quote(sql)}",
            f"adb shell su root sqlite3 {shlex.quote(db_path)} {shlex.quote(sql)}",
        ]
        errors: list[str] = []
        for command in commands:
            try:
                output = await self._run_adb_string(command, timeout=timeout)
            except Exception as exc:
                errors.append(str(exc))
                continue
            if "error" not in output.lower():
                return output
        raise AdbCommandError("adb sqlite command failed: " + " | ".join(errors))

    async def _try_root(self, *, timeout: float) -> None:
        try:
            await self._run_adb("root", timeout=timeout)
        except Exception:
            # Some images keep shell root via su even when `adb root` is noisy.
            pass


def _find_registry_path() -> Path | None:
    env_path = os.getenv("OPENGUI_ADB_COMMAND_SKILLS_PATH", "").strip()
    if env_path:
        path = Path(env_path).expanduser()
        if path.exists():
            return path
    candidates: list[Path] = []
    cwd = Path.cwd()
    for root in (cwd, *cwd.parents):
        candidates.append(root / "configs" / "adb_command_skills.mobileworld.json")
    for key in ("GUI_CLAW_PATH", "OPENGUI_WORKSPACE", "NANOBOT_WORKSPACE"):
        value = os.getenv(key, "").strip()
        if value:
            candidates.append(Path(value).expanduser() / "configs" / "adb_command_skills.mobileworld.json")
    for path in candidates:
        if path.exists():
            return path
    return None


def _coerce_param(name: str, value: Any, spec: dict[str, Any]) -> Any:
    typ = spec.get("type")
    if typ == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True
            if lowered in {"false", "0", "no", "off"}:
                return False
        raise ValueError(f"param {name!r} must be boolean")
    if typ == "integer":
        return int(value)
    if typ == "array":
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        if isinstance(value, (list, tuple)):
            return list(value)
        raise ValueError(f"param {name!r} must be array")
    if typ in {"string", "path", "filename", "string_or_integer"}:
        return value if typ == "string_or_integer" and isinstance(value, int) else str(value)
    return value


def _add_derived_params(params: dict[str, Any]) -> None:
    days_csv = str(params.get("days_csv") or "").strip()
    if days_csv:
        if not _SAFE_INT_LIST_RE.match(days_csv):
            raise ValueError("days_csv must contain only comma-separated integers")
        params["days_arg"] = f"--eia android.intent.extra.alarm.DAYS {days_csv}"
    else:
        params["days_arg"] = ""
    if params.get("hour") not in (None, "") and params.get("minute") not in (None, ""):
        params["where_hour_minute"] = f"WHERE hour={int(params['hour'])} AND minutes={int(params['minute'])}"
    else:
        params["where_hour_minute"] = ""


def _validate_param_constraints(params: dict[str, Any], schema: dict[str, Any]) -> None:
    for name, spec in schema.items():
        if name not in params:
            continue
        value = params[name]
        if spec.get("type") == "integer":
            if "minimum" in spec and int(value) < int(spec["minimum"]):
                raise ValueError(f"param {name!r} below minimum")
            if "maximum" in spec and int(value) > int(spec["maximum"]):
                raise ValueError(f"param {name!r} above maximum")
        if spec.get("type") == "filename":
            text = str(value)
            if not text or "/" in text or "\x00" in text or text in {".", ".."}:
                raise ValueError(f"unsafe filename param {name!r}: {text!r}")
        prefixes = spec.get("allowed_prefixes") or []
        if prefixes:
            values = value if isinstance(value, list) else [value]
            for item in values:
                text = str(item)
                if "\x00" in text or "/../" in text or text.endswith("/.."):
                    raise ValueError(f"unsafe path param {name!r}: {text!r}")
                if not any(text == prefix or text.startswith(str(prefix).rstrip("/") + "/") for prefix in prefixes):
                    raise ValueError(f"path param {name!r} outside allowed prefixes: {text!r}")


def _render_template(template: str, params: dict[str, Any]) -> str:
    def repl(match: re.Match[str]) -> str:
        name, fmt = match.group(1), match.group(2) or ""
        if name not in params:
            raise ValueError(f"template references missing param {name!r}")
        value = params[name]
        if fmt == "q":
            return shlex.quote(str(value))
        if fmt == "q*":
            if not isinstance(value, (list, tuple)):
                raise ValueError(f"template param {name!r} must be a list for q*")
            return " ".join(shlex.quote(str(item)) for item in value)
        if fmt == "bool":
            return "true" if bool(value) else "false"
        return str(value)
    return _PLACEHOLDER_RE.sub(repl, template)


def _condition_passes(condition: str, params: dict[str, Any]) -> bool:
    if not condition:
        return True
    normalized = condition.strip().lower()
    if normalized == "delete_sources == true":
        return bool(params.get("delete_sources"))
    raise ValueError(f"unsupported adb command condition: {condition}")
