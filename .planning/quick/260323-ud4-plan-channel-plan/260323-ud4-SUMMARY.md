# Quick Task 260323-ud4 Summary

**Description:** 在执行 plan 之后向当前 channel 发送 plan 预览消息，并补测试与提交。  
**Date:** 2026-03-23  
**Status:** completed

## Result

现在只要任务进入 planning 分支，`AgentLoop` 在执行 router 之前就会先向当前 channel 发送一条 plan 预览消息。

## Implementation

改动位于 [`loop.py`](/Users/jinli/Documents/Personal/nanobot_fork/nanobot/agent/loop.py)：

- 为 `_plan_and_execute()` 增加了：
  - `channel`
  - `chat_id`
  - `metadata`
- 在 planner 返回 `tree` 后，调用 bus 发送一条 `_plan_preview` 进度消息
- 消息内容使用 `_format_plan_tree()` 渲染，并包装成用户可见的预览文本：

```text
执行计划预览：
```text
...
```
```

同时在 `_process_message()` 中，把当前消息的 channel/chat_id/metadata 传入 `_plan_and_execute()`，这样这条预览会发到和原消息相同的 channel。

## Test Coverage

更新测试：

- `tests/test_opengui_p8_planning.py`
  - 现在会断言 `_plan_and_execute()` 触发了一次 `bus.publish_outbound()`
  - 并检查：
    - channel / chat_id 正确
    - metadata 含 `_progress=True`
    - metadata 含 `_plan_preview=True`
    - 内容包含格式化后的 plan tree

验证结果：

```bash
uv run pytest tests/test_opengui_p8_planning.py tests/test_opengui_agent_loop.py -q
uv run python -m py_compile nanobot/agent/loop.py tests/test_opengui_p8_planning.py
```

结果：

- `37 passed`
- `py_compile` 成功

## Outcome

TUI / channel 用户现在可以在计划执行前先看到一条 plan 预览，便于理解 agent 将如何分解并执行复杂任务。
