# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.1 — Background Execution

**Shipped:** 2026-03-20
**Phases:** 3 | **Plans:** 7 | **Sessions:** 1

### What Was Built
- A reusable virtual display protocol layer with `DisplayInfo`, `VirtualDisplayManager`, `NoOpDisplayManager`, and `XvfbDisplayManager`
- A production `BackgroundDesktopBackend` wrapper with DISPLAY lifecycle management, offset translation, and idempotent cleanup
- End-to-end background mode support in both the standalone CLI and nanobot GUI tool path

### What Worked
- The phase split was clean: protocol first, wrapper second, integration third
- Mocking at the subprocess boundary kept tests fast and CI-safe while still verifying realistic lifecycle behavior

### What Was Inefficient
- Summary metadata was inconsistent, leaving `MILESTONES.md` and the milestone audit under-informed until manually corrected
- Nyquist validation artifacts for phases 10 and 11 were left partial even though the product behavior shipped cleanly

### Patterns Established
- Virtual display support should be introduced behind a protocol, not by branching backend code directly
- Background execution should be integrated with warning-based platform fallback instead of hard failure on unsupported platforms

### Key Lessons
1. Capture milestone accomplishments in summary frontmatter or archive generation will be materially worse than the actual shipped work.
2. CI-safe background execution is practical when the subprocess boundary is the mocking seam, not the internal control flow.

### Cost Observations
- Model mix: n/a
- Sessions: 1
- Notable: v1.1 was implemented and validated in a compact single-day milestone with 678 passing tests at close.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.1 | 1 | 3 | Shifted milestone work toward smaller integration-focused phases with stronger test isolation |

### Cumulative Quality

| Milestone | Tests | Coverage | Zero-Dep Additions |
|-----------|-------|----------|-------------------|
| v1.1 | 678 passing | High regression confidence | Virtual display abstraction and Xvfb subprocess path |

### Top Lessons (Verified Across Milestones)

1. Test-first phase decomposition reduces integration risk when new infrastructure surfaces are added.
2. Planning artifacts need as much rigor as code artifacts if they are later used for audits and archives.
