"""QuadMix algorithm plugin.

The adapter only compiles the current QuaDMix runner into a ``CommandSpec``.
Execution remains the responsibility of the selected executor.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from auto_mixture_tool.plugins.base import AlgorithmAdapter, CommandSpec


class QuadMixAlgorithm(AlgorithmAdapter):
    """Current production mixing algorithm."""

    id = "quadmix"
    display_name = "QuaDMix"

    def build(self, request: dict[str, Any], workspace: Path) -> list[CommandSpec]:
        config = request.get("algorithm_config", {})
        num_experiments = int(config.get("num_experiments", 200))
        num_search = int(config.get("num_search", 2000))
        npu_devices = int(config.get("npu_devices", 1))
        device_type = str(config.get("device_type", "cpu"))
        if num_experiments <= 0 or num_search <= 0:
            raise ValueError("quadmix num_experiments and num_search must be positive")
        if npu_devices <= 0:
            raise ValueError("quadmix npu_devices must be positive")
        if device_type not in {"cpu", "cuda", "npu"}:
            raise ValueError("quadmix device_type must be one of: cpu, cuda, npu")
        output = request.get("output_uri") or str(
            workspace / "result" / request["job_id"] / "quadmix"
        )
        args = [
            str(workspace / "scripts" / "runners" / "run_essential_web_v1.py"),
            "--schema", str(request["schema_uri"]),
            "--preprocessed-dir", str(request["dataset_uri"]),
            "--output", output,
            "--num-experiments", str(num_experiments),
            "--num-search", str(num_search),
            "--device-type", device_type,
            "--npu-devices", str(npu_devices),
            "--val-set", str(config.get("proxy_validation_set", "cap_v1")),
        ]
        if config.get("target_tokens") is not None:
            if float(config["target_tokens"]) < 0:
                raise ValueError("quadmix target_tokens must not be negative")
            args.extend(["--target-tokens", str(config["target_tokens"])])
        return [CommandSpec("quadmix-selection", "python", args, cwd=str(workspace))]
