---
phase: quick
plan: 260322-uqf
type: execute
wave: 1
depends_on: []
files_modified:
  - nanobot/tui/web/src/features/chat/components/MessageInput.tsx
  - nanobot/tui/web/src/app/shell.tsx
  - nanobot/tui/web/src/features/operations/OperationsWorkspaceRoute.tsx
  - nanobot/tui/web/src/app/shell.test.tsx
  - nanobot/tui/web/src/features/workspace-routes.test.tsx
autonomous: true
requirements: []

must_haves:
  truths:
    - "Pressing Enter during Chinese IME composing confirms the character without sending the message"
    - "Pressing Enter outside of composing sends the message as before"
    - "Shell hero section shows clean workspace header without phase/implementation references"
    - "No debug context badges (Session/Run/Panel) visible in the shell header"
    - "No debug route text visible in Operations view"
    - "All frontend tests pass"
  artifacts:
    - path: "nanobot/tui/web/src/features/chat/components/MessageInput.tsx"
      provides: "IME-aware keyboard handler using isComposing guard"
      contains: "isComposing"
    - path: "nanobot/tui/web/src/app/shell.tsx"
      provides: "Clean workspace shell without debug/phase text"
    - path: "nanobot/tui/web/src/features/operations/OperationsWorkspaceRoute.tsx"
      provides: "Operations view without debug route display"
  key_links:
    - from: "MessageInput.tsx handleKeyDown"
      to: "submit()"
      via: "isComposing guard prevents send during IME composition"
      pattern: "isComposing"
---

<objective>
Fix two issues in the web chat UI: (1) Chinese IME composing Enter key incorrectly sends the message instead of confirming the composed character, and (2) clean up development-phase debug text and context badges from the shell header and operations view.

Purpose: Make the chat input usable for CJK language users and present a polished UI without internal development references.
Output: Fixed MessageInput with IME guard, cleaned shell and operations views, updated tests.
</objective>

<execution_context>
@/Users/jinli/.claude/get-shit-done/workflows/execute-plan.md
@/Users/jinli/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@nanobot/tui/web/src/features/chat/components/MessageInput.tsx
@nanobot/tui/web/src/app/shell.tsx
@nanobot/tui/web/src/features/operations/OperationsWorkspaceRoute.tsx
@nanobot/tui/web/src/app/shell.test.tsx
@nanobot/tui/web/src/features/workspace-routes.test.tsx
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix IME composing Enter bug in MessageInput</name>
  <files>nanobot/tui/web/src/features/chat/components/MessageInput.tsx</files>
  <action>
