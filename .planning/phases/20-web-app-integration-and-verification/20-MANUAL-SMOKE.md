# Phase 20 Manual Smoke

1. Build the frontend with `npm --prefix nanobot/tui/web run build`.
2. Start the local backend with `python -m nanobot.tui` or `nanobot-tui`.
3. Open `http://127.0.0.1:18791/` in a browser and confirm the workspace shell loads instead of a raw API response.
4. Create or resume a chat session and confirm the active `sessionId` is visible in the UI and URL.
5. Switch to Operations, confirm the selected session is still visible, and inspect one available run or runtime state panel.
6. Switch back to Chat and confirm the same session context remains present without manually reselecting it.
7. After the browser check, run one representative CLI command such as `nanobot --help` and confirm the existing CLI surface still works.
