"""Prepare manual plans after the first one using the existing proven pipeline."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def ratio_text(ratios: dict[str, float]) -> str:
    return ":".join(f"{key}={value}" for key, value in ratios.items())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plans-json", required=True)
    parser.add_argument("--prepare-script", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--tokenizer", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--file-pattern", default="*.parquet")
    parser.add_argument("--data-ratio", required=True)
    parser.add_argument("--num-scaling-params", required=True)
    parser.add_argument("--data-multiplier", required=True)
    parser.add_argument("--shard-size", required=True)
    parser.add_argument("--val-ratio", required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--max-shards", required=True)
    parser.add_argument("--num-npu", required=True)
    args = parser.parse_args()
    plans = json.loads(args.plans_json)
    output = Path(args.output)
    manifest = []
    for index, plan in enumerate(plans):
        plan_id = plan["id"]
        if index == 0:
            plan_dir = output / "manual_ratio_data"
            stats_path = output / "dataset_stats.json"
        else:
            temporary = output / f".prepare_{plan_id}"
            if temporary.exists():
                shutil.rmtree(temporary)
            command = [
                sys.executable, args.prepare_script,
                "--preprocessed-data-dir", args.source,
                "--output-dir", str(temporary),
                "--tokenizer-pkl", args.tokenizer,
                "--schema", args.schema,
                "--file-pattern", args.file_pattern,
                "--manual-ratio", ratio_text(plan["ratios"]),
                "--data-ratio", args.data_ratio,
                "--num-scaling-params", args.num_scaling_params,
                "--data-multiplier", args.data_multiplier,
                "--shard-size", args.shard_size,
                "--val-ratio", args.val_ratio,
                "--seed", args.seed,
                "--max-shards", args.max_shards,
                "--num-npu", args.num_npu,
            ]
            if plan.get("strategy_path"):
                command.extend([
                    "--manual-strategy", plan["strategy_path"],
                    "--manual-strategy-config", json.dumps(plan.get("strategy_config", {})),
                ])
            env = dict(os.environ, SKIP_RANDOM="1")
            subprocess.run(command, check=True, env=env)
            plan_dir = output / f"manual_{plan_id}_data"
            if plan_dir.exists():
                shutil.rmtree(plan_dir)
            (temporary / "manual_ratio_data").replace(plan_dir)
            stats_path = temporary / "dataset_stats.json"
        stats = json.loads(stats_path.read_text(encoding="utf-8"))["manual_ratio"]
        manifest.append({
            "id": plan_id,
            "label": plan.get("label", plan_id),
            "data_dir": str(plan_dir),
            "tokens": stats["tokens"],
            "ratios": plan["ratios"],
            "strategy_path": plan.get("strategy_path", ""),
        })
    (output / "manual_plans_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
