from opengui.skills.code_graph import (
    C,
    R,
    compile_code_graph,
    compile_code_skills,
    export_graph_to_code,
    export_skills_to_code,
    render_code_tree,
    state,
    tag,
)
from opengui.skills.data import Skill, SkillStep
from opengui.skills.graph import GraphEdge, GraphNode, PathCompiler, SkillGraphStore
from opengui.skills.state_contract import normalize_state_contract


def test_state_dsl_normalizes_contract():
    @state(app="com.example.app", platform="android")
    def home():
        return C(required=[R(resource_id="com.example:id/home", visible=True)])

    contract = home.__opengui_state__.contract

    assert contract == normalize_state_contract({
        "anchor": {"app_package": "com.example.app"},
        "signature": {
            "required": [
                {
                    "selector": {"resource_id": "com.example:id/home"},
                    "state": ["visible"],
                }
            ],
            "forbidden": [],
        },
    })


def test_tag_dsl_captures_tags():
    @tag("contacts", "navigation")
    async def open_create_contact(device):
        return None

    assert open_create_contact.__opengui_tags__ == ("contacts", "navigation")


def test_compile_code_skill_to_skill_object():
    source = '''
from opengui.skills.code_graph import C, R, action, skill

@skill(app="com.example.app", platform="android", tags=["profile"])
async def open_profile(device):
    await action("tap", target="Profile", text="Profile")
    await action("tap", target="Settings", text="Settings")
'''

    result = compile_code_skills(source)

    assert result.errors == []
    assert len(result.skills) == 1
    compiled = result.skills[0]
    assert compiled.name == "open_profile"
    assert compiled.app == "com.example.app"
    assert compiled.platform == "android"
    assert compiled.tags == ("profile",)
    assert [step.action_type for step in compiled.steps] == ["tap", "tap"]


def test_export_skill_json_to_code_round_trips():
    contract = normalize_state_contract({
        "anchor": {"app_package": "com.example.app"},
        "signature": {
            "required": [
                {"selector": {"resource_id": "com.example:id/profile"}, "state": ["visible"]}
            ],
            "forbidden": [],
        },
    })
    original = Skill(
        skill_id="skill-profile",
        name="open_profile",
        description="Open the profile page.",
        app="com.example.app",
        platform="android",
        tags=("profile",),
        steps=(
            SkillStep(
                action_type="tap",
                target="Profile",
                parameters={"text": "Profile"},
                valid_state="Profile page is visible",
                state_contract=contract,
            ),
        ),
    )

    source = export_skills_to_code([original])
    result = compile_code_skills(source)

    assert result.errors == []
    assert result.skills[0].steps[0].state_contract == contract


def test_export_skill_round_trip_preserves_step_execution_metadata():
    original = Skill(
        skill_id="skill-fixed",
        name="open_profile",
        description="Open the profile page.",
        app="com.example.app",
        platform="android",
        tags=("profile",),
        steps=(
            SkillStep(
                action_type="tap",
                target="Profile",
                parameters={"text": "Profile"},
                expected_state="Profile screen should open",
                valid_state="Profile page is visible",
                fixed=True,
                fixed_values={"text": "Profile"},
            ),
        ),
    )

    result = compile_code_skills(export_skills_to_code([original]))

    assert result.errors == []
    compiled_step = result.skills[0].steps[0]
    assert compiled_step.expected_state == "Profile screen should open"
    assert compiled_step.valid_state == "Profile page is visible"
    assert compiled_step.fixed is True
    assert compiled_step.fixed_values == {"text": "Profile"}


def test_export_skill_round_trip_preserves_skill_parameters():
    original = Skill(
        skill_id="skill-contact",
        name="add_contact",
        description="Add a contact.",
        app="com.example.contacts",
        platform="android",
        parameters=("full_name", "phone_number"),
        steps=(
            SkillStep(
                action_type="input_text",
                target="First name",
                parameters={"text": "{{full_name}}"},
            ),
            SkillStep(
                action_type="input_text",
                target="Phone",
                parameters={"text": "{{phone_number}}"},
            ),
        ),
    )

    source = export_skills_to_code([original])
    result = compile_code_skills(source)

    assert result.errors == []
    assert "async def add_contact(device, full_name, phone_number):" in source
    assert result.skills[0].parameters == ("full_name", "phone_number")
    assert result.skills[0].steps[0].parameters["text"] == "{{full_name}}"
    assert result.skills[0].steps[1].parameters["text"] == "{{phone_number}}"


