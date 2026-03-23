from __future__ import annotations

import argparse
import asyncio
import copy
import json
import re
import tempfile
from pathlib import Path

import numpy as np

from opengui.agent import GuiAgent
from opengui.backends.dry_run import DryRunBackend
from opengui.interfaces import LLMResponse, ToolCall
from opengui.memory.retrieval import MemoryRetriever
from opengui.memory.store import MemoryStore
from opengui.memory.types import MemoryEntry, MemoryType
from opengui.trajectory.recorder import TrajectoryRecorder


class _FakeEmbedder:
    DIM = 16

    async def embed(self, texts: list[str]) -> np.ndarray:
        vecs = np.zeros((len(texts), self.DIM), dtype=np.float32)
        for i, text in enumerate(texts):
            slot = hash(text) % self.DIM
            vecs[i, slot] = 1.0
        return vecs


class _RecordingLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    async def chat(self, messages, tools=None, tool_choice=None) -> LLMResponse:
        self.calls.append(copy.deepcopy(messages))
        if not self._responses:
            raise AssertionError("No scripted responses left")
        return self._responses.pop(0)


def _done_response() -> LLMResponse:
    return LLMResponse(
        content="Action: done",
        tool_calls=[ToolCall(
            id="tc_done",
            name="computer_use",
            arguments={"action_type": "done", "status": "success"},
        )],
    )


def _clean_content(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _entry_from_raw_file(
    *,
    path: Path,
    entry_id: str,
    memory_type: MemoryType,
    platform: str,
    app: str | None = None,
    tags: tuple[str, ...] = (),
) -> MemoryEntry:
    content = _clean_content(path.read_text(encoding="utf-8"))
    return MemoryEntry(
        entry_id=entry_id,
        memory_type=memory_type,
        platform=platform,
        app=app,
        tags=tags,
        content=content,
    )


async def _run_probe(task: str, os_path: Path, app_path: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="opengui-memory-probe-") as tmp:
        tmp_path = Path(tmp)
        store = MemoryStore(tmp_path / "memory")
        store.add(_entry_from_raw_file(
            path=os_path,
            entry_id="probe-os-guide",
            memory_type=MemoryType.OS_GUIDE,
            platform="macos",
            tags=("macos", "shortcut"),
        ))
        store.add(_entry_from_raw_file(
            path=app_path,
            entry_id="probe-app-guide",
            memory_type=MemoryType.APP_GUIDE,
            platform="macos",
            app="browser",
            tags=("browser", "hotkey"),
        ))
        store.save()

        retriever = MemoryRetriever(embedding_provider=_FakeEmbedder(), top_k=5)
        await retriever.index(store.list_all())

        hits = await retriever.search(task, top_k=5)
        context = retriever.format_context(hits)

        llm = _RecordingLLM([_done_response()])
        recorder = TrajectoryRecorder(output_dir=tmp_path / "traj", task=task, platform="macos")
        agent = GuiAgent(
            llm,
            DryRunBackend(),
            trajectory_recorder=recorder,
            memory_retriever=retriever,
            artifacts_root=tmp_path / "runs",
            max_steps=1,
        )
        result = await agent.run(task, max_retries=1)
        system_prompt = llm.calls[0][0]["content"] if llm.calls else ""
        trace_path = recorder.path
        trace_events = []
        if trace_path is not None and trace_path.exists():
            trace_events = [
                json.loads(line)
                for line in trace_path.read_text(encoding="utf-8").splitlines()
            ]
        memory_events = [event for event in trace_events if event.get("type") == "memory_retrieval"]

        print("=== Memory Probe ===")
        print(f"task: {task}")
        print(f"result_success: {result.success}")
        print(f"raw_file_count: 2")
        print(f"indexed_entry_count: {len(store.list_all())}")
        print(f"retrieval_hit_count: {len(hits)}")
        print()
        print("=== Retrieval Hits ===")
        for idx, (entry, score) in enumerate(hits, start=1):
            preview = _clean_content(entry.content)[:200]
            print(
                f"{idx}. id={entry.entry_id} type={entry.memory_type.value} "
                f"platform={entry.platform} app={entry.app or '-'} score={score:.4f}"
            )
            print(f"   preview={preview}")
        print()
        print("=== Injected Context ===")
        print(context or "(empty)")
        print()
        print("=== Prompt Has Relevant Knowledge ===")
        print("Relevant Knowledge" in system_prompt)
        print()
        print("=== Memory Retrieval Events ===")
        print(json.dumps(memory_events, ensure_ascii=False, indent=2))
        if trace_path is not None:
            print()
            print(f"trace_path: {trace_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe OpenGUI memory retrieval using raw guide markdown files.")
    parser.add_argument("task", help="Task/query to test against memory retrieval.")
    parser.add_argument(
        "--os-guide",
        type=Path,
        default=Path("/Users/jinli/.opengui/memory/os_guide.md"),
        help="Path to raw os_guide markdown.",
    )
    parser.add_argument(
        "--app-guide",
        type=Path,
        default=Path("/Users/jinli/.opengui/memory/app_guide.md"),
        help="Path to raw app_guide markdown.",
    )
    args = parser.parse_args()
    asyncio.run(_run_probe(args.task, args.os_guide, args.app_guide))


if __name__ == "__main__":
    main()
