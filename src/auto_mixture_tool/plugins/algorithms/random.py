"""Random mixing algorithm plugin.

Selects documents uniformly at random while matching a target token budget.
Useful as a simple baseline that is comparable to QuadMix in token count.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from auto_mixture_tool.plugins.base import AlgorithmAdapter, CommandSpec


class RandomAlgorithm(AlgorithmAdapter):
    id = "random"
    display_name = "Random uniform baseline"

    def build(self, request: dict[str, Any], workspace: Path) -> list[CommandSpec]:
        config = request.get("algorithm_config", {})
        output = request.get("output_uri") or str(
            workspace / "result" / request["job_id"] / "random"
        )
        args = [
            str(workspace / "scripts" / "platform" / "run_random_mixing.py"),
            "--dataset", request["dataset_uri"],
            "--schema", request["schema_uri"],
            "--output", output,
            "--seed", str(config.get("seed", 42)),
        ]
        if "target_tokens" in config:
            args.extend(["--target-tokens", str(config["target_tokens"])])
        if "target_docs" in config:
            args.extend(["--target-docs", str(config["target_docs"])])
        return [CommandSpec("random-selection", "python", args, cwd=str(workspace))]
