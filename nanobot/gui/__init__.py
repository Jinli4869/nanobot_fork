"""Lightweight GUI automation runtime for nanobot."""

from nanobot.gui.backend import (
    ComputerAction,
    DesktopObservation,
    DryRunDesktopBackend,
    LocalDesktopBackend,
    describe_action,
    parse_computer_action,
)
from nanobot.gui.runtime import GuiRuntime

__all__ = [
    "ComputerAction",
    "DesktopObservation",
    "DryRunDesktopBackend",
    "GuiRuntime",
    "LocalDesktopBackend",
    "describe_action",
    "parse_computer_action",
]
