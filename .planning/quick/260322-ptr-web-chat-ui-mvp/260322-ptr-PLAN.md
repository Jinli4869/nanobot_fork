---
phase: quick
plan: 260322-ptr
type: execute
wave: 1
depends_on: []
files_modified:
  - nanobot/tui/web/package.json
  - nanobot/tui/web/tailwind.config.ts
  - nanobot/tui/web/postcss.config.cjs
  - nanobot/tui/web/vite.config.ts
  - nanobot/tui/web/src/index.css
  - nanobot/tui/web/src/main.tsx
  - nanobot/tui/web/src/lib/api/client.ts
  - nanobot/tui/web/src/features/chat/components/MessageBubble.tsx
  - nanobot/tui/web/src/features/chat/components/MessageList.tsx
  - nanobot/tui/web/src/features/chat/components/MessageInput.tsx
  - nanobot/tui/web/src/features/chat/components/SessionSidebar.tsx
  - nanobot/tui/web/src/features/chat/hooks/useChatStream.ts
  - nanobot/tui/web/src/features/chat/hooks/useSessionManager.ts
  - nanobot/tui/web/src/features/chat/ChatWorkspaceRoute.tsx
autonomous: true
must_haves:
  truths:
    - "User sees a sidebar listing chat sessions with a New Chat button"
    - "User can type a message in the input box and send it"
    - "User messages appear right-aligned, assistant messages left-aligned"
    - "Assistant responses stream in progressively via SSE"
    - "Selecting a session loads its message history"
    - "Creating a new session navigates to it and starts fresh"
  artifacts:
    - path: "nanobot/tui/web/src/features/chat/ChatWorkspaceRoute.tsx"
      provides: "Full chat workspace layout with sidebar + chat area"
    - path: "nanobot/tui/web/src/features/chat/components/MessageList.tsx"
      provides: "Scrollable message list with auto-scroll"
    - path: "nanobot/tui/web/src/features/chat/components/MessageInput.tsx"
      provides: "Textarea with send button"
    - path: "nanobot/tui/web/src/features/chat/hooks/useChatStream.ts"
      provides: "SSE streaming hook"
  key_links:
    - from: "MessageInput"
      to: "POST /chat/sessions/{id}/messages"
      via: "fetchJson in onSend callback"
    - from: "useChatStream"
      to: "connectChatEvents"
      via: "SSE connection on active session"
    - from: "ChatWorkspaceRoute"
      to: "react-router navigate"
      via: "session selection navigates to /chat/{sessionId}"
---

<objective>
Replace the debug-card ChatWorkspaceRoute with a fully functional chat UI featuring session sidebar, message bubbles, text input, and SSE streaming. Install Tailwind CSS for styling.

Purpose: Make the web chat workspace usable for real conversations with the nanobot backend.
Output: Working chat UI at /chat and /chat/:sessionId routes with Tailwind styling.
</objective>

<execution_context>
@/Users/jinli/.claude/get-shit-done/workflows/execute-plan.md
@/Users/jinli/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@nanobot/tui/web/src/lib/api/client.ts
@nanobot/tui/web/src/lib/chat-events.ts
@nanobot/tui/web/src/lib/workspace-state.ts
@nanobot/tui/web/src/app/shell.tsx
@nanobot/tui/web/src/app/router.tsx
@nanobot/tui/web/src/main.tsx
@nanobot/tui/web/vite.config.ts
@nanobot/tui/web/package.json
@nanobot/tui/web/index.html

<interfaces>
<!-- Existing API client exports to use directly -->
From src/lib/api/client.ts:
```typescript
export type ChatMessage = { role: string; content: string; timestamp?: string | null };
export type ChatSessionSummary = { session_id: string; session_key: string; created_at?: string | null; updated_at?: string | null; metadata: Record<string, unknown>; message_count: number };
export type ChatSessionResponse = { session: ChatSessionSummary; messages: ChatMessage[] };
export function fetchJson<T>(path: string, init?: RequestInit, env?: ApiEnv): Promise<T>;
export function getChatSession(sessionId: string, env?: ApiEnv): Promise<ChatSessionResponse>;
export function resolveApiUrl(path: string, env?: ApiEnv): string;
```

From src/lib/chat-events.ts:
```typescript
export type ChatEvent = { id: string; type: string; session_id: string; run_id?: string | null; payload: Record<string, unknown> };
export function connectChatEvents(sessionId: string, onEvent: (event: ChatEvent) => void, env?: ApiEnv): () => void;
```
Event types: "message.accepted" (user msg ack), "progress" (partial assistant text in payload.content), "assistant.final" (complete assistant msg in payload.content), "error" (payload.message), "complete" (stream done)

