"""
opengui.observation
===================
Screen-state snapshot consumed by the LLM at each agent step.

``Observation`` is *mutable* because ``screenshot_path`` may be updated after
capture and ``extra`` is enriched incrementally by backends.
"""

from __future__ import annotations

import dataclasses
import textwrap
import typing


@dataclasses.dataclass
class Observation:
    """A snapshot of the device's current screen state."""

    screenshot_path: str | None
    screen_width: int
    screen_height: int
    foreground_app: str | None = None
    platform: str = "unknown"
    extra: dict[str, typing.Any] = dataclasses.field(default_factory=dict)

    @property
    def has_screenshot(self) -> bool:
        return self.screenshot_path is not None

    @property
    def resolution(self) -> tuple[int, int]:
        return (self.screen_width, self.screen_height)

    def to_user_text(
        self,
        task: str,
        step_index: int,
        app_hint: str | None = None,
        coordinate_instruction: str = "Prefer absolute pixel coordinates.",
    ) -> str:
        """Render a structured text block for inclusion in an LLM message."""
        app_name = app_hint or self.foreground_app or "unknown"
        lines: list[str] = [
            f"Step {step_index + 1}",
            f"Task: {task}",
            "",
            f"Screen: {self.screen_width} x {self.screen_height} px "
            f"(platform: {self.platform})",
            f"Foreground app: {app_name}",
            f"Coordinates: {coordinate_instruction}",
        ]
        if self.extra:
            lines.append("")
            lines.append("Additional context:")
            for key, value in self.extra.items():
                value_str = str(value)
                if "\n" in value_str:
                    indented = textwrap.indent(value_str, prefix="    ")
                    lines.append(f"  {key}:\n{indented}")
                else:
                    lines.append(f"  {key}: {value_str}")
        return "\n".join(lines)
