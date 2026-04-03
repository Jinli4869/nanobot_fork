"""Phase 30 - Stable shortcut execution: live binding, settle timing, and fallback."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.xfail(raises=ImportError, strict=True)
def test_llm_condition_evaluator() -> None:
    from opengui.skills.multi_layer_executor import LLMConditionEvaluator

    assert LLMConditionEvaluator is not None


@pytest.mark.xfail(strict=False)
def test_shortcut_executor_wiring() -> None:
    from opengui.skills.multi_layer_executor import ShortcutExecutor

    assert hasattr(ShortcutExecutor, "post_action_settle_seconds")


@pytest.mark.xfail(strict=False)
def test_live_binding() -> None:
    from opengui.skills import multi_layer_executor

    assert "LLMConditionEvaluator" in multi_layer_executor.__all__