def test_compile_helper_call_binds_actual_arguments_to_helper_parameters():
    source = '''
from opengui.skills.code_graph import action, skill

async def fill_name(device, name):
    await action("input_text", target="First name", text=name)

@skill(app="com.example.contacts", platform="android", tags=["contacts"])
async def add_contact(device, full_name):
    await fill_name(device, full_name)
'''

    result = compile_code_skills(source)

    assert result.errors == []
    assert result.skills[0].parameters == ("full_name",)
    assert result.skills[0].steps[0].parameters["text"] == "{{full_name}}"


def test_compile_unsupported_action_expression_returns_errors():
    source = '''
from opengui.skills.code_graph import action, skill

@skill(app="com.example.app", platform="android", tags=["profile"])
async def open_profile(device):
    await action("tap", target=f"Profile {device}")
'''

    result = compile_code_skills(source)

    assert result.skills == ()
    assert result.errors
    assert "unsupported expression" in result.errors[0]


def test_compile_helper_binds_state_contract_parameters():
    source = '''
from opengui.skills.code_graph import C, R, action, skill

async def assert_item(device, label):
    await action("tap", target="Item", state_contract=C(required=[R(text=label)]))

@skill(app="com.example.app", platform="android", tags=["items"])
async def open_item(device, item_name):
    await assert_item(device, item_name)
'''

    result = compile_code_skills(source)

    assert result.errors == []
    contract = result.skills[0].steps[0].state_contract
    required = contract["signature"]["required"]
    assert required[0]["selector"]["text"] == "{{item_name}}"


def test_export_skill_sanitizes_non_identifier_parameters_and_placeholders():
    original = Skill(
        skill_id="skill-search",
        name="search_items",
        description="Search items.",
        app="com.example.app",
        platform="android",
        parameters=("search-query", "class", "1st_name"),
        steps=(
            SkillStep(
                action_type="input_text",
                target="Search",
                parameters={
                    "query": "{{search-query}}",
                    "css_class": "{{class}}",
                    "name": "{{1st_name}}",
                },
            ),
        ),
    )

    source = export_skills_to_code([original])
    result = compile_code_skills(source)

    assert result.errors == []
    assert "async def search_items(device, search_query, class_, param_1st_name):" in source
    assert result.skills[0].parameters == ("search_query", "class_", "param_1st_name")
    assert result.skills[0].steps[0].parameters == {
        "query": "{{search_query}}",
        "css_class": "{{class_}}",
        "name": "{{param_1st_name}}",
    }


def test_compile_recursive_helper_returns_error():
    source = '''
from opengui.skills.code_graph import action, skill

async def helper(device):
    await bad(device)

async def bad(device):
    await helper(device)

@skill(app="com.example.app", platform="android", tags=["bad"])
async def run_bad(device):
    await bad(device)
'''

    result = compile_code_skills(source)

    assert result.skills == ()
    assert result.errors
    assert "recursive helper call" in result.errors[0]


async def test_export_graph_json_to_code_round_trips(tmp_path):
    source_contract = normalize_state_contract({
        "anchor": {"app_package": "com.example.app"},
        "signature": {
            "required": [
                {
                    "selector": {"resource_id": "com.example:id/home"},
                    "state": ["visible"],
                }
            ],
            "forbidden": [],
        },
    })
    target_contract = normalize_state_contract({
        "anchor": {"app_package": "com.example.app"},
        "signature": {
            "required": [
                {
                    "selector": {"resource_id": "com.example:id/profile"},
                    "state": ["visible"],
                }
            ],
            "forbidden": [],
        },
    })
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    source = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home screen",
            state_contract=source_contract,
            fingerprint="fp-home",
            source_ref={
                "path": "skill_graph_code.py",
                "symbol": "state_node_home",
                "line": 4,
                "kind": "state",
            },
        ),
        save=False,
    )
    target = store.upsert_node(
        GraphNode(
            node_id="node-profile",
            app="com.example.app",
            platform="android",
            description="Profile screen",
            state_contract=target_contract,
            fingerprint="fp-profile",
            source_ref={
                "path": "skill_graph_code.py",
                "symbol": "state_node_profile",
                "line": 9,
                "kind": "state",
            },
        ),
        save=False,
    )
    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-home-profile",
            app="com.example.app",
            platform="android",
            source_node_id=source.node_id,
            target_node_id=target.node_id,
            action_type="tap",
            target="Profile",
            parameters={"text": "Profile"},
            precondition=source.state_contract,
            skill_id="skill-profile",
            source_ref={
                "path": "skill_graph_code.py",
                "symbol": "edge_home_profile",
                "line": 14,
                "kind": "transition",
            },
        ),
        save=False,
    )
    store.save()
    reloaded = SkillGraphStore(store_dir=tmp_path / "graph")
    assert reloaded.get_node(source.node_id).source_ref == source.source_ref
    assert reloaded.get_edge(edge.edge_id).source_ref == edge.source_ref

    code = export_graph_to_code(reloaded)
    compiled_store = SkillGraphStore(store_dir=tmp_path / "compiled")
    result = await compile_code_graph(code, compiled_store)

    assert result.errors == []
    compiled_source = compiled_store.get_node(source.node_id)
    compiled_target = compiled_store.get_node(target.node_id)
    compiled_edge = compiled_store.get_edge(edge.edge_id)
    assert compiled_source is not None
    assert compiled_target is not None
    assert compiled_edge is not None
    assert compiled_source.state_contract == source.state_contract
    assert compiled_target.state_contract == target.state_contract
    assert compiled_source.source_ref == source.source_ref
    assert compiled_edge.source_ref == edge.source_ref
    assert compiled_edge.parameters == {"text": "Profile"}
    assert compiled_edge.precondition == source.state_contract
    path = PathCompiler(compiled_store).compile(source.node_id, target.node_id)
    assert path.status == "ok"
    assert [path_edge.edge_id for path_edge in path.edges] == [edge.edge_id]


