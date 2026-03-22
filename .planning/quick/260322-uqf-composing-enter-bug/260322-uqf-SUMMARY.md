---
phase: quick
plan: 260322-uqf
subsystem: web-chat-ui
tags: [ime, ux, cleanup, tests]
dependency_graph:
  requires: [260322-ptr]
  provides: [ime-safe-enter, clean-shell-ui]
  affects: [MessageInput, WorkspaceShell, OperationsWorkspaceRoute]
tech_stack:
  added: []
  patterns: [isComposing-guard, scrollIntoView-mock]
key_files:
  created: []
  modified:
    - nanobot/tui/web/src/features/chat/components/MessageInput.tsx
    - nanobot/tui/web/src/app/shell.tsx
    - nanobot/tui/web/src/features/operations/OperationsWorkspaceRoute.tsx
    - nanobot/tui/web/src/app/shell.test.tsx
    - nanobot/tui/web/src/features/workspace-routes.test.tsx
decisions:
  - Use e.nativeEvent.isComposing (not e.isComposing) since React SyntheticEvent does not expose isComposing directly on KeyboardEvent
  - Use getByRole("heading") in shell.test to disambiguate h1 from eyebrow <p> — both contain "Nanobot Workspace"
  - Add Element.prototype.scrollIntoView = vi.fn() mock to both shell.test.tsx and workspace-routes.test.tsx since both test routes that render MessageList
metrics:
  duration: 3 min
  completed: 2026-03-22
---

# Phase quick Plan 260322-uqf: IME Composing Enter Bug + Shell Cleanup Summary

**One-liner:** IME composing guard via `e.nativeEvent.isComposing` prevents CJK Enter from sending; shell stripped of debug badges and phase-specific copy.

## Tasks Completed

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 | Fix IME composing Enter bug in MessageInput | 741d04c | MessageInput.tsx |
| 2 | Clean up shell header and operations debug UI, fix broken tests | a61f88b | shell.tsx, OperationsWorkspaceRoute.tsx, shell.test.tsx, workspace-routes.test.tsx |

## What Was Built

**Task 1 - IME guard:**
The `handleKeyDown` function in `MessageInput.tsx` now checks `!e.nativeEvent.isComposing` before dispatching a send. When a CJK IME session is active, pressing Enter confirms the composed character without triggering message submission. The existing Shift+Enter (newline) and non-composing Enter (send) behaviors are unchanged.

**Task 2 - Shell and operations cleanup:**
- `shell.tsx`: h1 text changed to "Nanobot Workspace"; development subtitle paragraph removed; `ContextBadge` row (Session/Run/Panel) removed; `ContextBadge` component removed; unused `shellStyles.subtitle`, `shellStyles.contextRow`, and `shellStyles.badge` removed.
- `OperationsWorkspaceRoute.tsx`: phase-specific dev description paragraph removed from heading section; `route-debug` paragraph removed.
- `shell.test.tsx`: stale assertions (Session: badge, run-9 badge, route-debug text, "Chat workspace") replaced with heading role and nav link checks; `scrollIntoView` jsdom mock added.
- `workspace-routes.test.tsx`: `"2 messages loaded"` assertion replaced with `"hello"` (actual message from mock data); `scrollIntoView` jsdom mock added.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing] Added scrollIntoView mock to shell.test.tsx**
- **Found during:** Task 2 verification (first test run)
- **Issue:** `MessageList` calls `bottomRef.current?.scrollIntoView(...)` in a `useEffect`. jsdom does not implement `scrollIntoView`, causing `TypeError: bottomRef.current?.scrollIntoView is not a function` in React's error boundary, crashing the `shell.test.tsx` render.
- **Fix:** Added `Element.prototype.scrollIntoView = vi.fn()` to `shell.test.tsx`'s `beforeEach` (the plan already called for this in `workspace-routes.test.tsx`; `shell.test.tsx` also needed it).
- **Files modified:** `shell.test.tsx`
- **Commit:** a61f88b

**2. [Rule 1 - Bug] Fixed getByText("Nanobot Workspace") multiple-match error in shell.test.tsx**
- **Found during:** Task 2 verification (first test run after scrollIntoView fix)
- **Issue:** Both the eyebrow `<p>` and the `<h1>` contain exactly "Nanobot Workspace", so `getByText` threw a multiple-elements error.
- **Fix:** Changed to `getByRole("heading", { name: "Nanobot Workspace" })` which uniquely targets the `<h1>`.
- **Files modified:** `shell.test.tsx`
- **Commit:** a61f88b

## Verification

All 5 frontend tests pass:
- src/lib/api/client.test.ts: 3/3 pass
- src/features/workspace-routes.test.tsx: 1/1 pass
- src/app/shell.test.tsx: 1/1 pass

## Self-Check: PASSED