From src/lib/workspace-state.ts:
```typescript
export type WorkspaceState = { sessionId: string | null; runId: string | null; panel: string | null };
export function readWorkspaceState(pathname: string, search: string): WorkspaceState;
export function buildChatHref(state: WorkspaceState): string;
```

Backend API contract:
- POST /chat/sessions -> { session: ChatSessionSummary, messages: [] }
- GET /chat/sessions/{id} -> { session: ChatSessionSummary, messages: ChatMessage[] }
- POST /chat/sessions/{id}/messages -> { session: ChatSessionSummary, reply: ChatMessage } (body: { content: string })
- GET /chat/sessions/{id}/events -> SSE stream of ChatEvent

NOTE: There is no GET /chat/sessions (list all) endpoint. Session IDs must be tracked client-side via localStorage.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Install Tailwind CSS and create chat UI components</name>
  <files>
    nanobot/tui/web/package.json
    nanobot/tui/web/tailwind.config.ts
    nanobot/tui/web/postcss.config.cjs
    nanobot/tui/web/vite.config.ts
    nanobot/tui/web/src/index.css
    nanobot/tui/web/src/main.tsx
    nanobot/tui/web/src/lib/api/client.ts
    nanobot/tui/web/src/features/chat/components/MessageBubble.tsx
    nanobot/tui/web/src/features/chat/components/MessageList.tsx
    nanobot/tui/web/src/features/chat/components/MessageInput.tsx
    nanobot/tui/web/src/features/chat/components/SessionSidebar.tsx
  </files>
  <action>
1. Install Tailwind CSS v4 + dependencies:
   ```
   cd nanobot/tui/web && npm install -D tailwindcss @tailwindcss/vite
   ```
   Tailwind v4 uses the Vite plugin directly (no PostCSS config needed). Add `@tailwindcss/vite` plugin to vite.config.ts BEFORE the react plugin. No tailwind.config.ts or postcss.config.cjs needed for v4.

2. Create `src/index.css` with Tailwind v4 import:
   ```css
   @import "tailwindcss";
   ```
   Add a custom theme section preserving the earth-tone palette from shell.tsx:
   ```css
   @theme {
     --color-earth-bg: rgb(244 239 231);
     --color-earth-card: rgba(255 253 248 / 0.9);
     --color-earth-border: rgba(94 109 82 / 0.18);
     --color-earth-text: rgb(33 37 34);
     --color-earth-muted: rgb(72 79 74);
     --color-earth-accent: rgb(55 76 61);
     --color-earth-accent-light: rgb(96 111 81);
     --color-earth-badge: rgba(232 240 232 / 0.9);
     --color-user-bubble: rgb(55 76 61);
     --color-user-bubble-text: rgb(251 248 241);
     --color-assistant-bubble: rgba(246 248 245 / 0.95);
   }
   ```

3. Update `src/main.tsx`: Add `import "./index.css";` at the top (before other imports).

4. Add missing types to `src/lib/api/client.ts` (append, do NOT rewrite existing code):
   ```typescript
   export type ChatCreateSessionResponse = { session: ChatSessionSummary; messages: ChatMessage[] };
   export type ChatMessageResponse = { session: ChatSessionSummary; reply: ChatMessage };

   export function createChatSession(env?: ApiEnv) {
     return fetchJson<ChatCreateSessionResponse>("/chat/sessions", { method: "POST" }, env);
   }

   export function sendChatMessage(sessionId: string, content: string, env?: ApiEnv) {
     return fetchJson<ChatMessageResponse>(`/chat/sessions/${sessionId}/messages`, {
       method: "POST",
       headers: { "Content-Type": "application/json" },
       body: JSON.stringify({ content }),
     }, env);
   }
   ```

5. Create `MessageBubble.tsx`:
   - Props: `message: ChatMessage`, `isStreaming?: boolean`
   - Determine alignment from `message.role`: "user" right-aligned, everything else left-aligned
   - User bubble: `bg-user-bubble text-user-bubble-text` rounded-2xl px-4 py-3 max-w-[80%] ml-auto
   - Assistant bubble: `bg-assistant-bubble border border-earth-border` rounded-2xl px-4 py-3 max-w-[80%]
   - If isStreaming, show a blinking cursor indicator (a small pulsing dot via `animate-pulse`) after the text
   - Render content as whitespace-pre-wrap to preserve formatting
   - Show timestamp if present, formatted with toLocaleTimeString(), in a small muted text below the bubble

