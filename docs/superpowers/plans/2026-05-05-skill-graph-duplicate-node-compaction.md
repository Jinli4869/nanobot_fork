# Skill Graph Duplicate Node Compaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge repeated graph nodes into stable canonical nodes so the same UI state compiles to one reusable path instead of spawning parallel skills.

**Architecture:** Keep `skill_graph.json` as the canonical store. Add a deterministic compaction pass that performs two safe operations only: exact merge for identical canonical states, and verified hard alias for auxiliary nodes that can be proven equivalent to a canonical state. Compaction rewrites edges, absorbs stats/provenance into the survivor, deletes the loser node, and records every action in a compaction log so the runtime stays auditable and idempotent.

**Tech Stack:** Python 3.12, `dataclasses`, the existing `SkillGraphStore`, `GraphNode`, `GraphEdge`, `PostRunProcessor`, `StateIdentifier`, `PathCompiler`, and `pytest` via `uv run pytest`.

---

## File Structure

- Modify `opengui/skills/graph.py`
  - Add the compaction report and compaction entrypoint.
  - Implement exact-duplicate grouping, survivor selection, node absorption, edge rewrite, and node deletion.
  - Implement verified hard-alias resolution for auxiliary nodes using stable contract/evidence.
  - Append compaction events to a JSONL log and refresh runtime indexes after mutation.
- Modify `opengui/postprocessing.py`
  - Call graph compaction after graph sync so newly extracted skills immediately collapse duplicates.
  - Keep the existing skill JSON schema unchanged.
- Modify `tests/test_opengui_skill_graph.py`
  - Add exact-merge tests, edge-rewrite tests, and hard-alias tests.
- Modify `tests/test_opengui_skill_graph_migration.py`
  - Add post-run graph sync tests that prove duplicate nodes are compacted, not preserved.
- Modify `tests/test_opengui_skill_graph_runtime.py`
  - Add a runtime regression proving graph lookups still return the canonical node after compaction.

---

### Task 1: Add deterministic exact-merge compaction

**Files:**
- Modify: `opengui/skills/graph.py`
- Test: `tests/test_opengui_skill_graph.py`

- [ ] **Step 1: Write the failing exact-merge regression**

Add a test that builds two active `state` nodes with the same `(platform, app, kind, fingerprint)` and one active edge pointing at the loser:

```python
def test_compact_canonical_graph_merges_exact_duplicate_state_nodes(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    survivor = store.upsert_node(
        GraphNode(
            node_id="node-home-a",
            app="com.max.xiaoheihe",
            platform="android",
            description="Home page is visible",
            state_contract=_contract("首页", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-home",
            stats=NodeStats(reach_count=3, contract_match_count=3, contract_miss_count=0),
        )
    )
    loser = store.upsert_node(
        GraphNode(
            node_id="node-home-b",
            app="com.max.xiaoheihe",
            platform="android",
            description="Home feed page is visible",
            state_contract=_contract("首页", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-home",
            stats=NodeStats(reach_count=2, contract_match_count=2, contract_miss_count=0),
        )
    )
    edge = store.upsert_edge(
        GraphEdge(
            edge_id="edge-home-orders",
            app="com.max.xiaoheihe",
            platform="android",
            source_node_id=loser.node_id,
            target_node_id="node-orders",
            action_type="tap",
            target="我的订单",
            parameters={"x": 712.0, "y": 930.0, "relative": True},
            status=EDGE_STATUS_ACTIVE,
        )
    )

    report = store.compact_canonical_graph()

    assert store.get_node(loser.node_id) is None
    assert store.get_node(survivor.node_id) is not None
    assert report.exact_merges == 1
    assert store.get_edge(edge.edge_id).source_node_id == survivor.node_id
```

- [ ] **Step 2: Run the exact-merge test and confirm it fails first**

Run:

```bash
uv run pytest tests/test_opengui_skill_graph.py::test_compact_canonical_graph_merges_exact_duplicate_state_nodes -q
```

Expected before implementation: fail because `compact_canonical_graph()` does not exist yet or does not rewrite/delete nodes.

- [ ] **Step 3: Implement exact-merge compaction**

In `opengui/skills/graph.py`, add a compaction entrypoint on `SkillGraphStore`:

