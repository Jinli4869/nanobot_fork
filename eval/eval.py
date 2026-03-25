import argparse
import csv
import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any
from openai import OpenAI
import json_repair



DEFAULT_JUDGE_MODEL = "qwen3-vl-plus"
DEFAULT_API_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


@dataclass
class TaskSpec:
    task_id: str
    instruction: str
    instruction_ch: str


def load_tasks(csv_path: Path) -> list[TaskSpec]:
    tasks: list[TaskSpec] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            task_id = (row.get("task_id") or "").strip()
            if not task_id:
                continue
            instruction = (row.get("instruction") or "").strip()
            instruction_ch = (row.get("instruction_ch") or "").strip()
            tasks.append(TaskSpec(task_id=task_id, instruction=instruction, instruction_ch=instruction_ch))
    return tasks


def find_task_traj_path(traj_root: Path, task_id: str) -> Path | None:
    """
    支持两种常见布局（路径名完全由你自定）：
    - {traj_root}/{task_id}/traj.jsonl
    - {traj_root}/{task_id}/{子目录}/traj.jsonl

    当存在多个子目录时，选取 `traj.jsonl` 最近修改的那一个。
    """
    task_root = traj_root / task_id
    direct = task_root / "traj.jsonl"
    if direct.exists():
        return direct

    candidates: list[Path] = []
    for d in task_root.iterdir() if task_root.exists() else []:
        if d.is_dir():
            p = d / "traj.jsonl"
            if p.exists():
                candidates.append(p)
    if not candidates:
        return None

    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def load_traj_rows(traj_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with traj_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # 某些行可能是脏数据；跳过避免 judge 失败
                continue
    return rows


def load_screenshots_for_judge(
    traj_path: Path,
    traj_rows: list[dict[str, Any]],
) -> list[bytes]:
    """
    从 traj_rows 里读取每步的 screenshot_file，并把对应 png 文件读成 bytes。
    screenshot_file 是 hf_run.py 写入 traj.jsonl 时使用的相对文件名。
    """
    screenshot_bytes: list[bytes] = []
    screenshot_dir = traj_path.parent

    for row in traj_rows:
        screenshot_file = row.get("screenshot_file")
        if not screenshot_file:
            continue
        ss_path = screenshot_dir / str(screenshot_file)
        if not ss_path.exists():
            continue
        try:
            screenshot_bytes.append(ss_path.read_bytes())
        except Exception:
            continue

    return screenshot_bytes


def _extract_json_obj(text: str) -> str:
    # 尽量从 LLM 输出里定位 JSON 对象，避免被前后解释污染。
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return text
    return text[start : end + 1]


def judge_success(
    client: OpenAI,
    task: TaskSpec,
    traj_rows: list[dict[str, Any]],
    screenshots: list[bytes],
    model: str,
) -> tuple[bool, str]:
    instruction_text = task.instruction_ch or task.instruction

    trajectory_excerpt: list[dict[str, Any]] = []
    for row in traj_rows:
        trajectory_excerpt.append(
            {
                "step_num": row.get("step_num"),
                "action": row.get("action"),
                "response": row.get("response"),
                "done": row.get("done"),
                "info": row.get("info"),
            }
        )

    system_prompt = """
You are an expert evaluator for a mobile GUI agent task.

You will be given:
1) the user's original instruction,
2) the agent's execution trace (actions/response/done/info),
3) a final sequence of screenshots (PNG images).

Your job is to judge whether the task has been successfully completed.

【Evaluation rules】
1. "success" means the final task goal is achieved, not whether intermediate actions exist.
2. Screenshots are important evidence. If screenshot evidence is insufficient, judge failure.
3. "actions" are only supporting evidence; you must not label success based on actions alone.
4. You may accept semantically equivalent actions as correct, but evidence must still support success.
5. If the provided evidence does not clearly support achievement, judge as not completed.

【Output requirement】
Return ONLY strict JSON (no Markdown, no extra text) in exactly this schema:
{"success": true/false, "reason": "one short sentence explaining the key evidence"}
""".strip()

    user_prompt_text = "【Input】\n"
    user_prompt_text += f"task_id:\n{task.task_id}\n\n"
    user_prompt_text += "instruction:\n" + instruction_text + "\n\n"
    user_prompt_text += "actions_in_time_order:\n" + str(trajectory_excerpt) + "\n\n"
    user_prompt_text += "success_state (final goal):\n" + instruction_text + "\n"
    user_prompt_text += "\nJudge success based on trace evidence and screenshots."

    user_content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt_text}]
    for ss in screenshots:
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{base64.b64encode(ss).decode('utf-8')}"},
            }
        )

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
    )

    content = (resp.choices[0].message.content or "").strip()
    if not content:
        return False, "empty_judge_output"

    content_json = _extract_json_obj(content)

    try:
        obj = json.loads(content_json)
    except json.JSONDecodeError:
        if json_repair is not None:
            try:
                obj = json_repair.loads(content_json)
            except Exception:
                return False, f"judge_parse_error: {content[:200]}"
        else:
            return False, f"judge_parse_error: {content[:200]}"

    success = bool(obj.get("success", False))
    reason = str(obj.get("reason", "")).strip()
    return success, reason


