# eval/batch — Pass@k Before vs After Skill Extraction

Runs N tasks × K trials in two phases:

1. **phase_a (cold)** — empty skill library, no skill execution.
2. **skills extracted** — Phase A's *successful* traces are fed through `SkillExtractor` → `SkillLibrary.add_or_merge`.
3. **phase_b (warm)** — `enable_skill_execution=True` + reuser; same N × K.

Each phase produces:

- `runs.jsonl` — one line per `(task_id, trial_index)`
- `summary.json` — pass@1, pass@K, avg steps / tokens / latency / TTFT / skill_hit_rate

A `report.md` at the root compares the two phases.

## Metrics captured

Parsed from `trace_*.jsonl` (no extra LLM call):

| metric | source |
|---|---|
| `success` | `opengui.evaluation.evaluate_gui_trajectory_sync` (vision LLM judge, cached) |
| `steps` | count of `step` events |
| `prompt/completion/total_tokens` | sum across `step` / `subgoal_step` / `skill_step` |
| `avg_step_duration_s` | mean `step.duration_s` (wall-clock per step) |
| `avg_chat_latency_s` | mean `step.chat_latency_s` (LLM call wall-clock) |
| `avg_ttft_s` | mean `step.ttft_s` (time-to-first-token; populated only when `gui.capture_ttft=true`) |
| `skill_hit` | any `skill_search` event with `matched=true` |
| `skill_executed_success` | any `skill_execution_result` with `state="succeeded"` |

## Usage

```bash
uv run python -m eval.batch \
    --config ~/.nanobot/config.json \
    --dataset eval/datasets/batch_demo.csv \
    --trials 3 \
    --output-dir eval/results/batch/$(date -u +%Y%m%d_%H%M%S) \
    --max-tasks 20
```

Flags:

| flag | default | meaning |
|---|---|---|
| `--config` | `~/.nanobot/config.json` | Nanobot config (must contain `gui` section) |
| `--dataset` | required | CSV with columns `task_id, instruction, instruction_ch` |
| `--trials` | `3` | K — number of trials per task (drives pass@K) |
| `--max-tasks` | all | Limit dataset size |
| `--phase` | `both` | `a-only` / `b-only` / `both` |
| `--judge-model` | `qwen3-vl-plus` | Vision LLM for success judging |
| `--judge-api-key` | `$OPENAI_API_KEY` | judge auth |
| `--judge-api-base` | dashscope compat | judge endpoint |

## Enabling TTFT capture

TTFT is opt-in (streaming overhead). Add to your config:

```json
{ "gui": { "capture_ttft": true } }
```

When enabled, the main agent's per-step LLM call is routed through `chat_stream_with_retry` and the first content delta timestamp is recorded as `ttft_s`. Validator/grounder/reuser calls remain non-streaming.

## Output layout

```
<output-dir>/
  phase_a/
    runs.jsonl
    summary.json
  skills_extracted.json
  phase_b/
    runs.jsonl
    summary.json
  report.md
```

Per-trace judge results are cached as `<trace_stem>.judge.json` next to the trace, so repeated aggregation is free.