6. Create `MessageList.tsx`:
   - Props: `messages: ChatMessage[]`, `streamingContent?: string | null`
   - Render a scrollable container: `flex flex-col gap-3 overflow-y-auto flex-1 p-4`
   - Map messages to MessageBubble components, keyed by index (messages are append-only)
   - If `streamingContent` is truthy, render one additional MessageBubble with `role: "assistant"`, `content: streamingContent`, `isStreaming: true`
   - Use a ref + useEffect to auto-scroll to bottom when messages change or streamingContent updates
   - Show empty state when no messages: centered muted text "Start a conversation..."

7. Create `MessageInput.tsx`:
   - Props: `onSend: (content: string) => void`, `disabled?: boolean`
   - Textarea + send button in a row layout: `flex items-end gap-2 p-4 border-t border-earth-border`
   - Textarea: `flex-1 resize-none rounded-xl border border-earth-border bg-white px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-earth-accent/30` with rows=1, max-rows behavior via auto-resize
   - Auto-resize: on input, set height=auto then height=scrollHeight, cap at 150px
   - Send button: `rounded-xl bg-earth-accent text-white px-4 py-3 hover:opacity-90 disabled:opacity-40`
   - Enter sends (without shift), Shift+Enter for newline
   - Clear textarea after send
   - Disable textarea and button when `disabled` is true

8. Create `SessionSidebar.tsx`:
   - Props: `sessions: Array<{ id: string; title: string; updatedAt?: string }>`, `activeSessionId: string | null`, `onSelectSession: (id: string) => void`, `onNewSession: () => void`
   - Layout: `w-64 border-r border-earth-border flex flex-col bg-earth-card`
   - Header with "New Chat" button: `m-3 rounded-xl bg-earth-accent text-white py-2.5 text-center text-sm hover:opacity-90`
   - Session list: scrollable `flex-1 overflow-y-auto`
   - Each session item: `px-3 py-2.5 mx-2 my-0.5 rounded-lg cursor-pointer text-sm truncate hover:bg-earth-badge`
   - Active session: `bg-earth-badge font-medium`
   - Show session title (first message content truncated, or "New Chat" if empty) and relative time
  </action>
  <verify>
    <automated>cd /Users/jinli/Documents/Personal/nanobot_fork/nanobot/tui/web && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>Tailwind v4 installed with earth-tone theme. Four chat components (MessageBubble, MessageList, MessageInput, SessionSidebar) compile without type errors. API client extended with createChatSession and sendChatMessage functions.</done>
</task>

<task type="auto">
  <name>Task 2: Wire chat hooks and replace ChatWorkspaceRoute with full chat UI</name>
  <files>
    nanobot/tui/web/src/features/chat/hooks/useChatStream.ts
    nanobot/tui/web/src/features/chat/hooks/useSessionManager.ts
    nanobot/tui/web/src/features/chat/ChatWorkspaceRoute.tsx
  </files>
  <action>
1. Create `useChatStream.ts` hook:
   - Manages SSE streaming state for the active session
   - State: `streamingContent: string | null` (partial assistant text being assembled)
   - Takes `sessionId: string | null` and `onAssistantMessage: (msg: ChatMessage) => void` callback
   - On mount (when sessionId is truthy), call `connectChatEvents(sessionId, handleEvent)`
   - Event handling:
     - "message.accepted": no-op (user message was acknowledged)
     - "progress": append `event.payload.content` (string) to streamingContent. IMPORTANT: payload.content is a delta/chunk, so concatenate: `setStreamingContent(prev => (prev ?? "") + (event.payload.content as string))`
     - "assistant.final": call `onAssistantMessage({ role: "assistant", content: event.payload.content as string })`, then set streamingContent to null
     - "error": call `onAssistantMessage({ role: "assistant", content: "[Error] " + (event.payload.message as string) })`, set streamingContent to null
     - "complete": set streamingContent to null (cleanup)
   - Cleanup: return the disconnect function from connectChatEvents in useEffect cleanup
   - Return: `{ streamingContent }`

2. Create `useSessionManager.ts` hook:
   - Manages session list in localStorage under key "nanobot-chat-sessions"
   - Stored shape: `Array<{ id: string; title: string; updatedAt: string }>`
   - Functions:
     - `getSessions()`: read from localStorage, parse JSON, return sorted by updatedAt descending. Handle missing/corrupt JSON gracefully (return []).
     - `addSession(id: string, title?: string)`: prepend to list, write back. Default title: "New Chat"
     - `updateSessionTitle(id: string, title: string)`: find by id, update title + updatedAt, write back
     - `removeSession(id: string)`: filter out, write back
   - Use `useSyncExternalStore` or just `useState` + manual sync. Simplest: `useState` initialized from localStorage, write-through on every mutation.
   - Return: `{ sessions, addSession, updateSessionTitle, removeSession }`