def p90(values: list[int | float]) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    idx = int(0.9 * (len(xs) - 1))
    return float(xs[idx])


def compute_step_stats(steps: list[int]) -> dict[str, Any]:
    if not steps:
        return {"count": 0}
    return {
        "count": len(steps),
        "min": int(min(steps)),
        "max": int(max(steps)),
        "mean": float(mean(steps)),
        "median": float(median(steps)),
        "p90": p90(steps),
    }


def run_eval(
    dataset_csv: Path,
    traj_root: Path,
    output_dir: Path,
    model: str,
    api_key: str,
    api_base: str | None,
    max_samples: int | None,
) -> None:
    tasks = load_tasks(dataset_csv)
    if max_samples is not None:
        tasks = tasks[:max_samples]

    if not api_key:
        raise SystemExit("Missing api-key (or OPENAI_API_KEY).")

    client = OpenAI(api_key=api_key, base_url=api_base) if api_base else OpenAI(api_key=api_key)

    records: list[dict[str, Any]] = []

    for task in tasks:
        instruction_text = task.instruction_ch or task.instruction
        traj_path = find_task_traj_path(traj_root, task.task_id)

        if traj_path is None:
            records.append(
                {
                    "task_id": task.task_id,
                    "instruction": instruction_text,
                    "traj_path": None,
                    "success": False,
                    "reason": "no_traj.jsonl_found",
                    "steps": 0,
                }
            )
            continue

        traj_rows = load_traj_rows(traj_path)
        steps = len(traj_rows)
        screenshots = load_screenshots_for_judge(traj_path, traj_rows)

        success, reason = judge_success(
            client=client,
            task=task,
            traj_rows=traj_rows,
            screenshots=screenshots,
            model=model,
        )

        records.append(
            {
                "task_id": task.task_id,
                "instruction": instruction_text,
                "traj_path": str(traj_path),
                "success": success,
                "reason": reason,
                "steps": steps,
            }
        )

    # 汇总指标：success_rate = success=true 的数量 / 总条数
    total = len(records)
    success_count = sum(1 for r in records if r.get("success") is True)
    success_rate = success_count / total if total else 0.0

    all_steps = [int(r.get("steps") or 0) for r in records]
    success_steps = [int(r.get("steps") or 0) for r in records if r.get("success") is True]
    fail_steps = [
        int(r.get("steps") or 0)
        for r in records
        if r.get("success") is False
    ]

    summary = {
        "dataset_csv": str(dataset_csv),
        "traj_root": str(traj_root),
        "judge_model": model,
        "total_tasks": total,
        "success_count": success_count,
        "success_rate": success_rate,
        "steps_stats_all": compute_step_stats(all_steps),
        "steps_stats_success": compute_step_stats(success_steps),
        "steps_stats_fail": compute_step_stats(fail_steps),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    per_task_path = output_dir / "per_task_results.jsonl"
    summary_path = output_dir / "summary.json"

    with per_task_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"[ClawBench Eval] total={total}, success_rate={success_rate:.4f}, "
        f"per_task={per_task_path}, summary={summary_path}"
    )


def _repo_relative_default_dataset() -> Path:
    # 以本文件所在目录为基准定位 datasets
    here = Path(__file__).resolve().parent
    return here / "datasets" / "ClawBench.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ClawBench eval on existing traj.jsonl (prompt + trajectory judge).")
    parser.add_argument("--dataset-csv", type=Path, default=_repo_relative_default_dataset(), help="ClawBench CSV file.")
    parser.add_argument(
        "--traj-root",
        type=Path,
        required=True,
        help="轨迹根目录（{traj-root}/{task_id}/traj.jsonl 或 {traj-root}/{task_id}/{subdir}/traj.jsonl）",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("eval/results/clawbench"),
        help="输出目录：会写 per_task_results.jsonl 与 summary.json",
    )
    parser.add_argument("--max-samples", type=int, default=None, help="最多评测多少条（调试用）。默认全部。")

    parser.add_argument("--judge-model", type=str, default=DEFAULT_JUDGE_MODEL, help="用于判定 success 的模型名。")

    parser.add_argument("--api-key", type=str, default=os.getenv("OPENAI_API_KEY", ""), help="LLM judge API Key。")
    parser.add_argument(
        "--api-base",
        type=str,
        default=os.getenv("OPENAI_BASE_URL") or DEFAULT_API_BASE,
        help="OpenAI-compatible base_url（兼容 dashscope）。默认从 OPENAI_BASE_URL 或使用 dashscope 兼容地址。",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_eval(
        dataset_csv=args.dataset_csv,
        traj_root=args.traj_root,
        output_dir=args.output_dir,
        model=args.judge_model,
        api_key=args.api_key,
        api_base=args.api_base,
        max_samples=args.max_samples,
    )
