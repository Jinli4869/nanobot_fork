"""
opengui.backends.mobileworld
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
OpenGUI backend that talks directly to the MobileWorld runtime HTTP server.

The backend intentionally captures screenshot, state, and UI XML during every
observation because MobileWorld GUI skill extraction runs offline and cannot
reconstruct page state on demand.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from opengui.action import Action, resolve_coordinate
from opengui.backends import read_png_size
from opengui.backends.adb import (
    _parse_ui_tree_xml,
    _write_raw_ui_tree_error,
    _write_raw_ui_tree_xml,
)
from opengui.observation import Observation

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:6800"
_DEFAULT_DEVICE = "emulator-5554"
_DEFAULT_OBSERVE_TIMEOUT_SECONDS = 30.0
_DEFAULT_STEP_TIMEOUT_SECONDS = 30.0
_MOBILEWORLD_PACKAGE_TO_APP_NAME = {
    "com.google.android.apps.nexuslauncher": "桌面",
    "com.google.android.contacts": "Contacts",
    "com.android.settings": "Settings",
    "com.google.android.deskclock": "Clock",
    "com.google.android.apps.maps": "Maps",
    "com.android.chrome": "Chrome",
    "org.fossify.calendar": "Calendar",
    "com.google.android.documentsui": "files",
    "gallery.photomanager.picturegalleryapp.imagegallery": "Gallery",
    "com.testmall.app": "Taodian",
    "com.mattermost.rnbeta": "Mattermost",
    "com.mattermost.rn": "Mattermost",
    "org.joinmastodon.android.mastodon": "Mastodon",
    "com.gmailclone": "Mail",
    "com.google.android.apps.messaging": "SMS",
    "com.android.mms": "SMS",
    "com.android.messaging": "SMS",
    "com.android.camera2": "Camera",
}


class MobileWorldBackend:
    """Device backend backed by MobileWorld's `/screenshot`, `/state`, `/xml`, and `/step` APIs."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        device: str | None = None,
        xml_mode: str = "uia",
        collect_ui_tree: bool = True,
        collect_ui_tree_nodes: bool = True,
        screenshot_transport: str = "download",
    ) -> None:
        resolved_base_url = (
            base_url
            or os.getenv("MOBILEWORLD_ENV_URL")
            or os.getenv("MOBILEWORLD_BASE_URL")
            or _DEFAULT_BASE_URL
        )
        self.base_url = resolved_base_url.rstrip("/")
        self.device = device or os.getenv("MOBILEWORLD_DEVICE") or os.getenv("ANDROID_SERIAL") or _DEFAULT_DEVICE
        self.xml_mode = (xml_mode or "uia").strip().lower()
        if self.xml_mode not in {"uia", "ac"}:
            raise ValueError(f"Unsupported MobileWorld XML mode: {xml_mode!r}")
        self.collect_ui_tree = collect_ui_tree
        self.collect_ui_tree_nodes = collect_ui_tree_nodes
        self.screenshot_transport = (screenshot_transport or "download").strip().lower()
        self._screen_width = 1080
        self._screen_height = 2400
        self._capture_width = self._screen_width
        self._capture_height = self._screen_height

    @property
    def platform(self) -> str:
        return "android"

    async def preflight(self) -> None:
        await self._request_json("GET", "/health", timeout=5.0)

    async def list_apps(self) -> list[str]:
        return []

    async def observe(
        self,
        screenshot_path: Path,
        timeout: float = _DEFAULT_OBSERVE_TIMEOUT_SECONDS,
    ) -> Observation:
        screenshot_path = Path(screenshot_path)
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)

        started = time.monotonic()
        state: dict[str, Any] = {}
        extra: dict[str, Any] = {
            "capture_source": "mobileworld_server",
            "mobileworld_base_url": self.base_url,
            "mobileworld_device": self.device,
        }

        try:
            await self._capture_screenshot(screenshot_path, timeout=timeout)
        except Exception as exc:
            logger.warning("MobileWorld screenshot capture failed: %s", exc)
            raise

        screenshot_size = read_png_size(screenshot_path)
        if screenshot_size is not None:
            self._capture_width, self._capture_height = screenshot_size
            self._screen_width, self._screen_height = screenshot_size

        try:
            state = await self._request_json(
                "GET",
                "/state",
                params={"device": self.device},
                timeout=timeout,
            )
        except Exception as exc:
            extra["state_error"] = str(exc)
            logger.warning("MobileWorld state query failed: %s", exc)
        else:
            extra["state"] = state
            viewport_size = state.get("viewport_size")
            if (
                isinstance(viewport_size, list)
                and len(viewport_size) == 2
                and all(isinstance(value, int) for value in viewport_size)
            ):
                self._screen_width, self._screen_height = int(viewport_size[0]), int(viewport_size[1])

        if self.collect_ui_tree:
            await self._collect_ui_tree(screenshot_path, extra=extra, timeout=timeout)

        extra["observe_latency_ms"] = round((time.monotonic() - started) * 1000, 2)
        foreground_app = (
            _clean_optional_str(state.get("foreground_app"))
            or _clean_optional_str(state.get("current_app"))
            or _clean_optional_str(state.get("foreground_package"))
        )
        return Observation(
            screenshot_path=str(screenshot_path),
            screen_width=self._screen_width,
            screen_height=self._screen_height,
            foreground_app=foreground_app,
            platform=self.platform,
            extra=extra,
        )

    async def execute(
        self,
        action: Action,
        timeout: float = _DEFAULT_STEP_TIMEOUT_SECONDS,
    ) -> str:
        payload = self._to_mobileworld_action(action)
        response = await self._request_json(
            "POST",
            "/step",
            payload={"device": self.device, "action": payload},
            timeout=timeout,
        )
        result = response.get("result")
        if result is None:
            return json.dumps(response, ensure_ascii=False)
        return str(result)

    def _to_mobileworld_action(self, action: Action) -> dict[str, Any]:
        action_type = action.action_type

        if action_type == "tap":
            x, y = self._point(action.x, action.y, relative=action.relative)
            return {"action_type": "click", "x": x, "y": y}

        if action_type == "long_press":
            x, y = self._point(action.x, action.y, relative=action.relative)
            return {"action_type": "long_press", "x": x, "y": y}

        if action_type == "double_tap":
            x, y = self._point(action.x, action.y, relative=action.relative)
            return {"action_type": "double_tap", "x": x, "y": y}

        if action_type in {"drag", "swipe"}:
            start_x, start_y = self._point(action.x, action.y, relative=action.relative)
            end_x, end_y = self._point(action.x2, action.y2, relative=action.relative)
            return {
                "action_type": "drag",
                "start_x": start_x,
                "start_y": start_y,
                "end_x": end_x,
                "end_y": end_y,
            }

        if action_type == "scroll":
            direction = (action.text or "down").strip().lower()
            if direction not in {"up", "down", "left", "right"}:
                direction = "down"
            return {"action_type": "scroll", "direction": direction}

        if action_type == "input_text":
            text = action.text or ""
            if not text:
                return {"action_type": "wait"}
            return {"action_type": "input_text", "text": text}

        if action_type == "back":
            return {"action_type": "navigate_back"}

        if action_type == "home":
            return {"action_type": "navigate_home"}

        if action_type == "enter":
            return {"action_type": "keyboard_enter"}

        if action_type == "wait":
            return {"action_type": "wait"}

        if action_type == "screenshot":
            return {"action_type": "wait"}

        if action_type == "open_app":
            app_name = _mobileworld_open_app_name(action.text or action.package or "")
            return {"action_type": "open_app", "app_name": app_name}

        if action_type == "done":
            if action.text:
                return {"action_type": "answer", "text": action.text}
            status = action.status or "success"
            return {"action_type": "status", "goal_status": status}

        if action_type == "hotkey":
            key = "+".join(action.key or []).lower()
            if "enter" in key or "return" in key:
                return {"action_type": "keyboard_enter"}
            if "back" in key or "escape" in key:
                return {"action_type": "navigate_back"}
            if "home" in key:
                return {"action_type": "navigate_home"}

        raise ValueError(f"Unsupported MobileWorld backend action: {action_type}")

    async def _capture_screenshot(self, screenshot_path: Path, *, timeout: float) -> None:
        prefix = screenshot_path.stem
        if self.screenshot_transport != "b64":
            try:
                metadata = await self._request_json(
                    "GET",
                    "/screenshot",
                    params={
                        "device": self.device,
                        "prefix": prefix,
                        "return_b64": "false",
                    },
                    timeout=timeout,
                )
                remote_path = metadata.get("path")
                if not isinstance(remote_path, str) or not remote_path:
                    raise RuntimeError(f"MobileWorld screenshot response missing path: {metadata!r}")
                data = await self._request_bytes(
                    "/download",
                    params={"path": remote_path},
                    timeout=timeout,
                )
                screenshot_path.write_bytes(data)
                return
            except Exception as exc:
                logger.debug("MobileWorld screenshot download transport failed, falling back to b64: %s", exc)

        metadata = await self._request_json(
            "GET",
            "/screenshot",
            params={
                "device": self.device,
                "prefix": prefix,
                "return_b64": "true",
            },
            timeout=timeout,
        )
        b64_png = metadata.get("b64_png")
        if not isinstance(b64_png, str) or not b64_png:
            raise RuntimeError(f"MobileWorld screenshot response missing b64_png: {metadata!r}")
        screenshot_path.write_bytes(base64.b64decode(b64_png))

    async def _collect_ui_tree(
        self,
        screenshot_path: Path,
        *,
        extra: dict[str, Any],
        timeout: float,
    ) -> None:
        try:
            response = await self._request_json(
                "GET",
                "/xml",
                params={
                    "device": self.device,
                    "mode": self.xml_mode,
                    "prefix": screenshot_path.stem,
                    "return_content": "true",
                },
                timeout=timeout,
            )
            xml_text = response.get("content")
            if not isinstance(xml_text, str) or not xml_text.strip():
                raise RuntimeError(f"MobileWorld XML response missing content: {response!r}")
            _write_raw_ui_tree_xml(screenshot_path, xml_text)
            parsed = _parse_ui_tree_xml(xml_text, include_nodes=self.collect_ui_tree_nodes)
            extra.update(parsed)
            extra["ui_tree_source"] = "mobileworld_xml"
            extra["ui_tree_xml_mode"] = self.xml_mode
            if isinstance(response.get("path"), str):
                extra["ui_tree_remote_path"] = response["path"]
        except Exception as exc:
            message = str(exc)
            extra["ui_tree_error"] = message
            extra["ui_tree_source"] = "mobileworld_xml"
            extra["ui_tree_xml_mode"] = self.xml_mode
            _write_raw_ui_tree_error(screenshot_path, message, timeout)
            logger.warning("MobileWorld XML collection failed: %s", exc)

    def _point(self, x: float | None, y: float | None, *, relative: bool) -> tuple[int, int]:
        if x is None or y is None:
            raise ValueError("Action requires coordinates.")
        px = resolve_coordinate(x, self._capture_width, relative=relative)
        py = resolve_coordinate(y, self._capture_height, relative=relative)
        if (self._capture_width, self._capture_height) != (self._screen_width, self._screen_height):
            px = round(px * self._screen_width / max(1, self._capture_width))
            py = round(py * self._screen_height / max(1, self._capture_height))
            px = max(0, min(px, self._screen_width - 1))
            py = max(0, min(py, self._screen_height - 1))
        return px, py

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        timeout: float,
    ) -> dict[str, Any]:
        data = await asyncio.to_thread(
            self._request,
            method,
            path,
            params=params,
            payload=payload,
            timeout=timeout,
        )
        try:
            parsed = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"MobileWorld returned non-JSON response for {path}: {data[:200]!r}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"MobileWorld returned unexpected JSON for {path}: {parsed!r}")
        return parsed

    async def _request_bytes(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float,
    ) -> bytes:
        return await asyncio.to_thread(
            self._request,
            "GET",
            path,
            params=params,
            payload=None,
            timeout=timeout,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None,
        payload: dict[str, Any] | None,
        timeout: float,
    ) -> bytes:
        query = urllib.parse.urlencode(params or {})
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"

        body: bytes | None = None
        headers: dict[str, str] = {}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(request, timeout=max(1.0, timeout)) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MobileWorld HTTP {exc.code} for {method} {path}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"MobileWorld request failed for {method} {path}: {exc}") from exc


def _clean_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mobileworld_open_app_name(value: str) -> str:
    cleaned = " ".join((value or "").strip().strip("\"'").split())
    if not cleaned:
        return ""
    return _MOBILEWORLD_PACKAGE_TO_APP_NAME.get(cleaned.lower(), cleaned)
