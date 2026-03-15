"""Local desktop backends and computer-use action helpers."""

from __future__ import annotations

import base64
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.gui import _pyautogui


class GUIBackendError(RuntimeError):
    """Raised when the GUI backend cannot complete an operation."""


@dataclass(frozen=True)
class ComputerAction:
    """Validated desktop action."""

    action_type: str
    x: float | None = None
    y: float | None = None
    x2: float | None = None
    y2: float | None = None
    text: str | None = None
    key: tuple[str, ...] = ()
    pixels: int | None = None
    duration_ms: int | None = None
    relative: bool = False
    status: str | None = None


@dataclass(frozen=True)
class DesktopObservation:
    """A desktop observation captured from the current screen."""

    screenshot_path: str
    screen_width: int
    screen_height: int
    foreground_app: str | None = None
    accessibility_tree: str | None = None

    def to_user_text(self, task: str, *, step_index: int, app_hint: str | None = None) -> str:
        """Build compact text context for the next multimodal user turn."""
        lines = [
            f"Task: {task}",
            f"Step: {step_index}",
            f"Current app: {self.foreground_app or 'Unknown'}",
            f"Screen size: {self.screen_width}x{self.screen_height}",
            "Prefer absolute pixel coordinates with relative=false.",
        ]
        if app_hint:
            lines.append(f"Target app hint: {app_hint}")
        return "\n".join(lines)


_ONE_BY_ONE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9M2VYAAAAASUVORK5CYII="
)

_ACTION_ALIASES = {
    "click": "tap",
    "left_click": "tap",
    "mouse_move": "move",
    "drag": "swipe",
    "type": "input_text",
    "key": "hotkey",
}
_SUPPORTED_ACTIONS = {
    "tap",
    "move",
    "right_click",
    "middle_click",
    "double_click",
    "triple_click",
    "swipe",
    "scroll",
    "hscroll",
    "input_text",
    "hotkey",
    "wait",
    "terminate",
}


