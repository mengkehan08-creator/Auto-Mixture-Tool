"""Generate a machine-readable and Markdown report for all manual plans."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from nanochat_mid_compare.generate_report import parse_eval_log


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--runs", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    plans = {item["id"]: item for item in json.loads(Path(args.manifest).read_text(encoding="utf-8"))}
    rows = []
    with open(args.runs, encoding="utf-8") as handle:
        for values in csv.reader(handle, delimiter="\t"):
            if len(values) != 6:
                continue
            plan_id, label, data_dir, model_tag, train_log, eval_log = values
            item = dict(plans[plan_id])
            item.update({
                "label": label, "data_dir": data_dir, "model_tag": model_tag,
                "train_log": train_log, "eval_log": eval_log,
                "evaluation": parse_eval_log(eval_log),
            })
            rows.append(item)
    output = Path(args.output_dir)
    (output / "manual_plans_report.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = ["# Manual sampling plan results", "", "| Plan | Ratios | Strategy | Model | CORE |", "|---|---|---|---|---:|"]
    for item in rows:
        ratios = ", ".join(f"{key}={value}" for key, value in item["ratios"].items())
        strategy = item.get("strategy_path") or "builtin:ratio-random"
        metric = item["evaluation"].get("core_metric")
        lines.append(f"| {item['label']} | {ratios} | `{strategy}` | `{item['model_tag']}` | {metric if metric is not None else 'N/A'} |")
    (output / "manual_plans_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
