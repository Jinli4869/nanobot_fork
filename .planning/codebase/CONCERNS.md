# Codebase Concerns

**Analysis Date:** 2026-03-17

## Tech Debt

**Global State in Configuration:**
- Issue: `_current_config_path` global variable in `nanobot/config/loader.py` used for multi-instance support requires careful synchronization
- Files: `nanobot/config/loader.py` (lines 10-23), `nanobot/cli/commands.py` (line 97 for terminal state globals)
- Impact: Multiple concurrent instances or threads may interfere with each other's configuration; thread-safety not guaranteed
- Fix approach: Replace global state with context managers or dependency injection; use thread-local storage if multi-threading needed

**MCP Connection Retry with State Flags:**
- Issue: MCP connection uses multiple state flags (`_mcp_connected`, `_mcp_connecting`) instead of atomic state machine
- Files: `nanobot/agent/loop.py` (lines 136-156)
- Impact: Race condition possible between `_connect_mcp()` calls; connection retry after failure relies on next message arrival
- Fix approach: Use a single enum-based state or asyncio.Lock for atomic transitions; implement explicit retry on startup

**Broad Exception Handling:**
- Issue: Many bare `except Exception:` and `except:` clauses that swallow all errors without logging or recovery strategy
- Files: `nanobot/session/manager.py` (lines 154, 188, 239), `nanobot/cli/commands.py` (multiple), `nanobot/channels/*.py` (many)
- Count: 37+ bare pass statements and broad exception handlers
- Impact: Silent failures hide bugs; production issues become hard to debug; legitimate errors masked
- Fix approach: Replace with specific exception types; add logging context; distinguish between fatal and recoverable errors

**Error Handling in Sub-Agent Manager:**
- Issue: `SubagentManager` in `nanobot/agent/loop.py` spawned as background tasks without guaranteed cleanup
- Files: `nanobot/agent/subagent.py`, `nanobot/agent/loop.py` (lines 86-95, 277-279)
- Impact: Sub-agent tasks may continue running after parent terminates; resource leaks possible
- Fix approach: Ensure all sub-agents tracked and properly cancelled in shutdown; use task groups

## Known Bugs

**Truncation Edge Case in Tool Results:**
- Symptoms: Large tool command output (>16K chars) gets truncated with head+tail approach, potentially losing critical middle context
- Files: `nanobot/agent/loop.py` (lines 49, 129-137)
- Trigger: Any shell command, file read, or web_fetch returning >10K chars
- Workaround: Split command output with secondary tool calls; use `tail` within shell instead of client-side truncation
- Fix approach: Implement sliding window context preservation or compression before truncation

**Tool Call Argument Parsing Fragility:**
- Symptoms: Tool arguments arrive as either dict, list, or JSON string depending on provider; normalization assumes list[0] is dict
- Files: `nanobot/agent/memory.py` (lines 53-59), `nanobot/agent/tools/base.py`
- Trigger: Some providers (e.g., DeepSeek) return `[[{args}]]` instead of `{args}`
- Workaround: Most providers return dict directly; edge case rare in practice
- Fix approach: Add comprehensive provider-specific argument normalization; add type validation and logging

**Session History Tool-Call Boundary Bug (Fixed but fragile):**
- Symptoms: Session truncation can orphan tool results from their matching assistant messages
- Files: `nanobot/session/manager.py` (lines 47-67 `_find_legal_start()`)
- Trigger: When max_messages window truncates mid-tool-exchange
- Fix in place: `_find_legal_start()` validates boundaries, but logic is complex and hard to test
- Risk: Future refactors may reintroduce this; existing fix is defensive rather than proactive

## Security Considerations

