"""pyautogui helpers for reliable desktop mouse and keyboard control."""

from __future__ import annotations

import platform
import time
from pathlib import Path

_KEY_ALIASES = {
    "cmd": "command",
    "ctrl": "ctrl",
    "control": "ctrl",
    "return": "enter",
    "escape": "esc",
    "option": "option",
    "alt": "option",
    "delete": "backspace",
    "win": "winleft",
    "super": "winleft",
    "arrowleft": "left",
    "arrowright": "right",
    "arrowup": "up",
    "arrowdown": "down",
}
_MODIFIER_ORDER = {
    "command": 0,
    "ctrl": 1,
    "option": 2,
    "shift": 3,
    "winleft": 4,
}


def _load_pyautogui():
    import pyautogui

    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0
    return pyautogui


def normalize_keys(keys: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize aliases and modifier ordering for safe comparisons and execution."""
    normalized = tuple(
        _KEY_ALIASES.get(key.lower().strip(), key.lower().strip())
        for key in keys
        if key and key.strip()
    )
    modifiers = sorted(
        (key for key in normalized if key in _MODIFIER_ORDER),
        key=lambda key: _MODIFIER_ORDER[key],
    )
    others = [key for key in normalized if key not in _MODIFIER_ORDER]
    return tuple(modifiers + others)


def size() -> tuple[int, int]:
    """Return the logical desktop size used by pyautogui."""
    pyautogui = _load_pyautogui()
    dimensions = pyautogui.size()
    return int(dimensions.width), int(dimensions.height)


def capture_screenshot(output_path: str | Path) -> None:
    """Capture a screenshot via pyautogui and save it to *output_path*."""
    pyautogui = _load_pyautogui()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    screenshot = pyautogui.screenshot()
    screenshot.save(path)


def move(x: int, y: int) -> None:
    """Move to absolute screen coordinates."""
    pyautogui = _load_pyautogui()
    pyautogui.moveTo(x, y)


def _click(x: int, y: int, *, button: str = "left", clicks: int = 1) -> None:
    pyautogui = _load_pyautogui()
    pyautogui.moveTo(x, y)
    time.sleep(0.05)
    pyautogui.click(x=x, y=y, button=button, clicks=clicks, interval=0.05)


def click(x: int, y: int) -> None:
    """Perform a left click at absolute screen coordinates."""
    _click(x, y, button="left", clicks=1)


def right_click(x: int, y: int) -> None:
    """Perform a right click at absolute screen coordinates."""
    _click(x, y, button="right", clicks=1)


def middle_click(x: int, y: int) -> None:
    """Perform a middle click at absolute screen coordinates."""
    _click(x, y, button="middle", clicks=1)


def double_click(x: int, y: int) -> None:
    """Perform a double click at absolute screen coordinates."""
    _click(x, y, button="left", clicks=2)


def triple_click(x: int, y: int) -> None:
    """Perform a triple click at absolute screen coordinates."""
    _click(x, y, button="left", clicks=3)


def drag(x1: int, y1: int, x2: int, y2: int, *, duration_ms: int = 500) -> None:
    """Drag from one absolute point to another."""
    pyautogui = _load_pyautogui()
    pyautogui.moveTo(x1, y1)
    time.sleep(0.05)
    pyautogui.dragTo(x2, y2, duration=max(0, duration_ms) / 1000, button="left")


def scroll(direction: str, *, pixels: int = 360) -> None:
    """Scroll vertically or horizontally."""
    pyautogui = _load_pyautogui()
    amount = abs(int(pixels))
    if direction == "up":
        pyautogui.scroll(amount)
        return
    if direction == "down":
        pyautogui.scroll(-amount)
        return
    if direction == "right":
        if not hasattr(pyautogui, "hscroll"):
            raise RuntimeError("Horizontal scroll is unavailable in this pyautogui build")
        pyautogui.hscroll(amount)
        return
    if direction == "left":
        if not hasattr(pyautogui, "hscroll"):
            raise RuntimeError("Horizontal scroll is unavailable in this pyautogui build")
        pyautogui.hscroll(-amount)
        return
    raise RuntimeError(f"Unsupported scroll direction: {direction}")


def type_text(text: str) -> None:
    """Type text using clipboard paste first, then pyautogui.write fallback."""
    pyautogui = _load_pyautogui()
    paste_mod = "command" if platform.system() == "Darwin" else "ctrl"
    try:
        import pyperclip

        pyperclip.copy(text)
        pyautogui.hotkey(paste_mod, "v")
    except Exception:
        pyautogui.write(text, interval=0.0)


def press_keys(keys: tuple[str, ...]) -> None:
    """Press a single key or hotkey chord."""
    pyautogui = _load_pyautogui()
    normalized = normalize_keys(keys)
    if len(normalized) == 1:
        pyautogui.press(normalized[0])
        return
    pyautogui.hotkey(*normalized)


def is_available() -> bool:
    """Return True when pyautogui is importable."""
    try:
        _load_pyautogui()
        return True
    except Exception:
        return False
