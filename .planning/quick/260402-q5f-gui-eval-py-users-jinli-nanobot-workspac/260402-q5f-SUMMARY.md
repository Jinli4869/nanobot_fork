# Quick Task 260402-q5f Summary

## Goal

修复 GUI 执行与评估里的两个行为问题：

1. GUI 动作完成后，等动作执行链路真正返回并经过短暂 settle，再抓取下一张截图。
2. GUI 评估中的步数统计只计算 `type == "step"` 的轨迹事件。

## What Changed

- 在 `opengui/agent.py` 中为非终止动作加入固定的 post-action settle 延迟；`_run_step()` 现在按 `execute -> settle -> observe` 顺序推进。
- `wait`、`done`、`request_intervention` 不会额外插入 settle 延迟，避免重复等待或影响终止/人工接管语义。
- 在 `nanobot/utils/gui_evaluation.py` 中新增 `filter_step_rows()`，并让 `evaluate_gui_trajectory_sync()` 只基于 `type == "step"` 的轨迹事件：
  - 传给 judge 的轨迹片段只包含 step
  - 送去 judge 的截图也只读取 step 对应截图
  - `steps` 字段只统计 step 事件数量
- `eval/eval.py` 已通过共享的 `evaluate_gui_trajectory_sync()` 自动继承同一条 step-only 计数规则，无需再维护另一套统计口径。

## Verification

- `uv run pytest tests/test_opengui.py -q -k settle_before_observing`
- `uv run pytest tests/test_opengui_p8_trajectory.py -q -k "counts_only_step_rows or uses_step_only_counts"`
- `uv run pytest tests/test_opengui.py tests/test_opengui_p8_trajectory.py -q`
- 实际 trace 校验：
  - `rg -c '"type"\\s*:\\s*"step"' /Users/jinli/.nanobot/workspace/gui_runs/2026-04-02_184228_600485/trace_20260402_184228.jsonl`
  - 结果为 `2`，与修复后的 step-only 统计口径一致

## Commits

- `1ac5e43` `fix(gui): settle screenshots and count step events only`