def _parse_relative(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _parse_number(value: Any, *, field: str, relative: bool) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GUIBackendError(f"{field} must be numeric") from exc
    if relative:
        if not 0.0 <= number <= 999.0:
            raise GUIBackendError(f"{field} must be in [0, 999] when relative=true")
    elif number < 0.0:
        raise GUIBackendError(f"{field} must be non-negative")
    return number


def _parse_key_spec(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        raw = [part.strip() for part in value.split("+")] if "+" in value else [value.strip()]
    elif isinstance(value, (list, tuple)):
        raw = [str(part).strip() for part in value]
    else:
        raw = []
    keys = tuple(part.lower() for part in raw if part)
    if not keys:
        raise GUIBackendError("hotkey action requires a non-empty key")
    return _pyautogui.normalize_keys(keys)


def _parse_duration_ms(value: Any, *, field: str, default: int) -> int:
    if value is None:
        return default
    try:
        duration = int(float(value))
    except (TypeError, ValueError) as exc:
        raise GUIBackendError(f"{field} must be numeric") from exc
    return max(0, duration)


def parse_computer_action(payload: dict[str, Any]) -> ComputerAction:
    """Validate and normalize a computer-use action payload."""
    if not isinstance(payload, dict):
        raise GUIBackendError("computer_use arguments must be an object")

    action_type = str(payload.get("action_type", "")).strip().lower()
    if not action_type:
        raise GUIBackendError("computer_use requires action_type")
    action_type = _ACTION_ALIASES.get(action_type, action_type)
    if action_type not in _SUPPORTED_ACTIONS:
        raise GUIBackendError(f"Unsupported computer_use action_type: {action_type}")

    relative = _parse_relative(payload.get("relative"), default=False)
    x = y = x2 = y2 = None
    text = None
    key: tuple[str, ...] = ()
    pixels = None
    duration_ms = None
    status = None

    if action_type in {
        "tap",
        "move",
        "right_click",
        "middle_click",
        "double_click",
        "triple_click",
    }:
        x = _parse_number(payload.get("x"), field="x", relative=relative)
        y = _parse_number(payload.get("y"), field="y", relative=relative)
    elif action_type == "swipe":
        x = _parse_number(payload.get("x"), field="x", relative=relative)
        y = _parse_number(payload.get("y"), field="y", relative=relative)
        x2 = _parse_number(payload.get("x2"), field="x2", relative=relative)
        y2 = _parse_number(payload.get("y2"), field="y2", relative=relative)
        duration_ms = _parse_duration_ms(payload.get("duration_ms"), field="duration_ms", default=500)
    elif action_type == "input_text":
        text = str(payload.get("text", ""))
        if not text:
            raise GUIBackendError("input_text action requires non-empty text")
    elif action_type == "hotkey":
        key = _parse_key_spec(payload.get("key"))
    elif action_type in {"scroll", "hscroll"}:
        try:
            pixels = int(float(payload.get("pixels", 0)))
        except (TypeError, ValueError) as exc:
            raise GUIBackendError(f"{action_type} action requires numeric pixels") from exc
        if pixels == 0:
            raise GUIBackendError(f"{action_type} action requires non-zero pixels")
    elif action_type == "wait":
        duration_ms = _parse_duration_ms(payload.get("duration_ms"), field="duration_ms", default=1000)
    elif action_type == "terminate":
        status = str(payload.get("status", "success")).strip().lower() or "success"
        if status not in {"success", "failure"}:
            raise GUIBackendError("terminate status must be success or failure")

    return ComputerAction(
        action_type=action_type,
        x=x,
        y=y,
        x2=x2,
        y2=y2,
        text=text,
        key=key,
        pixels=pixels,
        duration_ms=duration_ms,
        relative=relative,
        status=status,
    )


def describe_action(action: ComputerAction) -> str:
    """Return a compact human-readable action summary."""
    if action.action_type in {
        "tap",
        "move",
        "right_click",
        "middle_click",
        "double_click",
        "triple_click",
    }:
        return f"{action.action_type} @ ({int(action.x or 0)}, {int(action.y or 0)})"
    if action.action_type == "swipe":
        return (
            f"swipe ({int(action.x or 0)}, {int(action.y or 0)})"
            f" -> ({int(action.x2 or 0)}, {int(action.y2 or 0)})"
        )
    if action.action_type == "input_text" and action.text is not None:
        preview = action.text if len(action.text) <= 40 else f"{action.text[:37]}..."
        return f'input_text "{preview}"'
    if action.action_type == "hotkey" and action.key:
        return f"hotkey {'+'.join(action.key)}"
    if action.action_type in {"scroll", "hscroll"}:
        return f"{action.action_type} {action.pixels}"
    if action.action_type == "wait":
        seconds = (action.duration_ms or 0) / 1000
        return f"wait {seconds:.1f}s"
    if action.action_type == "terminate":
        return f"terminate ({action.status})"
    return action.action_type


class LocalDesktopBackend:
    """Synchronous macOS desktop backend."""

    # Dangerous shortcuts blocked by default to avoid accidental termination.
    _DANGEROUS_KEY_COMBOS: frozenset[tuple[str, ...]] = frozenset({
        ("command", "w"), # close the current window
        ("command", "backspace"), # delete the entire line in many apps
        ("command", "shift", "backspace"), # "force delete" in many apps
        ("command", "option", "esc"), # open the Force Quit menu
        ("command", "ctrl", "q"), # log out of the current user session
        ("command", "q"), # quit the current app
    })

    def __init__(self) -> None:
        self._screen_width: int | None = None
        self._screen_height: int | None = None

    def preflight(self, artifacts_dir: Path, timeout_seconds: int) -> list[str]:
        """Validate the backend can capture the current desktop."""
        errors: list[str] = []
        if platform.system() != "Darwin":
            errors.append("Local GUI backend currently supports macOS only.")
        if not _pyautogui.is_available():
            errors.append(
                "pyautogui GUI support is unavailable. Install nanobot with the gui_macos extra."
            )

        try:
            shot = artifacts_dir / ".preflight.png"
            self._capture_screenshot(shot, timeout_seconds)
            if shot.exists():
                shot.unlink()
        except Exception as exc:
            errors.append(f"Unable to capture the screen: {exc}")

        try:
            self._screen_width, self._screen_height = self._get_screen_size(timeout_seconds)
        except Exception as exc:
            errors.append(f"Unable to read the screen size: {exc}")

        try:
            _ = self._get_foreground_app(timeout_seconds)
        except Exception as exc:
            errors.append(f"Unable to read the foreground app: {exc}")

        return errors

    def observe(self, output_path: Path, timeout_seconds: int) -> DesktopObservation:
        """Capture a fresh screenshot and current desktop metadata."""
        self._capture_screenshot(output_path, timeout_seconds)
        width, height = self._get_screen_size(timeout_seconds)
        self._screen_width, self._screen_height = width, height
        # Retina screenshots are captured at physical resolution while pyautogui
        # works in logical points. Resizing keeps the screenshot coordinate space aligned.
        self._downscale_to_logical(output_path, width, height, timeout_seconds)
        foreground = self._get_foreground_app(timeout_seconds)
        return DesktopObservation(
            screenshot_path=str(output_path),
            screen_width=width,
            screen_height=height,
            foreground_app=foreground,
        )

    def execute_action(self, action: ComputerAction, timeout_seconds: int) -> str:
        """Execute one validated desktop action."""
        if action.action_type == "hotkey" and action.key:
            if warning := self._check_dangerous_keys(action.key):
                raise GUIBackendError(warning)

        if action.action_type == "tap":
            x, y = self._resolve_point(action.x, action.y, relative=action.relative, timeout_seconds=timeout_seconds)
            _pyautogui.click(x, y)
            return f"Executed {describe_action(action)}"
        if action.action_type == "move":
            x, y = self._resolve_point(action.x, action.y, relative=action.relative, timeout_seconds=timeout_seconds)
            _pyautogui.move(x, y)
            return f"Executed {describe_action(action)}"
        if action.action_type == "right_click":
            x, y = self._resolve_point(action.x, action.y, relative=action.relative, timeout_seconds=timeout_seconds)
            _pyautogui.right_click(x, y)
            return f"Executed {describe_action(action)}"
        if action.action_type == "middle_click":
            x, y = self._resolve_point(action.x, action.y, relative=action.relative, timeout_seconds=timeout_seconds)
            _pyautogui.middle_click(x, y)
            return f"Executed {describe_action(action)}"
        if action.action_type == "double_click":
            x, y = self._resolve_point(action.x, action.y, relative=action.relative, timeout_seconds=timeout_seconds)
            _pyautogui.double_click(x, y)
            return f"Executed {describe_action(action)}"
        if action.action_type == "triple_click":
            x, y = self._resolve_point(action.x, action.y, relative=action.relative, timeout_seconds=timeout_seconds)
            _pyautogui.triple_click(x, y)
            return f"Executed {describe_action(action)}"
        if action.action_type == "swipe":
            x1, y1 = self._resolve_point(action.x, action.y, relative=action.relative, timeout_seconds=timeout_seconds)
            x2, y2 = self._resolve_point(action.x2, action.y2, relative=action.relative, timeout_seconds=timeout_seconds)
            _pyautogui.drag(x1, y1, x2, y2, duration_ms=action.duration_ms or 500)
            return f"Executed {describe_action(action)}"
        if action.action_type == "input_text" and action.text is not None:
            _pyautogui.type_text(action.text)
            return f"Executed {describe_action(action)}"
        if action.action_type == "hotkey" and action.key:
            _pyautogui.press_keys(action.key)
            return f"Executed {describe_action(action)}"
        if action.action_type == "scroll" and action.pixels is not None:
            _pyautogui.scroll("up" if action.pixels > 0 else "down", pixels=abs(action.pixels))
            return f"Executed {describe_action(action)}"
        if action.action_type == "hscroll" and action.pixels is not None:
            _pyautogui.scroll("right" if action.pixels > 0 else "left", pixels=abs(action.pixels))
            return f"Executed {describe_action(action)}"
        if action.action_type == "wait":
            time.sleep((action.duration_ms or 0) / 1000)
            return f"Executed {describe_action(action)}"
        if action.action_type == "terminate":
            return f"Terminated with status={action.status}"
        raise GUIBackendError(f"Unsupported action execution path: {action.action_type}")

    def _run_command(
        self,
        command: list[str],
        *,
        timeout_seconds: int,
        text: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=text,
                check=False,
                timeout=timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise GUIBackendError(f"Command not available: {command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise GUIBackendError(f"Command timed out: {' '.join(command)}") from exc

    def _run_osascript(self, script: str, timeout_seconds: int) -> str:
        result = self._run_command(
            ["osascript", "-e", script],
            timeout_seconds=timeout_seconds,
        )
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            raise GUIBackendError(stderr or "osascript failed")
        return (result.stdout or "").strip()

    def _capture_screenshot(self, output_path: Path, timeout_seconds: int) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if _pyautogui.is_available():
            try:
                _pyautogui.capture_screenshot(output_path)
                if output_path.exists():
                    return
            except Exception as exc:
                logger.debug("pyautogui screenshot failed, falling back to screencapture: {}", exc)

        result = self._run_command(
            ["screencapture", "-x", str(output_path)],
            timeout_seconds=timeout_seconds,
        )
        if result.returncode != 0 or not output_path.exists():
            stderr = (result.stderr or result.stdout or "").strip()
            raise GUIBackendError(stderr or "screencapture failed")

    def _downscale_to_logical(
        self,
        image_path: Path,
        logical_width: int,
        logical_height: int,
        timeout_seconds: int,
    ) -> None:
        """Resize a Retina screenshot to logical resolution using sips.

        If this fails the screenshot stays at physical (2x) resolution while
        coordinates remain in logical points, which can cause click misalignment.
        """
        try:
            result = self._run_command(
                [
                    "sips",
                    "--resampleWidth",
                    str(logical_width),
                    "--resampleHeight",
                    str(logical_height),
                    str(image_path),
                ],
                timeout_seconds=timeout_seconds,
            )
            if result.returncode != 0:
                stderr = (result.stderr or result.stdout or "").strip()
                logger.warning(
                    "sips downscale failed (rc={}); screenshot may be at physical resolution: {}",
                    result.returncode,
                    stderr,
                )
        except GUIBackendError as exc:
            logger.warning("sips downscale failed; screenshot may be at physical resolution: {}", exc)

    def _get_screen_size(self, timeout_seconds: int) -> tuple[int, int]:
        if _pyautogui.is_available():
            try:
                return _pyautogui.size()
            except Exception as exc:
                logger.debug("pyautogui.size() failed, falling back to Finder bounds: {}", exc)

        script = 'tell application "Finder" to get bounds of window of desktop'
        stdout = self._run_osascript(script, timeout_seconds)
        numbers = [int(v) for v in re.findall(r"-?\d+", stdout)]
        if len(numbers) < 4:
            raise GUIBackendError("Unable to parse the desktop bounds")
        width = max(1, numbers[2] - numbers[0])
        height = max(1, numbers[3] - numbers[1])
        return (width, height)

    def _get_foreground_app(self, timeout_seconds: int) -> str | None:
        script = (
            'tell application "System Events" to get name of first application process '
            "whose frontmost is true"
        )
        stdout = self._run_osascript(script, timeout_seconds)
        return stdout or None

    @classmethod
    def _check_dangerous_keys(cls, keys: tuple[str, ...]) -> str | None:
        """Return an error message if *keys* form a dangerous shortcut."""
        normalized = _pyautogui.normalize_keys(keys)
        if normalized in cls._DANGEROUS_KEY_COMBOS:
            return f"Blocked dangerous shortcut: {'+'.join(keys)}"
        return None

    def _ensure_screen_size(self, timeout_seconds: int) -> tuple[int, int]:
        if self._screen_width is None or self._screen_height is None:
            self._screen_width, self._screen_height = self._get_screen_size(timeout_seconds)
        return self._screen_width, self._screen_height

    def _resolve_point(
        self,
        x: float | None,
        y: float | None,
        *,
        relative: bool,
        timeout_seconds: int,
    ) -> tuple[int, int]:
        if x is None or y is None:
            raise GUIBackendError("Action requires x and y coordinates")
        width, height = self._ensure_screen_size(timeout_seconds)
        return (
            self._resolve_axis(x, width, relative=relative),
            self._resolve_axis(y, height, relative=relative),
        )

    @staticmethod
    def _resolve_axis(value: float, extent: int, *, relative: bool) -> int:
        if relative:
            return max(0, min(extent - 1, int(round((value / 999.0) * (extent - 1)))))
        return max(0, min(extent - 1, int(round(value))))


class DryRunDesktopBackend:
    """Deterministic no-op backend for tests and non-macOS development."""

    def __init__(self) -> None:
        self._foreground_app = "DryRun Desktop"
        self._screen_width = 1440
        self._screen_height = 900

    def preflight(self, artifacts_dir: Path, timeout_seconds: int) -> list[str]:
        del artifacts_dir, timeout_seconds
        return []

    def observe(self, output_path: Path, timeout_seconds: int) -> DesktopObservation:
        del timeout_seconds
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(_ONE_BY_ONE_PNG)
        return DesktopObservation(
            screenshot_path=str(output_path),
            screen_width=self._screen_width,
            screen_height=self._screen_height,
            foreground_app=self._foreground_app,
        )

    def execute_action(self, action: ComputerAction, timeout_seconds: int) -> str:
        del timeout_seconds
        return f"[dry-run] {describe_action(action)}"
