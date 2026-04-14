"""Phase 19 Plan 03 trace/log inspection tests for the TUI backend."""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    from fastapi.testclient import TestClient

    from nanobot.tui.app import create_app
    from nanobot.tui.contracts import SessionContract
    from nanobot.tui.dependencies import (
        get_runtime_service,
        get_trace_inspection_service,
    )
    from nanobot.tui.services import OperationsRegistry, RuntimeService, TraceInspectionService

    _IMPORTS_OK = True
    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - Wave 0 guard until Task 1 lands
    TestClient = None
    create_app = None
    SessionContract = None
    get_runtime_service = None
    get_trace_inspection_service = None
    OperationsRegistry = None
    RuntimeService = None
    TraceInspectionService = None
    _IMPORTS_OK = False
    _IMPORT_ERROR = exc


def _require_imports() -> None:
    if not _IMPORTS_OK:
        pytest.fail(f"phase 19 trace modules are not importable yet: {_IMPORT_ERROR}")


def _make_artifacts(workspace: Path, run_id: str) -> tuple[Path, Path]:
    run_dir = workspace / "gui_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir / "trace.jsonl", run_dir / "log.jsonl"


def _make_app(workspace: Path, run_id: str) -> TestClient:
    app = create_app(include_runtime_routes=True)
    registry = OperationsRegistry()
    registry.start_run(
        run_id=run_id,
        task_kind="nanobot_open_url",
        status="succeeded",
        summary="Finished",
        trace_ref=str(workspace / "gui_runs" / run_id),
        started_at="2026-03-21T12:00:00Z",
    )
    app.dependency_overrides[get_runtime_service] = lambda: RuntimeService(
        SessionContract(workspace_path=workspace, list_sessions=lambda: []),
        registry=registry,
        artifacts_root=workspace / "gui_runs",
        task_launch_available=True,
    )
    app.dependency_overrides[get_trace_inspection_service] = lambda: TraceInspectionService(
        registry=registry,
        artifacts_root=workspace / "gui_runs",
    )
    return TestClient(app)


def test_trace_endpoint_returns_filtered_events_for_browser_consumers(tmp_path: Path) -> None:
    _require_imports()

    trace_path, _ = _make_artifacts(tmp_path, "run-trace-001")
    trace_path.write_text(
        "\n".join(
            [
                '{"type":"metadata","timestamp_iso":"2026-03-21T12:00:00Z","task":"Open URL https://example.com/docs","trace_path":"/tmp/hidden","summary":"'
                + ("metadata summary " * 30)
                + '"}',
                '{"type":"step","event_id":"evt-step-1","timestamp_iso":"2026-03-21T12:00:10Z","step_index":1,"status":"running","summary":"'
                + ("step summary " * 30)
                + '","prompt":{"task":"secret"},"model_output":{"raw_content":"hidden"},"screenshot":"frame-001.png"}',
                '{"type":"attempt_result","event_id":"evt-result-1","timestamp_iso":"2026-03-21T12:00:20Z","success":true,"status":"succeeded","summary":"'
                + ("done summary " * 30)
                + '","steps_taken":3,"trace_path":"/tmp/secret/trace.jsonl"}',
            ]
        ),
        encoding="utf-8",
    )

    client = _make_app(tmp_path, "run-trace-001")
    response = client.get("/runtime/runs/run-trace-001/trace")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == "run-trace-001"
    assert payload["status"] == "ok"
    assert [event["event_type"] for event in payload["events"]] == [
        "metadata",
        "step",
        "attempt_result",
    ]
    assert set(payload["events"][1]) <= {
        "event_id",
        "event_type",
        "timestamp",
        "step_index",
        "status",
        "summary",
        "success",
        "done",
        "retry_count",
    }
    assert "prompt" not in response.text
    assert "model_output" not in response.text
    assert "trace_path" not in response.text
    assert "screenshot" not in response.text
    assert len(payload["events"][0]["summary"]) == 240
    assert len(payload["events"][1]["summary"]) == 240