In the `handleKeyDown` function in MessageInput.tsx, add an `isComposing` guard to prevent sending during IME composition. The fix requires checking `e.nativeEvent.isComposing` (React's KeyboardEvent wraps the native event; the `isComposing` property lives on `nativeEvent`).

Change line 25 from:
```
if (e.key === "Enter" && !e.shiftKey) {
```
to:
```
if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
```

This ensures that when a user is composing CJK characters via an input method editor, pressing Enter to confirm the composed character does NOT trigger the message send. Only a non-composing Enter (i.e., after IME composition is complete or when not using IME) will send.

Note: Do NOT use `e.isComposing` directly — React's SyntheticEvent does not expose `isComposing` on the KeyboardEvent type. Access it via `e.nativeEvent.isComposing`. If TypeScript complains about `isComposing` not existing on `nativeEvent`, cast: `(e.nativeEvent as KeyboardEvent).isComposing`.
  </action>
  <verify>
    <automated>cd nanobot/tui/web && npx vitest run src/lib/api/client.test.ts --reporter=verbose 2>&1 | tail -10</automated>
  </verify>
  <done>handleKeyDown checks isComposing before sending, preventing IME Enter from triggering message dispatch</done>
</task>

<task type="auto">
  <name>Task 2: Clean up shell header and operations debug UI, fix broken tests</name>
  <files>
    nanobot/tui/web/src/app/shell.tsx
    nanobot/tui/web/src/features/operations/OperationsWorkspaceRoute.tsx
    nanobot/tui/web/src/app/shell.test.tsx
    nanobot/tui/web/src/features/workspace-routes.test.tsx
  </files>
  <action>
**shell.tsx changes:**

1. Replace the hero `<h1>` text from "One browser workspace for chat and operations." to "Nanobot Workspace" (simple, clean product name).

2. Remove the `<p style={shellStyles.subtitle}>` element entirely — it contains phase-specific implementation text ("Phase 20 starts by turning the backend contracts from Phases 17-19...") that is development noise.

3. Remove the entire `<div style={shellStyles.contextRow}>` block (lines 116-120) that renders the three ContextBadge components (Session, Run, Panel). These are debug badges not meant for end users.

4. Remove the `ContextBadge` function component entirely (lines 144-150) since it is no longer referenced.

5. Remove the unused `contextRow` and `badge` entries from `shellStyles` object.

6. Remove the `subtitle` entry from `shellStyles` object since it is no longer used.

7. Remove the unused import of `readWorkspaceState` and `buildChatHref`/`buildOperationsHref` ONLY if they become unused after removing the context badges. Check: `workspaceState` is still used by `buildChatHref` and `buildOperationsHref` for nav links, so `readWorkspaceState`, `buildChatHref`, and `buildOperationsHref` must stay.

**OperationsWorkspaceRoute.tsx changes:**

1. Remove the `<p data-testid="route-debug">` element (lines 63-65) that displays "Current route: ..." debug text.

2. Remove the development-description `<p>` inside the heading section (lines 20-23) that says "Operations now reads runtime status through the same typed client seam...". Replace with nothing (just remove it) — the "Operations console" heading is sufficient.

**shell.test.tsx changes:**

The test currently asserts on removed elements. Update the test:

1. Remove assertions for `screen.getByText("Session:")` (line 71) — context badges are gone.
2. Remove assertions for `screen.getAllByText("session-123")` and `screen.getAllByText("run-9")` that checked context badges (lines 72-73, 79-80, 86-87) — BUT keep the test's navigation logic intact.
3. Remove assertions for `screen.getByText(/Current route: .../)` (lines 74, 81, 88) — debug route text is gone.
4. Remove the assertion for `screen.getByText("Chat workspace")` (line 85) — this text does not exist in the new ChatWorkspaceRoute.
5. Replace removed assertions with valid checks that verify navigation still works:
   - After initial render at `/chat/session-123?runId=run-9&panel=trace`: assert `screen.getByText("Nanobot Workspace")` exists (the new hero title).
   - After clicking "Operations" link: assert `screen.getByText("Operations console")` exists.
   - After clicking "Chat" link back: assert the Chat nav link is present and active.

**workspace-routes.test.tsx changes:**

1. Replace line 84 `await screen.findByText("2 messages loaded")` — this text no longer exists after ChatWorkspaceRoute was rewritten. The new ChatWorkspaceRoute renders actual message bubbles. Replace with a check that the messages are actually rendered: `await screen.findByText("hello")` (the first user message from the mock data).

2. Remove assertions for `screen.getAllByText("session-123")` and `screen.getAllByText("run-9")` (lines 93-94) if they relied on context badges. Check: the Operations route still shows "Linked session" with session-123 in its own card, so `screen.getAllByText("session-123")` should still pass. Keep both assertions.

3. The `scrollIntoView` error in workspace-routes.test.tsx is because jsdom does not implement `scrollIntoView`. Add a mock in the `beforeEach`: `Element.prototype.scrollIntoView = vi.fn()`.
  </action>
  <verify>
    <automated>cd nanobot/tui/web && npx vitest run --reporter=verbose 2>&1 | tail -20</automated>
  </verify>
  <done>Shell shows "Nanobot Workspace" without debug badges or phase text, Operations view has no debug route line, all 5 tests pass (3 in client.test + 1 in shell.test + 1 in workspace-routes.test)</done>
</task>

</tasks>

<verification>
1. `cd nanobot/tui/web && npx vitest run --reporter=verbose` — all tests pass
2. Manual: open the web UI, switch to Chinese IME, type characters, press Enter to confirm composition — message should NOT send. Press Enter again (outside composing) — message sends.
3. Visual: shell header shows "Nanobot Workspace" with no phase/debug text, no Session/Run/Panel badges, Operations page has no "Current route:" debug line.
</verification>

<success_criteria>
- IME composing Enter does not trigger message send (isComposing guard in handleKeyDown)
- Shell hero section clean: shows "Nanobot Workspace" title, no subtitle, no context badges
- Operations view clean: no debug route paragraph
- All frontend tests (5 total) pass green
</success_criteria>

<output>
After completion, create `.planning/quick/260322-uqf-composing-enter-bug/260322-uqf-SUMMARY.md`
</output>
