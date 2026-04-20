"""CLI entry point for batch eval harness.

Usage:
    uv run python -m eval.batch \\
        --config ~/.nanobot/config.json \\
        --dataset eval/datasets/batch_demo.csv \\
        --trials 3 \\
        --output-dir eval/results/batch/<ts>
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

from eval.batch.runner import run_batch


def _build_provider_and_model(config) -> tuple[object, str]:
    """Reuse nanobot's runtime provider builder for parity with the CLI."""
    from nanobot.cli.commands import _make_provider

    model = config.gui.model or config.agents.defaults.model
    provider = _make_provider(
        config,
        model_override=model,
        provider_override=config.gui.provider,
    )
    return provider, model


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="eval.batch")
    p.add_argument("--config", type=Path, default=None, help="Path to nanobot config.json")
    p.add_argument("--dataset", type=Path, required=True, help="Tasks CSV (task_id,instruction,instruction_ch)")
    p.add_argument("--output-dir", type=Path, default=None, help="Output directory; default eval/results/batch/<ts>")
    p.add_argument("--trials", type=int, default=3)
    p.add_argument("--max-tasks", type=int, default=None)
    p.add_argument("--phase", choices=["a-only", "b-only", "both"], default="both")
    p.add_argument("--workspace", type=Path, default=Path.cwd())
    p.add_argument("--judge-model", type=str, default=None)
    p.add_argument("--judge-api-key", type=str, default=os.getenv("OPENAI_API_KEY"))
    p.add_argument("--judge-api-base", type=str, default=os.getenv("OPENAI_BASE_URL"))
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s | %(message)s")

    from nanobot.config.loader import load_config

    config = load_config(args.config)
    if config.gui is None:
        raise SystemExit("config.gui section is required for batch eval")

    provider, model = _build_provider_and_model(config)

    output_dir = args.output_dir or (
        Path("eval/results/batch") / datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    )

    out = asyncio.run(
        run_batch(
            dataset_csv=args.dataset,
            output_dir=output_dir,
            config=config,
            provider=provider,
            model=model,
            workspace=args.workspace,
            trials=args.trials,
            max_tasks=args.max_tasks,
            phase=args.phase,
            judge_model=args.judge_model,
            judge_api_key=args.judge_api_key,
            judge_api_base=args.judge_api_base,
        )
    )
    print(f"[batch] done. results in {out}")


if __name__ == "__main__":
    main()