def test_log_endpoint_returns_filtered_lines_without_raw_paths_or_prompts(tmp_path: Path) -> None:
    _require_imports()

    trace_path, log_path = _make_artifacts(tmp_path, "run-trace-002")
    trace_path.write_text(
        "\n".join(
            [
                '{"type":"attempt_exception","timestamp_iso":"2026-03-21T12:01:00Z","error_message":"'
                + ("settings panel timed out " * 20)
                + '","error_type":"RuntimeError","prompt":{"task":"hidden"}}',
                '{"type":"result","timestamp_iso":"2026-03-21T12:01:10Z","success":false,"error":"'
                + ("backend failed " * 30)
                + '","trace_path":"/tmp/secret/run"}',
            ]
        ),
        encoding="utf-8",
    )
    log_path.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-03-21T12:01:00Z","level":"INFO","code":"RUN_START","message":"Starting run for https://example.com/docs","prompt":"do not leak"}',
                '{"timestamp":"2026-03-21T12:01:05Z","level":"ERROR","code":"STEP_FAIL","message":"'
                + ("Failed while opening /tmp/private/workspace/file because the prompt asked for a secret " * 6)
                + '","artifact_path":"/tmp/private/workspace/file"}',
            ]
        ),
        encoding="utf-8",
    )

    client = _make_app(tmp_path, "run-trace-002")
    response = client.get("/runtime/runs/run-trace-002/logs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == "run-trace-002"
    assert payload["status"] == "ok"
    assert all(set(line) <= {"timestamp", "level", "code", "message"} for line in payload["lines"])
    assert any(line["level"] == "ERROR" for line in payload["lines"])
    assert "prompt" not in response.text
    assert "artifact_path" not in response.text
    assert "/tmp/private/workspace/file" not in response.text
    assert all(len(line["message"]) <= 240 for line in payload["lines"])


def test_trace_and_log_endpoints_return_typed_not_found_or_empty_states(tmp_path: Path) -> None:
    _require_imports()

    trace_path, _ = _make_artifacts(tmp_path, "run-empty-001")
    trace_path.write_text("", encoding="utf-8")

    client = _make_app(tmp_path, "run-empty-001")

    empty_trace = client.get("/runtime/runs/run-empty-001/trace")
    empty_logs = client.get("/runtime/runs/run-empty-001/logs")
    missing_trace = client.get("/runtime/runs/run-missing-001/trace")
    missing_logs = client.get("/runtime/runs/run-missing-001/logs")

    assert empty_trace.status_code == 200
    assert empty_trace.json() == {
        "run_id": "run-empty-001",
        "status": "empty",
        "events": [],
    }
    assert empty_logs.status_code == 200
    assert empty_logs.json() == {
        "run_id": "run-empty-001",
        "status": "empty",
        "lines": [],
    }
    assert missing_trace.status_code == 200
    assert missing_trace.json() == {
        "run_id": "run-missing-001",
        "status": "not_found",
        "events": [],
    }
    assert missing_logs.status_code == 200
    assert missing_logs.json() == {
        "run_id": "run-missing-001",
        "status": "not_found",
        "lines": [],
    }


def test_trace_playback_endpoint_returns_detailed_step_payload(tmp_path: Path) -> None:
    _require_imports()

    trace_path, _ = _make_artifacts(tmp_path, "run-playback-001")
    screenshots_dir = trace_path.parent / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    screenshot_file = screenshots_dir / "step_001.png"
    screenshot_file.write_bytes(b"png-bytes")

    trace_path.write_text(
        "\n".join(
            [
                '{"event":"metadata","timestamp_iso":"2026-03-21T12:00:00Z","task":"Create calendar event"}',
                '{"event":"step","timestamp_iso":"2026-03-21T12:00:10Z","step_index":1,"action":{"action_type":"tap","x":320,"y":480},"action_summary":"tap add button","screenshot_path":"'
                + str(screenshot_file)
                + '","prompt":{"task":"Create calendar event"},"model_output":{"raw_content":"Action: tap add button"},"execution":{"tool_result":"ok"},"stability":{"thinking_mode":"fast"}}',
            ]
        ),
        encoding="utf-8",
    )

    client = _make_app(tmp_path, "run-playback-001")
    response = client.get("/runtime/runs/run-playback-001/trace-playback")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == "run-playback-001"
    assert payload["status"] == "ok"
    assert payload["task"] == "Create calendar event"
    assert payload["total_steps"] == 1
    step = payload["steps"][0]
    assert step["step_index"] == 1
    assert step["action"]["action_type"] == "tap"
    assert step["action_summary"] == "tap add button"
    assert step["prompt"]["task"] == "Create calendar event"
    assert step["model_output"]["raw_content"] == "Action: tap add button"
    assert step["execution"]["tool_result"] == "ok"
    assert step["stability"]["thinking_mode"] == "fast"
    assert step["screenshot_url"] == "/runtime/runs/run-playback-001/screenshots/step_001.png"


def test_run_screenshot_endpoint_serves_only_run_screenshot_files(tmp_path: Path) -> None:
    _require_imports()

    trace_path, _ = _make_artifacts(tmp_path, "run-playback-002")
    screenshots_dir = trace_path.parent / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    screenshot_file = screenshots_dir / "step_002.png"
    screenshot_file.write_bytes(b"png-two")
    trace_path.write_text("", encoding="utf-8")

    client = _make_app(tmp_path, "run-playback-002")
    ok = client.get("/runtime/runs/run-playback-002/screenshots/step_002.png")
    missing = client.get("/runtime/runs/run-playback-002/screenshots/step_404.png")
    traversal = client.get("/runtime/runs/run-playback-002/screenshots/%2E%2E%2Ftrace.jsonl")

    assert ok.status_code == 200
    assert ok.content == b"png-two"
    assert missing.status_code == 404
    assert traversal.status_code == 404
