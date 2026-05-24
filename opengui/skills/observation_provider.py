"""
opengui.skills.observation_provider
===================================
Lightweight wrapper around ``DeviceBackend.observe()`` for the skill executor.

This lives in ``skills/`` because it is only consumed by ``SkillExecutor`` and
related infrastructure — not by the main agent loop directly.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from opengui.interfaces import DeviceBackend
from opengui.observation import Observation

logger = logging.getLogger(__name__)


class AgentScreenshotProvider:
    """Provide the current screenshot via ``DeviceBackend.observe()``."""

    def __init__(self, backend: DeviceBackend, artifacts_root: Path) -> None:
        self._backend = backend
        self._artifacts_root = Path(artifacts_root)
        self._counter = 0

    async def get_observation(self) -> Observation | None:
        self._counter += 1
        skill_dir = self._artifacts_root / "skill_screenshots"
        skill_dir.mkdir(parents=True, exist_ok=True)
        path = skill_dir / f"skill_{int(time.time() * 1000)}_{self._counter}.png"
        try:
            return await self._backend.observe(path)
        except Exception as exc:
            logger.warning("ScreenshotProvider observe failed: %s", exc)
        return None

    async def get_screenshot(self) -> Path | None:
        obs = await self.get_observation()
        if obs is not None and obs.screenshot_path:
            return Path(obs.screenshot_path)
        return None
