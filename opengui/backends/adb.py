"""
opengui.backends.adb
~~~~~~~~~~~~~~~~~~~~
Android Debug Bridge backend for device and emulator automation.

Unicode text input prefers ADBKeyboard IME on the target device:
    adb shell ime set com.android.adbkeyboard/.AdbIME

If ADBKeyboard is unavailable, OpenGUI falls back to a device-side `yadb`
helper when it is installed at `/data/local/tmp/yadb`.

All I/O is non-blocking via asyncio.create_subprocess_exec.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.resources
import re
from pathlib import Path

from opengui.action import Action, describe_action, resolve_coordinate
from opengui.observation import Observation

# ---------------------------------------------------------------------------
# Keycode mapping
# ---------------------------------------------------------------------------

_KEYCODE_MAP: dict[str, str] = {
    "home": "KEYCODE_HOME",
    "back": "KEYCODE_BACK",
    "enter": "KEYCODE_ENTER",
    "return": "KEYCODE_ENTER",
    "tab": "KEYCODE_TAB",
    "delete": "KEYCODE_DEL",
    "backspace": "KEYCODE_DEL",
    "volumeup": "KEYCODE_VOLUME_UP",
    "volume_up": "KEYCODE_VOLUME_UP",
    "volumedown": "KEYCODE_VOLUME_DOWN",
    "volume_down": "KEYCODE_VOLUME_DOWN",
    "power": "KEYCODE_POWER",
    "menu": "KEYCODE_MENU",
    "recents": "KEYCODE_APP_SWITCH",
    "app_switch": "KEYCODE_APP_SWITCH",
    "escape": "KEYCODE_ESCAPE",
    "space": "KEYCODE_SPACE",
    "search": "KEYCODE_SEARCH",
    "camera": "KEYCODE_CAMERA",
    "left": "KEYCODE_DPAD_LEFT",
    "right": "KEYCODE_DPAD_RIGHT",
    "up": "KEYCODE_DPAD_UP",
    "down": "KEYCODE_DPAD_DOWN",
}

_WM_SIZE_RE = re.compile(r"Physical size:\s*(\d+)x(\d+)", re.IGNORECASE)
_RESUMED_ACTIVITY_RE = re.compile(
    r"mResumedActivity.*?"
    r"([a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z][a-zA-Z0-9_]*)+)/",
    re.IGNORECASE,
)

_DEVICE_SCREENSHOT_PATH = "/sdcard/__opengui_cap.png"
_ADB_KEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"
_YADB_PATH = "/data/local/tmp/yadb"
_YADB_MAIN_CLASS = "com.ysbing.yadb.Main"


class AdbError(Exception):
    """Raised when an adb command fails."""

    def __init__(self, message: str, returncode: int | None = None, stderr: str = "") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


def _escape_shell_text(text: str) -> str:
    """Escape text for ``adb shell input text``."""
    # Android's `input text` command treats `%s` as a space placeholder.
    # We are not invoking a shell here, so `\ ` would be passed literally and
    # can cause whitespace truncation on device-side parsing.
    _SPECIAL = frozenset(r'\`$"!&|<>(){}[];#~*?^')
    escaped: list[str] = []
    for ch in text:
        if ch == " ":
            escaped.append("%s")
        elif ch in _SPECIAL:
            escaped.append("\\" + ch)
        else:
            escaped.append(ch)
    return "".join(escaped)


def _is_ascii_safe(text: str) -> bool:
    return all(ord(ch) < 128 for ch in text)


def _to_b64_text(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class AdbBackend:
    """ADB backend for Android device/emulator automation.

    Args:
        serial: Device serial (e.g. "emulator-5554"). None = default device.
        adb_path: Path to adb binary.
    """

    def __init__(self, serial: str | None = None, adb_path: str = "adb") -> None:
        self._serial = serial
        self._adb = adb_path
        self._screen_width = 1080
        self._screen_height = 1920

    @property
    def platform(self) -> str:
        return "android"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_cmd(self, *args: str) -> list[str]:
        cmd: list[str] = [self._adb]
        if self._serial:
            cmd += ["-s", self._serial]
        cmd += list(args)
        return cmd

    async def _run(self, *args: str, timeout: float = 10.0) -> str:
        cmd = self._build_cmd(*args)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            raise TimeoutError(f"adb timed out after {timeout}s: {' '.join(cmd)}")

        stdout = stdout_bytes.decode(errors="replace").strip()
        stderr = stderr_bytes.decode(errors="replace").strip()
        if proc.returncode != 0:
            raise AdbError(
                f"adb failed (exit {proc.returncode}): {' '.join(cmd)}"
                + (f"\nstderr: {stderr}" if stderr else ""),
                returncode=proc.returncode,
                stderr=stderr,
            )
        return stdout

    # ------------------------------------------------------------------
    # Preflight
    # ------------------------------------------------------------------

    async def preflight(self) -> None:
        cmd = [self._adb, "devices"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        except asyncio.TimeoutError:
            raise AdbError("'adb devices' timed out during preflight")

        output = stdout_bytes.decode(errors="replace")
        device_lines = [
            line for line in output.splitlines()
            if "\t" in line and not line.startswith("List of")
        ]

        if self._serial:
            for line in device_lines:
                parts = line.split("\t", 1)
                if len(parts) == 2 and parts[0].strip() == self._serial:
                    if parts[1].strip() != "device":
                        raise AdbError(
                            f"Device {self._serial!r} in state {parts[1].strip()!r}, "
                            "not 'device'. Check authorisation."
                        )
                    return
            raise AdbError(f"Device {self._serial!r} not found in 'adb devices'.")
        else:
            ready = [l for l in device_lines if l.split("\t", 1)[-1].strip() == "device"]
            if not ready:
                raise AdbError("No Android device found. Connect a device or start an emulator.")

    # ------------------------------------------------------------------
    # App discovery
    # ------------------------------------------------------------------

    async def list_apps(self) -> list[str]:
        """Return package names of launchable apps on the device.

        Fetches third-party packages (``pm list packages -3``) and merges a
        small set of commonly-used system packages so the LLM can resolve
        human-readable names like "Settings" to ``com.android.settings``.
        """
        _COMMON_SYSTEM_PACKAGES = [
            "com.android.settings",
            "com.android.contacts",
            "com.android.dialer",
            "com.android.mms",
            "com.android.camera2",
            "com.android.gallery3d",
            "com.android.calculator2",
            "com.android.calendar",
            "com.android.deskclock",
            "com.android.documentsui",
            "com.android.vending",
            "com.google.android.apps.messaging",
            "com.google.android.apps.photos",
            "com.google.android.gm",
            "com.google.android.googlequicksearchbox",
            "com.google.android.youtube",
            "com.google.android.apps.maps",
            "com.google.android.dialer",
            "com.google.android.contacts",
            "com.google.android.calendar",
        ]
        try:
            output = await self._run("shell", "pm", "list", "packages", "-3", timeout=10.0)
        except (AdbError, TimeoutError):
            return list(_COMMON_SYSTEM_PACKAGES)

        packages: list[str] = []
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                packages.append(line[len("package:"):])
        # Merge common system packages (deduplicated, order preserved)
        seen = set(packages)
        for pkg in _COMMON_SYSTEM_PACKAGES:
            if pkg not in seen:
                packages.append(pkg)
                seen.add(pkg)
        return packages

    # ------------------------------------------------------------------
    # Observe
    # ------------------------------------------------------------------

    async def observe(self, screenshot_path: Path, timeout: float = 5.0) -> Observation:
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)

        await self._run("shell", "screencap", "-p", _DEVICE_SCREENSHOT_PATH, timeout=timeout)
        await self._run("pull", _DEVICE_SCREENSHOT_PATH, str(screenshot_path), timeout=timeout)

        (width, height), fg_app = await asyncio.gather(
            self._query_screen_size(timeout),
            self._query_foreground_app(timeout),
        )

        self._screen_width = width
        self._screen_height = height

        return Observation(
            screenshot_path=str(screenshot_path),
            screen_width=width,
            screen_height=height,
            foreground_app=fg_app,
            platform=self.platform,
        )

    async def _query_screen_size(self, timeout: float) -> tuple[int, int]:
        try:
            output = await self._run("shell", "wm", "size", timeout=timeout)
            match = _WM_SIZE_RE.search(output)
            if match:
                return int(match.group(1)), int(match.group(2))
        except (AdbError, TimeoutError):
            pass
        return 1080, 1920

    async def _query_foreground_app(self, timeout: float) -> str:
        try:
            output = await self._run(
                "shell", "dumpsys", "activity", "activities",
                timeout=max(timeout, 10.0),
            )
            match = _RESUMED_ACTIVITY_RE.search(output)
            if match:
                return match.group(1)
        except (AdbError, TimeoutError):
            pass
        return "unknown"

    async def _get_default_input_method(self, timeout: float) -> str | None:
        try:
            output = await self._run(
                "shell", "settings", "get", "secure", "default_input_method",
                timeout=timeout,
            )
        except (AdbError, TimeoutError):
            return None
        output = output.strip()
        return output or None

    async def _list_input_methods(self, timeout: float) -> set[str]:
        try:
            output = await self._run("shell", "ime", "list", "-s", timeout=timeout)
        except (AdbError, TimeoutError):
            return set()
        return {line.strip() for line in output.splitlines() if line.strip()}

    async def _needs_ime_enable_before_set(self, timeout: float) -> bool:
        del timeout
        return False

    def _get_packaged_yadb_path(self) -> Path:
        return Path(importlib.resources.files("opengui").joinpath("assets/android/yadb"))

    async def _ensure_yadb_available(self, timeout: float) -> bool:
        try:
            await self._run("shell", "ls", _YADB_PATH, timeout=timeout)
            return True
        except (AdbError, TimeoutError):
            pass

        local_yadb = self._get_packaged_yadb_path()
        if not local_yadb.exists():
            return False

        try:
            await self._run("push", str(local_yadb), _YADB_PATH, timeout=timeout)
            await self._run("shell", "chmod", "755", _YADB_PATH, timeout=timeout)
        except (AdbError, TimeoutError):
            return False
        return True

    async def _ensure_adb_keyboard_ready(self, timeout: float) -> bool:
        current_ime = await self._get_default_input_method(timeout)
        if current_ime == _ADB_KEYBOARD_IME:
            return True

        available_imes = await self._list_input_methods(timeout)
        if _ADB_KEYBOARD_IME not in available_imes:
            return False

        if await self._needs_ime_enable_before_set(timeout=timeout):
            try:
                await self._run("shell", "ime", "enable", _ADB_KEYBOARD_IME, timeout=timeout)
            except (AdbError, TimeoutError):
                return False

        try:
            await self._run("shell", "ime", "set", _ADB_KEYBOARD_IME, timeout=timeout)
        except (AdbError, TimeoutError):
            return False
        return True

    async def _input_text_via_adb_keyboard(self, text: str, timeout: float) -> bool:
        if not await self._ensure_adb_keyboard_ready(timeout):
            return False
        for args in (
            (
                "shell", "am", "broadcast",
                "-a", "ADB_INPUT_B64", "--es", "msg", _to_b64_text(text),
            ),
            (
                "shell", "am", "broadcast",
                "-a", "ADB_INPUT_TEXT", "--es", "msg", text,
            ),
        ):
            try:
                await self._run(*args, timeout=timeout)
                return True
            except (AdbError, TimeoutError):
                continue
        return False

    async def _input_text_via_yadb(self, text: str, timeout: float) -> bool:
        if not await self._ensure_yadb_available(timeout):
            return False
        try:
            await self._run(
                "shell",
                "app_process",
                f"-Djava.class.path={_YADB_PATH}",
                "/data/local/tmp",
                _YADB_MAIN_CLASS,
                "-keyboard",
                text,
                timeout=timeout,
            )
            return True
        except (AdbError, TimeoutError):
            return False

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(self, action: Action, timeout: float = 5.0) -> str:
        t = action.action_type

        if t == "tap":
            x, y = self._resolve_point(action)
            await self._run(
                "shell", "input", "tap", str(x), str(y),
                timeout=timeout,
            )

        elif t == "long_press":
            px, py = self._resolve_point(action)
            x, y = str(px), str(py)
            dur = str(action.duration_ms or 800)
            await self._run("shell", "input", "swipe", x, y, x, y, dur, timeout=timeout)

        elif t == "double_tap":
            px, py = self._resolve_point(action)
            x, y = str(px), str(py)
            await self._run("shell", "input", "tap", x, y, timeout=timeout)
            await asyncio.sleep(0.1)
            await self._run("shell", "input", "tap", x, y, timeout=timeout)

        elif t in ("drag", "swipe"):
            px1, py1 = self._resolve_point(action)
            px2, py2 = self._resolve_second_point(action)
            x1, y1 = str(px1), str(py1)
            x2, y2 = str(px2), str(py2)
            dur = str(action.duration_ms or 300)
            await self._run("shell", "input", "swipe", x1, y1, x2, y2, dur, timeout=timeout)

        elif t == "input_text":
            text = action.text or ""
            if text:
                if await self._input_text_via_adb_keyboard(text, timeout):
                    pass
                elif await self._input_text_via_yadb(text, timeout):
                    pass
                elif _is_ascii_safe(text):
                    await self._run(
                        "shell", "input", "text", _escape_shell_text(text),
                        timeout=timeout,
                    )
                else:
                    raise AdbError(
                        "Unicode text input failed. Install and activate ADBKeyboard "
                        "(`adb shell ime set com.android.adbkeyboard/.AdbIME`) or "
                        f"push yadb to {_YADB_PATH}."
                    )

        elif t == "enter":
            await self._run("shell", "input", "keyevent", "KEYCODE_ENTER", timeout=timeout)

        elif t in ("app_switch", "recents"):
            await self._run("shell", "input", "keyevent", "KEYCODE_APP_SWITCH", timeout=timeout)

        elif t == "hotkey":
            keys = action.key or []
            for k in keys:
                keycode = _KEYCODE_MAP.get(k.lower().strip())
                if keycode is None:
                    raise ValueError(
                        f"Unknown key {k!r}. Supported: {sorted(_KEYCODE_MAP.keys())}"
                    )
                await self._run("shell", "input", "keyevent", keycode, timeout=timeout)

        elif t == "scroll":
            await self._do_scroll(action, timeout=timeout)

        elif t == "wait":
            await asyncio.sleep((action.duration_ms or 1000) / 1000.0)

        elif t == "back":
            await self._run("shell", "input", "keyevent", "KEYCODE_BACK", timeout=timeout)

        elif t == "home":
            await self._run("shell", "input", "keyevent", "KEYCODE_HOME", timeout=timeout)

        elif t == "done":
            pass  # terminal action, no device command

        elif t == "open_app":
            pkg = action.text or ""
            if pkg:
                await self._run(
                    "shell", "monkey", "-p", pkg,
                    "-c", "android.intent.category.LAUNCHER", "1",
                    timeout=timeout,
                )

        elif t == "close_app":
            pkg = action.text or ""
            if pkg:
                await self._run("shell", "am", "force-stop", pkg, timeout=timeout)

        else:
            raise ValueError(f"Unsupported action type: {t!r}")

        return describe_action(action)

    def _resolve_x(self, value: float, *, relative: bool) -> int:
        return resolve_coordinate(value, self._screen_width, relative=relative)

    def _resolve_y(self, value: float, *, relative: bool) -> int:
        return resolve_coordinate(value, self._screen_height, relative=relative)

    def _resolve_point(self, action: Action) -> tuple[int, int]:
        if action.x is None or action.y is None:
            raise ValueError(f"Action {action.action_type!r} requires coordinates.")
        return (
            self._resolve_x(action.x, relative=action.relative),
            self._resolve_y(action.y, relative=action.relative),
        )

    def _resolve_second_point(self, action: Action) -> tuple[int, int]:
        if action.x2 is None or action.y2 is None:
            raise ValueError(f"Action {action.action_type!r} requires end-point coordinates.")
        return (
            self._resolve_x(action.x2, relative=action.relative),
            self._resolve_y(action.y2, relative=action.relative),
        )

    async def _do_scroll(self, action: Action, *, timeout: float) -> None:
        """Simulate scroll via a short swipe gesture."""
        x = self._screen_width // 2
        y = self._screen_height // 2
        if action.x is not None and action.y is not None:
            x = self._resolve_x(action.x, relative=action.relative)
            y = self._resolve_y(action.y, relative=action.relative)
        pixels = abs(action.pixels or 200)
        dur = str(action.duration_ms or 300)

        # For scroll, direction is stored in action.text
        direction = (action.text or "down").lower()

        if direction == "up":
            x2, y2 = x, y - pixels
        elif direction == "down":
            x2, y2 = x, y + pixels
        elif direction == "left":
            x2, y2 = x - pixels, y
        else:
            x2, y2 = x + pixels, y

        await self._run(
            "shell", "input", "swipe",
            str(x), str(y), str(x2), str(y2), dur,
            timeout=timeout,
        )