3. Rewrite `ChatWorkspaceRoute.tsx` completely:
   - Remove the old WorkspaceRouteCard debug component entirely
   - Import: useNavigate, useLocation from react-router; useQuery, useQueryClient from @tanstack/react-query; all chat components; both hooks; API functions
   - Read workspace state from location (existing pattern)
   - Session management: useSessionManager hook for sidebar data
   - Load messages: useQuery with key ["chat-session", sessionId], calling getChatSession, enabled when sessionId is truthy
   - Derive messages array: `sessionQuery.data?.messages ?? []`
   - Local messages state: `const [localMessages, setLocalMessages] = useState<ChatMessage[]>([])` — reset when sessionQuery.data changes (useEffect that sets localMessages from query data)
   - Sending state: `const [isSending, setIsSending] = useState(false)`
   - SSE streaming: useChatStream(sessionId, onAssistantMessage) where onAssistantMessage appends to localMessages
   - onSend handler:
     1. Set isSending=true
     2. Optimistically append user message to localMessages
     3. Call `sendChatMessage(sessionId, content)` — do NOT await the reply to append it (the SSE "assistant.final" event handles that)
     4. On error, append error message to localMessages
     5. Set isSending=false
     6. Update session title if this is the first message (updateSessionTitle with first 40 chars of content)
   - onNewSession handler:
     1. Call `createChatSession()`
     2. Add to session manager with addSession
     3. Navigate to `/chat/${newSession.session.session_id}`
   - onSelectSession handler: navigate to `/chat/${id}`
   - Layout: `flex h-full` wrapping SessionSidebar on the left and a `flex flex-col flex-1 min-w-0` main area on the right
   - Main area contains: MessageList (flex-1) + MessageInput (at bottom)
   - When no session is selected (sessionId is null), show a centered prompt: "Select a session or start a new chat" with a "New Chat" button styled like the sidebar one
   - MessageInput disabled when isSending is true or sessionId is null
   - IMPORTANT: The shell.tsx section wrapper has `padding: 28px` and `borderRadius: 24px` — the chat UI should fill it. Apply `-m-7 -mb-7` (negative margin to counteract the 28px padding) and `rounded-3xl overflow-hidden` on the outermost chat container, and set a min-height: `min-h-[600px] h-[calc(100vh-320px)]` to make it tall enough for comfortable chatting.
  </action>
  <verify>
    <automated>cd /Users/jinli/Documents/Personal/nanobot_fork/nanobot/tui/web && npx tsc --noEmit 2>&1 | head -30</automated>
  </verify>
  <done>ChatWorkspaceRoute renders a full chat UI: session sidebar on left, message list with bubbles in center, input at bottom. SSE streaming shows progressive assistant text. Session list persists in localStorage. Navigation works via /chat/:sessionId URLs. TypeScript compiles cleanly.</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <what-built>Complete chat UI with Tailwind styling: session sidebar, message bubbles, text input, and SSE streaming. Earth-tone color scheme matching existing shell.</what-built>
  <how-to-verify>
    1. Start the backend: ensure nanobot tui is running on port 18791
    2. Start the frontend: `cd nanobot/tui/web && npm run dev`
    3. Open http://127.0.0.1:4173 in browser
    4. Verify the Chat tab shows the new chat UI (not the old debug cards)
    5. Click "New Chat" — should create a session and navigate to /chat/{sessionId}
    6. Type a message and press Enter — message appears right-aligned in a dark green bubble
    7. Watch the assistant response stream in progressively (left-aligned, light bubble)
    8. The sidebar should show the session with the first message as its title
    9. Verify auto-scroll works when messages exceed viewport
    10. Verify Shift+Enter creates a newline instead of sending
  </how-to-verify>
  <resume-signal>Type "approved" or describe issues to fix</resume-signal>
</task>

</tasks>

<verification>
- `cd nanobot/tui/web && npx tsc --noEmit` passes with zero errors
- `cd nanobot/tui/web && npm run build` produces a clean production build
- All new component files exist under src/features/chat/
- Tailwind classes render correctly (not raw class strings)
- Existing shell.tsx and router.tsx are unmodified
</verification>

<success_criteria>
- Chat UI renders inside the existing workspace shell at /chat route
- User can create sessions, send messages, and see streamed responses
- Session list persists across page refreshes via localStorage
- Earth-tone Tailwind theme matches the existing shell aesthetic
- No TypeScript compilation errors
</success_criteria>

<output>
After completion, create `.planning/quick/260322-ptr-web-chat-ui-mvp/260322-ptr-SUMMARY.md`
</output>
