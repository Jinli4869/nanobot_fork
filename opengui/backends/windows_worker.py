"""Windows worker launch helper for alternate-desktop execution."""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import Any


def launch_windows_worker(
    *,
    desktop_name: str,
    width: int,
    height: int,
    control_path: str,
) -> subprocess.Popen[Any] | Any:
    """Launch the worker process on the named desktop via ``lpDesktop``."""
    startupinfo = _build_startupinfo(desktop_name)
    command = [
        sys.executable,
        "-m",
        "opengui.backends.windows_worker",
        "--desktop-name",
        desktop_name,
        "--width",
        str(width),
        "--height",
        str(height),
        "--control-path",
        control_path,
    ]
    if sys.platform != "win32":
        raise RuntimeError(f"launch_windows_worker requires Windows (lpDesktop={startupinfo.lpDesktop})")
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=startupinfo,
    )


def _build_startupinfo(desktop_name: str) -> Any:
    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_cls is None:
        class _StartupInfo:
            lpDesktop: str | None = None

        startupinfo = _StartupInfo()
    else:
        startupinfo = startupinfo_cls()
    startupinfo.lpDesktop = f"WinSta0\\{desktop_name}"
    return startupinfo


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OpenGUI Windows alternate-desktop worker")
    parser.add_argument("--desktop-name", required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--control-path", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _parse_args(argv)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
