---
phase: 7
slug: phase2-retroactive-verification
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-19
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.2 + pytest-asyncio |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest tests/test_opengui_p2_integration.py tests/test_opengui_p2_memory.py tests/test_opengui_p6_wiring.py -q` |
| **Full suite command** | `uv run pytest tests/ -x -q` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/test_opengui_p2_integration.py tests/test_opengui_p2_memory.py tests/test_opengui_p6_wiring.py -q`
- **After every plan wave:** Run `uv run pytest tests/test_opengui_p2_integration.py tests/test_opengui_p2_memory.py tests/test_opengui_p6_wiring.py -q`
- **Before `$gsd-verify-work`:** Run `uv run pytest tests/ -x -q`
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 1 | AGENT-04, AGENT-05, AGENT-06, MEM-05, SKILL-08, TRAJ-03, TEST-05 | integration | `uv run pytest tests/test_opengui_p2_integration.py tests/test_opengui_p2_memory.py tests/test_opengui_p6_wiring.py -q` | ✅ exists | ⬜ pending |
| 07-01-02 | 01 | 1 | AGENT-04, AGENT-05, AGENT-06, MEM-05, SKILL-08, TRAJ-03, TEST-05 | docs/static | `rg -n "AGENT-04|AGENT-05|AGENT-06|MEM-05|SKILL-08|TRAJ-03|TEST-05" .planning/phases/02-agent-loop-integration/VERIFICATION.md` | ✅ exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] Existing test infrastructure already covers all phase requirements.
- [x] Existing verification target file already exists at `.planning/phases/02-agent-loop-integration/VERIFICATION.md`.
- [x] Existing validation contract from Phase 2 (`02-VALIDATION.md`) provides the canonical quick/full commands for the requirement surface.
- [x] Phase 6 dependency coverage already exists in `tests/test_opengui_p6_wiring.py`.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Stale audit wording is resolved in the rewritten report | AGENT-04, AGENT-05, AGENT-06, MEM-05, SKILL-08, TRAJ-03, TEST-05 | The contradiction is historical/documentary, not executable | Read `.planning/v1.0-MILESTONE-AUDIT.md`, confirm it says Phase 2 verification was missing, then read `.planning/phases/02-agent-loop-integration/VERIFICATION.md` and confirm the report explicitly explains the discrepancy |

---

## Validation Sign-Off

- [x] All tasks have automated verification or static checks
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all required evidence inputs
- [x] No watch-mode flags
- [x] Feedback latency < 20s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending execution