async def test_compile_code_graph_error_leaves_target_store_empty(tmp_path):
    source = '''
from opengui.skills.code_graph import C, R, action, state, transition

@state(app="com.example.app", platform="android", node_id="node-home")
def home():
    return C(required=[R(text="Home", visible=True)])

@transition(src=home, dst=missing_state, edge_id="edge-bad")
async def open_missing(device):
    await action("tap", target="Missing")
'''
    target_store = SkillGraphStore(store_dir=tmp_path / "target")

    result = await compile_code_graph(source, target_store)

    assert result.errors
    assert result.nodes == ()
    assert result.edges == ()
    assert target_store.list_nodes() == []
    assert target_store.list_edges() == []


async def test_compile_code_graph_requires_transition_state_contract(tmp_path):
    source = '''
from opengui.skills.code_graph import C, R, action, state, transition

@state(app="com.example.app", platform="android", node_id="node-home")
def home():
    return C(required=[R(text="Home", visible=True)])

@state(app="com.example.app", platform="android", node_id="node-profile")
def profile():
    return C(required=[R(text="Profile", visible=True)])

@transition(src=home, dst=profile, edge_id="edge-profile")
async def open_profile(device):
    await action("tap", target="Profile")
'''
    target_store = SkillGraphStore(store_dir=tmp_path / "target")

    result = await compile_code_graph(source, target_store)

    assert result.errors
    assert "missing state_contract" in result.errors[0]
    assert target_store.list_nodes() == []
    assert target_store.list_edges() == []


async def test_compile_code_graph_allows_explicit_unchecked_transition(tmp_path):
    source = '''
from opengui.skills.code_graph import C, R, action, state, transition

@state(app="com.example.app", platform="android", node_id="node-home")
def home():
    return C(required=[R(text="Home", visible=True)])

@state(app="com.example.app", platform="android", node_id="node-profile")
def profile():
    return C(required=[R(text="Profile", visible=True)])

@transition(src=home, dst=profile, edge_id="edge-profile", unchecked=True)
async def open_profile(device):
    await action("tap", target="Profile")
'''
    target_store = SkillGraphStore(store_dir=tmp_path / "target")

    result = await compile_code_graph(source, target_store)

    assert result.errors == []
    assert target_store.get_edge("edge-profile") is not None


def test_render_code_tree_shows_containment():
    source = '''
from opengui.skills.code_graph import action, skill, transition

async def open_create_contact(device):
    await action("tap", target="Create contact")

async def fill_contact_form(device):
    await action("input_text", target="First name")

@skill(app="com.android.contacts", platform="android", tags=["contacts"])
async def add_contact(device):
    await open_create_contact(device)
    await fill_contact_form(device)
'''

    assert render_code_tree(source) == "\n".join([
        "add_contact [skill]",
        "  open_create_contact [transition]",
        "  fill_contact_form [transition]",
    ])
    assert render_code_tree(source, format="mermaid") == "\n".join([
        "graph TD",
        '  add_contact["add_contact (skill)"]',
        '  open_create_contact["open_create_contact (transition)"]',
        '  fill_contact_form["fill_contact_form (transition)"]',
        "  add_contact --> open_create_contact",
        "  add_contact --> fill_contact_form",
    ])


