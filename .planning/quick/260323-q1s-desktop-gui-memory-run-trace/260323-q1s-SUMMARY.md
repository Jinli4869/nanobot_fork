# Quick Task 260323-q1s Summary

## Goal

为 desktop/local backend 设计一条真实 GUI 任务的端到端 memory 命中验证方案，并明确执行后应该检查哪份 run trace、看哪些字段来判断 memory 是否真的被检索与使用。

## Final Recommended Task

主测试任务固定为：

`切换回浏览器，并重新打开刚刚关闭的标签页。`

这是本次设计里最优的 desktop 场景，因为它在一次 run 中同时触发两类 memory：
- macOS OS memory：切换应用
- browser app memory：恢复刚关闭的标签页

## Manual Precondition

执行前建议先人工准备：
- 当前前台不是浏览器，而是别的 macOS 应用
- 浏览器里刚刚关闭过一个标签页，确保“恢复标签页”有真实目标
- 使用真实桌面，不使用 `adb`、`--dry-run`、`--background`

## Recommended Command

```bash
python -m opengui.cli --backend local --task "切换回浏览器，并重新打开刚刚关闭的标签页。"
```

如果本地 `~/.opengui/config.yaml` 没有可用 embedding provider，这次测试即使运行成功，也不能证明 memory 检索链路成立，因为 `MemoryRetriever` 不会被构建。

## Which Run Trace To Inspect

执行后，优先查看最新 run 根目录：

- `opengui_runs/<run_stamp>/`

重点看两份 trace：

1. trajectory trace
- `opengui_runs/<run_stamp>/trace_<timestamp>.jsonl`

2. attempt trace
- `opengui_runs/<run_stamp>/<task_slug>_<epoch_ms>_0/trace.jsonl`

如果第一次 attempt 失败，再看 `_1`、`_2`；但 memory 检索主证据优先来自 run 根目录的 trajectory trace。

## What To Look For

### In trajectory trace

搜索：

```text
"type": "memory_retrieval"
```

关键字段：
- `hit_count`
- `hits[].entry_id`
- `hits[].memory_type`
- `hits[].platform`
- `hits[].app`
- `hits[].score`
- `context`

理想通过标准：
- `hit_count >= 2`
- 命中 `os-guide-macos-shortcuts`
- 命中 `app-guide-browser-hotkeys`
- `context` 非空

### In attempt trace

按顺序看：
- `attempt_start`
- `step`
- `attempt_result`

理想模式：
- 先尝试应用切换类热键
- 再尝试浏览器恢复标签页热键

即使最终执行没完全成功，只要 trajectory trace 已经同时命中 OS + browser memory，也可以判定“memory 检索与注入链路成立”，只是执行链路另算。

## Deliverable

本 quick task 产出的是测试设计文档，不改 runtime 行为。

相关文件：
- `260323-q1s-PLAN.md`
- `260323-q1s-SUMMARY.md`
