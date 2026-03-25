## nano_fork / eval（ClawBench）

`eval.py` 用于对基于 `traj.jsonl` 的评测结果做两项指标统计：

1. **效率（steps）**：每条任务的 `steps = traj.jsonl` 行数（从 `traj.jsonl` 读取到的 step 记录数）。
2. **成功率（success_rate）**：每条任务由 LLM judge 输出 `success=true/false`，最终汇总 `success_rate = success=true 的数量 / 总任务数`。

评测不需要中间状态（`intermediate_checks` 等），仅使用每一步的 `traj.jsonl` 证据（`action/response/done/info`）与每步对应的截图（`screenshot_file` 指向的 png）。

---

## 运行方式

```bash
python3 eval.py \
  --traj-root "/你的traj根目录" \
  --output-dir "results/clawbench_run" \
  --api-key "$OPENAI_API_KEY" \
  --judge-model "qwen3-vl-plus"
```

可选参数：

```bash
--dataset-csv  # 默认为 eval/datasets/ClawBench.csv
--api-base     # 默认为环境变量 OPENAI_BASE_URL 或使用 dashscope 兼容地址
--max-samples  # 默认为全部；调试用
```

---

## `--traj-root` 的目录约定

`eval.py` 会按 `task_id` 在 `--traj-root` 下找 `traj.jsonl`，支持两种布局：

1. `{traj-root}/{task_id}/traj.jsonl`
2. `{traj-root}/{task_id}/{subdir}/traj.jsonl`（当存在多个子目录时，取 `traj.jsonl` 最近修改时间最新的那个）

此外，`traj.jsonl` 的每条 step 中应包含 `screenshot_file`，该字段表示截图文件名（相对路径，通常就在 `traj.jsonl` 同目录下）。

---

## 输出文件

输出目录（`--output-dir`）下会生成：

- `per_task_results.jsonl`
  - 每条任务一行 JSON，包含：
    - `task_id`
    - `instruction`
    - `traj_path`（本次评测实际读取的 traj.jsonl 路径）
    - `success`（LLM judge 输出）
    - `reason`（LLM judge 输出）
    - `steps`（效率指标）
- `summary.json`
  - 数据集级统计：
    - `total_tasks`
    - `success_rate`
    - `steps_stats_all / steps_stats_success / steps_stats_fail`