def test_render_code_tree_shows_graph_only_state_transition_structure(tmp_path):
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    source = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home",
            state_contract=normalize_state_contract({
                "anchor": {"app_package": "com.example.app"},
                "signature": {
                    "required": [
                        {"selector": {"text": "Home"}, "state": ["visible"]},
                    ],
                    "forbidden": [],
                },
            }),
            source_ref={"symbol": "home_state", "kind": "state"},
        ),
        save=False,
    )
    target = store.upsert_node(
        GraphNode(
            node_id="node-profile",
            app="com.example.app",
            platform="android",
            description="Profile",
            state_contract=normalize_state_contract({
                "anchor": {"app_package": "com.example.app"},
                "signature": {
                    "required": [
                        {"selector": {"text": "Profile"}, "state": ["visible"]},
                    ],
                    "forbidden": [],
                },
            }),
            source_ref={"symbol": "profile_state", "kind": "state"},
        ),
        save=False,
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-open-profile",
            app="com.example.app",
            platform="android",
            source_node_id=source.node_id,
            target_node_id=target.node_id,
            action_type="tap",
            target="Profile",
            precondition=source.state_contract,
            source_ref={"symbol": "open_profile", "kind": "transition"},
        ),
        save=False,
    )

    code = export_graph_to_code(store)

    assert render_code_tree(code) == "\n".join([
        "home_state [state]",
        "  open_profile [transition]",
        "    profile_state [state]",
    ])


def test_render_code_tree_shows_mixed_skill_and_graph_structure():
    source = '''
from opengui.skills.code_graph import C, R, action, skill, state, transition

@skill(app="com.example.app", platform="android", tags=["orders"])
async def open_orders(device):
    await action("tap", target="Orders")

@state(app="com.example.app", platform="android", node_id="node-home")
def home():
    return C(required=[R(text="Home", visible=True)])

@state(app="com.example.app", platform="android", node_id="node-orders")
def orders():
    return C(required=[R(text="Orders", visible=True)])

@transition(src=home, dst=orders, edge_id="edge-orders", unchecked=True)
async def go_orders(device):
    await action("tap", target="Orders")
'''

    assert render_code_tree(source) == "\n".join([
        "open_orders [skill]",
        "home [state]",
        "  go_orders [transition]",
        "    orders [state]",
    ])

    mermaid = render_code_tree(source, format="mermaid")
    assert 'open_orders["open_orders (skill)"]' in mermaid
    assert 'home["home (state)"]' in mermaid
    assert "home --> go_orders" in mermaid
    assert "go_orders --> orders" in mermaid


def test_render_code_tree_mermaid_shows_graph_only_multihop_structure(tmp_path):
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    home = store.upsert_node(
        GraphNode(
            node_id="node-home",
            app="com.example.app",
            platform="android",
            description="Home",
            state_contract=normalize_state_contract({
                "anchor": {"app_package": "com.example.app"},
                "signature": {
                    "required": [
                        {"selector": {"text": "Home"}, "state": ["visible"]},
                    ],
                    "forbidden": [],
                },
            }),
            source_ref={"symbol": "home", "kind": "state"},
        ),
        save=False,
    )
    middle = store.upsert_node(
        GraphNode(
            node_id="node-middle",
            app="com.example.app",
            platform="android",
            description="Middle",
            state_contract=normalize_state_contract({
                "anchor": {"app_package": "com.example.app"},
                "signature": {
                    "required": [
                        {"selector": {"text": "Middle"}, "state": ["visible"]},
                    ],
                    "forbidden": [],
                },
            }),
            source_ref={"symbol": "middle", "kind": "state"},
        ),
        save=False,
    )
    target = store.upsert_node(
        GraphNode(
            node_id="node-target",
            app="com.example.app",
            platform="android",
            description="Target",
            state_contract=normalize_state_contract({
                "anchor": {"app_package": "com.example.app"},
                "signature": {
                    "required": [
                        {"selector": {"text": "Target"}, "state": ["visible"]},
                    ],
                    "forbidden": [],
                },
            }),
            source_ref={"symbol": "target", "kind": "state"},
        ),
        save=False,
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-go-middle",
            app="com.example.app",
            platform="android",
            source_node_id=home.node_id,
            target_node_id=middle.node_id,
            action_type="tap",
            target="Middle",
            precondition=home.state_contract,
            source_ref={"symbol": "go_middle", "kind": "transition"},
        ),
        save=False,
    )
    store.upsert_edge(
        GraphEdge(
            edge_id="edge-go-target",
            app="com.example.app",
            platform="android",
            source_node_id=middle.node_id,
            target_node_id=target.node_id,
            action_type="tap",
            target="Target",
            precondition=middle.state_contract,
            source_ref={"symbol": "go_target", "kind": "transition"},
        ),
        save=False,
    )

    mermaid = render_code_tree(export_graph_to_code(store), format="mermaid")

    assert '  go_target["go_target (transition)"]' in mermaid
    assert '  target["target (state)"]' in mermaid
    assert "  middle --> go_target" in mermaid
    assert "  go_target --> target" in mermaid