```python
def compact_canonical_graph(self, *, save: bool = True) -> GraphCompactionReport:
    ...
```

Add a report dataclass:

```python
@dataclass(frozen=True)
class GraphCompactionReport:
    exact_merges: int
    hard_aliases: int
    deleted_nodes: int
    edge_rewrites: int
    disabled_edges: int
    candidates: int
    warnings: tuple[str, ...] = ()
```

Implement these exact-merge rules:

- Group nodes by `(platform, app, kind, fingerprint)`.
- Only merge active `state` nodes in the exact-merge path.
- Pick the survivor deterministically:
  - higher `NodeStats.contract_match_rate`
  - then higher `NodeStats.reach_count`
  - then higher `NodeStats.last_verified_at`
  - then lexicographically smaller `node_id`
- Absorb loser data into the survivor:
  - `stats` sum counts, keep the newest timestamps
  - `skill_ids` union and dedupe
  - `retrieval_profile` merge through the shared static selector filters already used by runtime/profile extraction (`filter_static_texts`, `filter_static_resource_ids`, `filter_static_controls`)
  - `description` and provenance remain on the survivor; loser identity goes to the compaction log
- Rewrite every edge that points to the loser so it points to the survivor.
- Delete the loser node after rewrite is complete.
- Delete any edge that becomes a self-loop after rewrite.
- Mark the graph index dirty after mutation.

- [ ] **Step 4: Run the exact-merge test again**

Run:

```bash
uv run pytest tests/test_opengui_skill_graph.py::test_compact_canonical_graph_merges_exact_duplicate_state_nodes -q
```

Expected after implementation: PASS.

- [ ] **Step 5: Commit**

```bash
git add opengui/skills/graph.py tests/test_opengui_skill_graph.py
git commit -m "feat: compact exact duplicate skill graph nodes"
```

---

### Task 2: Add verified hard-alias compaction for auxiliary nodes

**Files:**
- Modify: `opengui/skills/graph.py`
- Test: `tests/test_opengui_skill_graph.py`

- [ ] **Step 1: Write the failing hard-alias regressions**

Add two tests:

```python
def test_compact_canonical_graph_hard_aliases_verified_auxiliary_node(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    canonical = store.upsert_node(
        GraphNode(
            node_id="node-mall",
            app="com.max.xiaoheihe",
            platform="android",
            description="Heihei Mall page is visible",
            state_contract=_contract("黑盒商城", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-mall",
        )
    )
    alias = store.upsert_node(
        GraphNode(
            node_id="node-mall-aux",
            app="com.max.xiaoheihe",
            platform="android",
            description="Mall entry page evidence",
            kind=NODE_KIND_AUXILIARY,
            retrieval_profile={
                "foreground_app": "com.max.xiaoheihe",
                "visible_text": ["黑盒商城", "我的订单"],
                "stable_controls": [
                    {"text": "黑盒商城", "resource_id": "com.max.xiaoheihe:id/vg_menu_mall_v2"},
                ],
            },
            fingerprint="fp-mall-aux",
        )
    )

    store.append_transition_evidence({
        "platform": "android",
        "app": "com.max.xiaoheihe",
        "source_node_id": alias.node_id,
        "target_node_id": canonical.node_id,
        "edge_kind": "same_page",
        "reason": "same trace adjacent observation",
        "candidate_node_ids": [canonical.node_id],
    })

    report = store.compact_canonical_graph()

    assert store.get_node(alias.node_id) is None
    assert report.hard_aliases == 1
    assert any(
        edge.target_node_id == canonical.node_id
        for edge in store.list_edges(platform="android", app="com.max.xiaoheihe", status=EDGE_STATUS_ACTIVE)
    )
```