**Shell Command Injection Protection (Moderate Risk):**
- Risk: `ExecTool` guards against destructive commands but pattern matching is regex-based and potentially bypassable
- Files: `nanobot/agent/tools/shell.py` (lines 26-36, 144-176)
- Current mitigation: Blocklist of dangerous patterns (rm -r, dd, format, etc.); allowlist support; path traversal guard
- Recommendations:
  - Add integration test suite with attempted bypasses
  - Document limitations of regex guards in help text
  - Consider stricter default: deny-by-default with explicit allow patterns
  - Use shlex for better argument parsing before pattern matching

**File System Boundary Check (Low-to-Moderate Risk):**
- Risk: `restrict_to_workspace` path traversal detection relies on Path resolution; symlinks could bypass checks
- Files: `nanobot/agent/tools/shell.py` (lines 161-174), `nanobot/agent/tools/filesystem.py`
- Current mitigation: Checks for `../` and `..\` patterns; uses `Path.resolve()` for absolute paths
- Recommendations:
  - Resolve symlinks explicitly with `Path.resolve(strict=True)`
  - Document that workspace boundary is not cryptographic-strength isolation
  - Add tests for symlink bypass attempts
  - Log all path access outside workspace (currently may be silent)

**Web Fetch Content Untrusted (Design Constraint):**
- Risk: `web_fetch` returns untrusted external data directly to LLM for interpretation
- Files: `nanobot/agent/tools/web.py`, `nanobot/agent/context.py` (line 96 warning)
- Current mitigation: System prompt warns agent not to follow instructions from fetched content
- Recommendations:
  - Add rate limiting to prevent data exfiltration attacks
  - Log all fetches for audit trail
  - Consider content size limits (currently unbounded except truncation)
  - Add option to sanitize HTML/remove scripts before passing to LLM

**Secrets in Session History:**
- Risk: User may paste secrets or API keys in conversation; stored in `session.messages` in plaintext
- Files: `nanobot/session/manager.py`, `nanobot/agent/loop.py` (message storage)
- Current mitigation: None
- Recommendations:
  - Add secret detection (regex for common patterns: sk-, AKIA, etc.)
  - Scrub detected secrets before storage with placeholder
  - Document this limitation in README
  - Consider optional encryption of session files

## Performance Bottlenecks

**Memory Consolidation on Hot Path:**
- Problem: `MemoryConsolidator` called after every message even if no consolidation needed; full memory file read/write on each consolidation
- Files: `nanobot/agent/loop.py` (lines 414, 446), `nanobot/agent/memory.py`
- Cause: Background consolidation still reads entire MEMORY.md file; no incremental updates
- Current state: Background task mitigates but first message in session still waits for lock
- Improvement path:
  - Add consolidation threshold (only consolidate after N messages or M tokens)
  - Implement append-only history updates without rewriting entire memory file
  - Cache long-term memory in memory until consolidation

**Context Window Exhaustion with Large Memory:**
- Problem: Every message includes full MEMORY.md content + HISTORY.md search results; no cost tracking
- Files: `nanobot/agent/context.py` (lines 27-54), `nanobot/agent/memory.py` (line 100)
- Cause: Linear growth of memory context; no automatic pruning
- Impact: Frequent token limit errors in long-running sessions
- Improvement path:
  - Add memory size budget to context builder
  - Implement LRU or relevance-based memory pruning
  - Add token counting for memory section before sending to LLM

**Large File Operations Without Streaming:**
- Problem: `ReadFileTool` loads entire files into memory; no streaming for large files
- Files: `nanobot/agent/tools/filesystem.py`, `nanobot/agent/loop.py` (line 49 truncation)
- Impact: Large log files, databases, or binary files cause memory spikes and truncation
- Improvement path:
  - Add file size check before reading
  - Implement tail/head extraction for large files
  - Use streaming or chunked reading for files >1MB

**Session Loading Performance:**
- Problem: All sessions in workspace loaded into memory; no lazy loading or pagination
- Files: `nanobot/session/manager.py`
- Impact: Workspace with 1000+ sessions becomes sluggish on startup
- Improvement path:
  - Implement directory listing only; load session on demand
  - Add LRU cache for frequently accessed sessions
  - Consider SQLite instead of JSON files for indexed lookups

## Fragile Areas

**MCP Server Connection Lifecycle:**
- Files: `nanobot/agent/loop.py` (lines 136-156), `nanobot/agent/tools/mcp.py`
- Why fragile:
  - Lazy connection on first message; no validation on startup
  - Reconnection logic triggers only on next message after failure
  - `AsyncExitStack` cleanup catches but silences exceptions
  - No timeout on connection attempts
- Safe modification:
  - Add explicit connection validation in startup
  - Implement exponential backoff with max retries
  - Add explicit timeout to `_connect_mcp()`
  - Log all MCP errors, not just warnings
- Test coverage: No tests visible for MCP failure scenarios

**Channel WebSocket Connections:**
- Files: `nanobot/channels/feishu.py`, `nanobot/channels/slack.py`, `nanobot/channels/telegram.py`
- Why fragile:
  - Long-lived WebSocket connections without explicit heartbeat/keepalive
  - Reconnection logic implicit in SDK (e.g., `feishu.py` line 940 `nonlocal first_send`)
  - No explicit connection state tracking; implicit state in SDK
  - Error callbacks swallow some exceptions
- Safe modification:
  - Add explicit connection state machine per channel
  - Implement heartbeat for channels that support it
  - Add metrics/logging for connection state changes
  - Document expected behavior when connection drops
- Test coverage: No integration tests for network failures

**Tool Execution Timeout Handling:**
- Files: `nanobot/agent/tools/shell.py` (lines 102-113), `nanobot/agent/tools/web.py`
- Why fragile:
  - Process killed but not guaranteed to be reaped (sleep-and-ignore in line 112)
  - Tool timeout max cap of 600s may be insufficient for compilation/large downloads
  - Timeout errors don't distinguish timeout from exit code errors
- Safe modification:
  - Use process.wait() with timeout instead of bare kill()
  - Add returncode validation after kill
  - Consider separate timeout categories (network vs computation)
  - Log timeout details (which tool, what command, how long)

**JSON Parsing in Context Building:**
- Files: `nanobot/agent/context.py`, `nanobot/channels/feishu.py` (lines 59-62)
- Why fragile:
  - Generic `json.JSONDecodeError` catch with silent fallback
  - Interactive content extraction assumes nested dict structure (lines 76-82)
  - No validation of parsed message structure
- Safe modification:
  - Add specific validation after parsing
  - Log JSON parse failures with context (URL, source, content preview)
  - Use stricter schema validation instead of duck typing
- Test coverage: No tests for malformed message formats

## Scaling Limits

**Session File Format (JSONL):**
- Current capacity: Single session with 10K+ messages becomes slow to load/parse
- Limit: Each message JSON serialization adds overhead; no indexing
- Scaling path:
  - Migrate to SQLite with indexed queries
  - Implement message pagination
  - Archive old sessions to separate storage

**Provider Retry Queue:**
- Current capacity: Sequential retry with fixed delays (1s, 2s, 4s)
- Limit: Under high load with rate limiting, single retry sequence blocks all other messages
- Scaling path:
  - Use priority queue for retries instead of sequential
  - Implement exponential backoff with jitter
  - Add circuit breaker per provider

**Tool Registry Single Instance:**
- Current capacity: All tools in single registry; no per-session or per-workspace tooling
- Limit: Custom tools must be registered globally; no tool isolation
- Scaling path:
  - Implement tool scoping (global, workspace, session-level)
  - Add tool resource limits (max concurrent executions per tool)

## Dependencies at Risk

**Pydantic 2.x Breaking Changes:**
- Risk: Dependency pinned to `pydantic>=2.12.0,<3.0.0`; major version jump possible
- Impact: Model validation, JSON serialization behavior could change
- Migration plan:
  - Add compatibility layer for Pydantic 3 validator syntax
  - Test with `pydantic>=3.0.0` in dev periodically

**litellm 2.x Gateway:**
- Risk: Heavy dependency on litellm for provider abstraction; major version possible
- Impact: Provider configuration, model listing, retry logic could change
- Migration plan:
  - Add abstraction layer over litellm calls in `nanobot/providers/base.py`
  - Test with litellm 2.x periodically
  - Document fallback for critical providers if litellm breaks

**Deprecated DingTalk Channel:**
- Risk: `dingtalk-stream` SDK pinned to `<1.0.0`; maintainability unclear
- Impact: Breaking API changes possible in minor versions
- Migration plan:
  - Monitor dingtalk-stream releases for security fixes
  - Consider extracting channel as optional plugin
  - Test dingtalk integration in CI

**Python 3.11 Support EOL:**
- Risk: `requires-python = ">=3.11"` will be EOL in October 2026
- Impact: Security patches may stop; async/typing improvements unavailable
- Scaling path:
  - Update to `requires-python = ">=3.12"` in 2026
  - Use async/typing improvements (PEP 701, etc.)
  - Drop 3.11 support in next major release

## Missing Critical Features

**Connection Health Monitoring:**
- Problem: No metrics for channel connection uptime, message latency, or error rates
- Blocks: Can't detect if bot is alive/responsive without manual checks
- Implementation: Add Prometheus-style metrics or simple JSON endpoint

**Graceful Degradation:**
- Problem: If MCP fails, tools fail silently; no fallback or warning to user
- Blocks: Users unaware bot capabilities reduced
- Implementation: Add capability detection and fallback messaging

**Transaction-Like Semantics for Tool Chains:**
- Problem: Multi-step tool operations (e.g., read-modify-write) not atomic; failure mid-chain leaves inconsistent state
- Blocks: Complex tasks cannot reliably modify multiple files
- Implementation: Add session transactions or explicit rollback support

**Structured Logging:**
- Problem: loguru logs to file/console but no structured (JSON) output option
- Blocks: Log aggregation and analysis difficult in production
- Implementation: Add JSON formatter option to loguru config

## Test Coverage Gaps

**Shell Command Injection Prevention:**
- What's not tested: Bypass attempts for regex guards (e.g., `rm -r` variants, obfuscation)
- Files: `nanobot/agent/tools/shell.py`
- Risk: False sense of security; undiscovered bypass exploitable
- Priority: High

**MCP Connection Failures:**
- What's not tested: MCP server unreachable, timeout, invalid response, concurrent connection attempts
- Files: `nanobot/agent/tools/mcp.py`, `nanobot/agent/loop.py`
- Risk: Unclear behavior in degraded network conditions
- Priority: High

**Session History Boundary Cases:**
- What's not tested: Truncation with orphaned tool results, mixed tool-call and non-tool messages, rapid session creation
- Files: `nanobot/session/manager.py`
- Risk: Regressions in `_find_legal_start()` logic
- Priority: Medium

**Memory Consolidation Edge Cases:**
- What's not tested: Very large session histories, concurrent consolidation attempts, out-of-disk errors
- Files: `nanobot/agent/memory.py`
- Risk: Data loss or corruption if consolidation fails
- Priority: Medium

**Provider Timeout/Retry Behavior:**
- What's not tested: Network timeouts, partial responses, retry exhaustion
- Files: `nanobot/providers/base.py`, `nanobot/providers/*.py`
- Risk: Unclear failure modes; possible infinite loops or silent drops
- Priority: Medium

**File System Permission Errors:**
- What's not tested: Read-only workspace, full disk, permission denied, symlink loops
- Files: `nanobot/agent/tools/filesystem.py`
- Risk: Unclear error messages; possible data loss
- Priority: Low

**Concurrent Session Access:**
- What's not tested: Multiple agent instances accessing same session, race conditions in session.save()
- Files: `nanobot/session/manager.py`, `nanobot/agent/loop.py`
- Risk: Session corruption if multiple writers
- Priority: Low (mitigated by processing lock but not tested)

---

*Concerns audit: 2026-03-17*
