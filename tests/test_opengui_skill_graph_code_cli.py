import json
from pathlib import Path
from types import SimpleNamespace

from opengui.interfaces import LLMResponse
from opengui.skills.code_graph import export_graph_to_code
from opengui.skills.code_graph_cli import main
from opengui.skills.data import Skill, SkillStep
from opengui.skills.graph import GraphEdge, GraphNode, SkillGraphStore
from opengui.skills.library import SkillLibrary
from opengui.skills.state_contract import normalize_state_contract


def _contract(label: str) -> dict[str, object]:
    return normalize_state_contract({
        "anchor": {"app_package": "com.example.app"},
        "signature": {
            "required": [
                {
                    "selector": {
                        "resource_id": f"com.example:id/{label.lower()}",
                    },
                    "state": ["visible"],
                }
            ],
            "forbidden": [],
        },
    }) or {}


def _graph_store(store_dir: Path) -> SkillGraphStore:
    store = SkillGraphStore(store_dir=store_dir)
    home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home",
            state_contract=_contract("home"),
            fingerprint="fp-home",
        ),
        save=False,
    )
    profile = store.upsert_node(
        GraphNode(
            node_id="node-profile",
            app="com.example.app",
            platform="android",
            description="Profile",
            state_contract=_contract("profile"),
            fingerprint="fp-profile",
        ),
        save=False,
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-profile",
            app="com.example.app",
            platform="android",
            source_node_id=home.node_id,
            target_node_id=profile.node_id,
            action_type="tap",
            target="Profile",
            parameters={"text": "Profile"},
            precondition=home.state_contract,
        ),
        save=False,
    )
    store.save()
    return store


def test_code_graph_cli_export_skills_writes_source(tmp_path: Path) -> None:
    library = SkillLibrary(store_dir=tmp_path / "skills")
    library.add(
        Skill(
            skill_id="skill-profile",
            name="open_profile",
            description="Open profile.",
            app="com.example.app",
            platform="android",
            steps=(
                SkillStep(action_type="tap", target="Profile", parameters={"text": "Profile"}),
            ),
        )
    )
    out = tmp_path / "skill_graph_code.py"

    assert main(["export-skills", "--store-dir", str(library.store_dir), "--out", str(out)]) == 0

    source = out.read_text(encoding="utf-8")
    assert "@skill(" in source
    assert "async def open_profile" in source


def test_code_graph_cli_export_graph_writes_source(tmp_path: Path) -> None:
    store = _graph_store(tmp_path / "graph")
    out = tmp_path / "skill_graph_code.py"

    assert main(["export-graph", "--store-dir", str(store.store_dir), "--out", str(out)]) == 0

    source = out.read_text(encoding="utf-8")
    assert "@state(" in source
    assert "@transition(" in source


def test_code_graph_cli_check_rejects_unsafe_code(tmp_path: Path) -> None:
    source_path = tmp_path / "unsafe.py"
    source_path.write_text("import os\n", encoding="utf-8")

    assert main(["check", str(source_path)]) == 1


def test_code_graph_cli_check_rejects_bad_transition_graph_source(tmp_path: Path) -> None:
    source_path = tmp_path / "bad_graph.py"
    source_path.write_text(
        '''
from opengui.skills.code_graph import C, R, action, state, transition

@state(app="com.example.app", platform="android")
def home():
    return C(required=[R(text="Home", visible=True)])

@transition(src=home, dst=missing_state)
async def open_missing(device):
    await action("tap", target="Missing")
''',
        encoding="utf-8",
    )

    assert main(["check", str(source_path)]) == 1


def test_code_graph_cli_compile_graph_writes_store(tmp_path: Path) -> None:
    source_store = _graph_store(tmp_path / "source")
    source_path = tmp_path / "skill_graph_code.py"
    source_path.write_text(export_graph_to_code(source_store), encoding="utf-8")
    target_dir = tmp_path / "compiled"

    assert main(["compile-graph", str(source_path), "--store-dir", str(target_dir)]) == 0

    compiled = SkillGraphStore(store_dir=target_dir)
    assert compiled.get_node("node-home") is not None
    assert compiled.get_edge("edge-profile") is not None


def test_code_graph_cli_compile_alias_writes_store(tmp_path: Path) -> None:
    source_store = _graph_store(tmp_path / "source")
    source_path = tmp_path / "skill_graph_code.py"
    source_path.write_text(export_graph_to_code(source_store), encoding="utf-8")
    target_dir = tmp_path / "compiled"

    assert main(["compile", str(source_path), "--store", str(target_dir)]) == 0

    compiled = SkillGraphStore(store_dir=target_dir)
    assert compiled.get_node("node-home") is not None
    assert compiled.get_edge("edge-profile") is not None


def test_code_graph_cli_extract_writes_canonical_code(tmp_path: Path, monkeypatch) -> None:
    import opengui.cli as opengui_cli

    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        json.dumps({"type": "step", "action": {"action_type": "tap", "target": "Profile"}})
        + "\n"
        + json.dumps({"type": "result", "success": True})
        + "\n",
        encoding="utf-8",
    )
    code = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android")
async def open_profile(device):
    await action("tap", target="Profile", state_contract=C(required=[R(text="Profile")]))
'''

    class FakeProvider:
        def __init__(self, **kwargs):
            del kwargs

        async def chat(self, messages, tools=None, tool_choice=None, model=None, max_tokens=None):
            del messages, tools, tool_choice, model, max_tokens
            return LLMResponse(content=json.dumps({
                "step_by_step_reasoning": "profile prefix",
                "python_code": code,
            }))

    monkeypatch.setattr(
        opengui_cli,
        "load_config",
        lambda path: SimpleNamespace(provider=SimpleNamespace(base_url="http://example", model="test", api_key=None)),
    )
    monkeypatch.setattr(opengui_cli, "OpenAICompatibleLLMProvider", FakeProvider)

    out_path = tmp_path / "skills" / "skill_graph_code.py"
    assert main(["extract", "--trace", str(trace_path), "--out", str(out_path), "--platform", "android"]) == 0

    source = out_path.read_text(encoding="utf-8")
    assert "@skill(" in source
    assert "async def open_profile" in source


def test_code_graph_cli_migrate_json_writes_code_graph_cache_and_marks_legacy(tmp_path: Path) -> None:
    store_dir = tmp_path / "skills"
    library = SkillLibrary(store_dir=store_dir)
    library.add(
        Skill(
            skill_id="skill-orders",
            name="open_orders",
            description="Open orders.",
            app="com.example.app",
            platform="android",
            tags=("orders",),
            steps=(
                SkillStep(
                    action_type="tap",
                    target="Orders",
                    state_contract=_contract("home"),
                ),
            ),
        )
    )

    assert main(["migrate-json", "--store-dir", str(store_dir)]) == 0

    source = (store_dir / "skill_graph_code.py").read_text(encoding="utf-8")
    graph = SkillGraphStore(store_dir=store_dir)

    assert "@skill(" in source
    assert "async def open_orders" in source
    assert graph.count_nodes > 0
    assert not (store_dir / "android" / "skills.json").exists()
    assert (store_dir / "android" / "skills.legacy.json").exists()
    assert (store_dir / "legacy_json_migration.json").exists()