```python
def test_compact_canonical_graph_keeps_ambiguous_auxiliary_candidate(tmp_path: Path) -> None:
    store = SkillGraphStore(store_dir=tmp_path / "graph")
    canonical = store.upsert_node(
        GraphNode(
            node_id="node-profile",
            app="com.max.xiaoheihe",
            platform="android",
            description="Profile page is visible",
            state_contract=_contract("我的订单", app="com.max.xiaoheihe", clickable=True),
            fingerprint="fp-profile",
        )
    )
    ambiguous = store.upsert_node(
        GraphNode(
            node_id="node-profile-ambiguous",
            app="com.max.xiaoheihe",
            platform="android",
            description="The page contains 黑盒商城 text",
            kind=NODE_KIND_AUXILIARY,
            retrieval_profile={
                "foreground_app": "com.max.xiaoheihe",
                "visible_text": ["黑盒商城", "我的订单", "购物车"],
            },
            fingerprint="fp-ambiguous",
        )
    )

    report = store.compact_canonical_graph()

    assert store.get_node(ambiguous.node_id) is not None
    assert report.candidates >= 1
    assert report.hard_aliases == 0
```

- [ ] **Step 2: Run the hard-alias tests and confirm they fail first**

Run:

```bash
uv run pytest tests/test_opengui_skill_graph.py::test_compact_canonical_graph_hard_aliases_verified_auxiliary_node tests/test_opengui_skill_graph.py::test_compact_canonical_graph_keeps_ambiguous_auxiliary_candidate -q
```

Expected before implementation: fail because alias resolution is not yet deterministic enough and ambiguous auxiliary nodes are still treated as canonical candidates.

- [ ] **Step 3: Implement verified hard-alias resolution**

Add a helper in `opengui/skills/graph.py` that only hard-aliases an auxiliary node when one of these is true:

```python
def _is_verified_hard_alias(candidate: GraphNode, canonical: GraphNode, evidence: list[dict[str, Any]]) -> bool:
    ...
```

Use these rules only:

- contract equivalence: the auxiliary node can be normalized into the same canonical `state_contract.fingerprint` as the target canonical node
- trace adjacency equivalence: the auxiliary node and canonical node are linked by transition evidence from the same app/platform trace and their stable selectors/anchor evidence describe the same page

Do not hard-alias nodes based only on description text, page title, or other weak semantic similarity.

When a hard alias is accepted:

- absorb node stats, skill IDs, and retrieval profile into the canonical node
- rewrite all edges from the alias node to the canonical node
- delete the alias node
- write a hard-alias record to the compaction log with reason/evidence

When evidence is ambiguous:

- keep the auxiliary node
- leave its edges untouched
- record it as a compaction candidate only

- [ ] **Step 4: Run the hard-alias tests again**

Run:

```bash
uv run pytest tests/test_opengui_skill_graph.py::test_compact_canonical_graph_hard_aliases_verified_auxiliary_node tests/test_opengui_skill_graph.py::test_compact_canonical_graph_keeps_ambiguous_auxiliary_candidate -q
```

Expected after implementation: PASS.

- [ ] **Step 5: Commit**

```bash
git add opengui/skills/graph.py tests/test_opengui_skill_graph.py
git commit -m "feat: hard-alias verified auxiliary skill graph nodes"
```

---

### Task 3: Wire compaction into load and post-run sync

**Files:**
- Modify: `opengui/skills/graph.py`
- Modify: `opengui/postprocessing.py`
- Test: `tests/test_opengui_skill_graph_migration.py`
- Test: `tests/test_opengui_skill_graph_runtime.py`

- [ ] **Step 1: Write the failing post-run compaction test**

Add a test that ingests a skill, writes duplicate graph nodes through post-run sync, and confirms the persisted `skill_graph.json` has already compacted them:

```python
@pytest.mark.asyncio
async def test_postrun_graph_sync_compacts_duplicate_nodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ...
    await processor._extract_skill(trace_path, is_success=True, platform="android")
    graph_payload = json.loads((tmp_path / "store" / "skill_graph.json").read_text(encoding="utf-8"))
    assert len([node for node in graph_payload["nodes"] if node["kind"] == "state"]) == 1
```

- [ ] **Step 2: Run the post-run test and confirm it fails first**

Run:

```bash
uv run pytest tests/test_opengui_skill_graph_migration.py::test_postrun_graph_sync_compacts_duplicate_nodes -q
```

Expected before implementation: fail because extraction still persists duplicate nodes without a compaction pass.

- [ ] **Step 3: Wire compaction into the lifecycle**

In `opengui/postprocessing.py`, after graph sync finishes, call the new compaction entrypoint:

```python
graph = SkillGraphStore(store_dir=store_root / "skill_graph")
graph.compact_canonical_graph(save=True)
```

