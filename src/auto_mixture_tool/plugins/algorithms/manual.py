"""Manual ratio mixing algorithm plugin.

Allows the operator to specify fixed per-domain sampling ratios. This is useful
for reproducing a known recipe or comparing QuadMix against a hand-tuned
baseline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from auto_mixture_tool.plugins.base import AlgorithmAdapter, CommandSpec


class ManualRatioAlgorithm(AlgorithmAdapter):
    id = "manual"
    display_name = "Manual ratio baseline"

    def build(self, request: dict[str, Any], workspace: Path) -> list[CommandSpec]:
        config = request.get("algorithm_config", {})
        output = request.get("output_uri") or str(
            workspace / "result" / request["job_id"] / "manual"
        )
        ratios = config.get("domain_ratios", {})
        if not ratios:
            raise ValueError("manual algorithm_config.domain_ratios is required")
        ratios_path = workspace / "temp" / f"manual_ratios_{request['job_id']}.json"
        ratios_path.parent.mkdir(parents=True, exist_ok=True)
        ratios_path.write_text(json.dumps(ratios, ensure_ascii=False, indent=2), encoding="utf-8")
        args = [
            str(workspace / "scripts" / "platform" / "run_manual_ratio.py"),
            "--dataset", request["dataset_uri"],
            "--schema", request["schema_uri"],
            "--ratios", str(ratios_path),
            "--output", output,
            "--seed", str(config.get("seed", 42)),
        ]
        if "target_tokens" in config:
            args.extend(["--target-tokens", str(config["target_tokens"])])
        return [CommandSpec("manual-selection", "python", args, cwd=str(workspace))]
