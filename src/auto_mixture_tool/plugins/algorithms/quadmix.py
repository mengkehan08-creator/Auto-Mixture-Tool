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
        num_search = int(config.get("num_search", 5000))
        tiny_steps = int(config.get("tiny_steps", 3))
        npu_devices = int(config.get("npu_devices", 1))
        device_type = str(config.get("device_type", "cpu"))
        if num_experiments <= 0 or num_search <= 0 or tiny_steps <= 0:
            raise ValueError(
                "quadmix num_experiments, num_search and tiny_steps must be positive"
            )
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
            "--tiny-steps", str(tiny_steps),
            "--device-type", device_type,
            "--npu-devices", str(npu_devices),
            "--val-set", str(config.get("proxy_validation_set", "cap_v1")),
        ]
        if config.get("target_tokens") is not None:
            if float(config["target_tokens"]) < 0:
                raise ValueError("quadmix target_tokens must not be negative")
            args.extend(["--target-tokens", str(config["target_tokens"])])
        if config.get("tokenizer_path"):
            args.extend(["--tokenizer-path", str(config["tokenizer_path"])])
        if config.get("proxy_validation_path"):
            args.extend(["--val-path", str(config["proxy_validation_path"])])
        if config.get("algorithm_nodes") not in (None, "auto"):
            nodes = int(config["algorithm_nodes"])
            if nodes <= 0:
                raise ValueError("quadmix algorithm_nodes must be positive or auto")
            args.extend(["--distributed-nodes", str(nodes)])
        if config.get("seed") is not None:
            args.extend(["--seed", str(int(config["seed"]))])
        if config.get('sampling_bounds') is not None:
            from quadmix.core.sampling_bounds import validate_sampling_bounds
            for name, (low, high) in validate_sampling_bounds(config['sampling_bounds']).items():
                args.extend([f'--{name}-min', str(low), f'--{name}-max', str(high)])
        if config.get("coordination_uri"):
            args.extend(["--coordination-uri", str(config["coordination_uri"])])
        configurable = {
            "top_k": ("--top-k", int, 1),
            "block_size": ("--block-size", int, 1),
            "micro_batch_size": ("--micro-batch-size", int, 1),
            "global_batch_size": ("--global-batch-size", int, 1),
            "rank_ref_size": ("--rank-ref-size", int, 1),
            "checkpoint_interval": ("--checkpoint-interval", int, 1),
            "coordination_timeout": ("--coordination-timeout", float, 0),
        }
        for key, (flag, converter, minimum) in configurable.items():
            if config.get(key) is None:
                continue
            value = converter(config[key])
            if value < minimum:
                raise ValueError(f"quadmix {key} must be >= {minimum}")
            args.extend([flag, str(value)])
        if config.get("search_mode"):
            args.extend(["--search-mode", str(config["search_mode"])])
        return [CommandSpec("quadmix-selection", "python", args, cwd=str(workspace))]