In `opengui/skills/graph.py`, keep the existing load-time cleanup, but extend it so load-time compaction is idempotent and runs before the runtime index is rebuilt.

After every successful compaction:

- persist the updated `skill_graph.json`
- persist the updated embeddings if node IDs changed
- mark the runtime index dirty
- rebuild the in-memory bucket/index structures before the next query

- [ ] **Step 4: Add a runtime regression that queries the canonical node after compaction**

Add a test in `tests/test_opengui_skill_graph_runtime.py` that seeds duplicate state nodes, compacts the graph, and confirms `StateIdentifier` or `GoalNodeResolver` returns the survivor node rather than the deleted loser.

- [ ] **Step 5: Run the lifecycle tests**

Run:

```bash
uv run pytest tests/test_opengui_skill_graph_migration.py::test_postrun_graph_sync_compacts_duplicate_nodes tests/test_opengui_skill_graph_runtime.py -k "compaction or alias or canonical" -q
```

Expected after implementation: PASS.

- [ ] **Step 6: Commit**

```bash
git add opengui/skills/graph.py opengui/postprocessing.py tests/test_opengui_skill_graph_migration.py tests/test_opengui_skill_graph_runtime.py
git commit -m "feat: wire skill graph compaction into runtime lifecycle"
```

---

### Task 4: Verify idempotence and auditability

**Files:**
- Modify: `opengui/skills/graph.py`
- Modify: `tests/test_opengui_skill_graph.py`
- Modify: `tests/test_opengui_skill_graph_migration.py`

- [ ] **Step 1: Write the idempotence and audit-log tests**

Add tests that:

```python
def test_compact_canonical_graph_is_idempotent(tmp_path: Path) -> None:
    ...
    first = store.compact_canonical_graph()
    second = store.compact_canonical_graph()
    assert second.exact_merges == 0
    assert second.hard_aliases == 0
    assert first.deleted_nodes >= 1
```

```python
def test_compaction_log_records_deleted_node_and_edge_rewrites(tmp_path: Path) -> None:
    ...
    log_path = tmp_path / "graph" / "skill_graph_compaction_log.jsonl"
    record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["deleted_node_id"] == "node-home-b"
    assert record["canonical_node_id"] == "node-home-a"
    assert record["edge_rewrites"] >= 1
```

- [ ] **Step 2: Run the idempotence/audit tests and confirm they fail first**

Run:

```bash
uv run pytest tests/test_opengui_skill_graph.py::test_compact_canonical_graph_is_idempotent tests/test_opengui_skill_graph_migration.py::test_compaction_log_records_deleted_node_and_edge_rewrites -q
```

Expected before implementation: fail because there is no dedicated compaction log and repeated compaction still mutates state.

- [ ] **Step 3: Implement the log and idempotence guard**

Add a JSONL compaction log file, for example:

```python
COMPACTION_LOG_FILENAME = "skill_graph_compaction_log.jsonl"
```

Each record must include:

- `timestamp`
- `platform`
- `app`
- `canonical_node_id`
- `deleted_node_id`
- `merge_kind` (`exact_merge` or `hard_alias`)
- `edge_rewrites`
- `reason`
- `evidence`

Ensure the second compaction run sees no remaining eligible duplicates and returns zero mutations.

- [ ] **Step 4: Run the idempotence/audit tests again**

Run:

```bash
uv run pytest tests/test_opengui_skill_graph.py::test_compact_canonical_graph_is_idempotent tests/test_opengui_skill_graph_migration.py::test_compaction_log_records_deleted_node_and_edge_rewrites -q
```

Expected after implementation: PASS.

- [ ] **Step 5: Commit**

```bash
git add opengui/skills/graph.py tests/test_opengui_skill_graph.py tests/test_opengui_skill_graph_migration.py
git commit -m "feat: make skill graph compaction auditable and idempotent"
```

---

## Self-Review

Coverage check:

- exact duplicate merge -> Task 1
- verified hard alias -> Task 2
- load/post-run lifecycle wiring -> Task 3
- idempotence and auditability -> Task 4
- runtime still resolves canonical nodes after compaction -> Task 3

No placeholder steps remain. Every task names concrete files, concrete tests, and concrete commands. No Neo4j or new persistence layer is introduced.
