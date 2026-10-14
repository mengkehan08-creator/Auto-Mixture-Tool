"""NanoChat mid-training plugin.

Wraps the existing ``nanochat_mid_compare`` scripts as the current pluggable
training framework. Evaluation configuration is supplied by ``PlatformService``
at build time, so adding another evaluator does not create another trainer id.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from auto_mixture_tool.plugins.base import CommandSpec, TrainerAdapter


class NanoChatTrainer(TrainerAdapter):
    id = "nanochat"
    display_name = "NanoChat mid-training"

    _comparison_methods = {"quadmix", "random", "manual"}

    def build(self, request: dict[str, Any], workspace: Path) -> list[CommandSpec]:
        config = request.get("trainer_config", {})
        npu_devices = int(config.get("npu_devices", 8))
        target_ratio = float(config.get("target_param_data_ratio", 0.5))
        if npu_devices <= 0:
            raise ValueError("nanochat npu_devices must be positive")
        if target_ratio <= 0:
            raise ValueError("nanochat target_param_data_ratio must be positive")
        evaluator_id = str(request.get("evaluator_id", "stem"))
        evaluator_env = {
            str(key): str(value)
            for key, value in request.get("_evaluator_env", {}).items()
        }
        comparison = request.get("comparison_config", {})
        methods = comparison.get("methods", ["quadmix"])
        if not isinstance(methods, list) or not methods:
            raise ValueError("comparison_config.methods must be a non-empty list")
        methods = [str(method).strip().lower() for method in methods]
        unknown = sorted(set(methods) - self._comparison_methods)
        if unknown:
            raise ValueError(
                "unknown comparison methods: " + ", ".join(unknown)
            )
        if len(methods) != len(set(methods)):
            raise ValueError("comparison_config.methods must not contain duplicates")

        manual_ratios = comparison.get("manual_ratios", {})
        manual_plans = comparison.get("manual_plans")
        if manual_plans is None and manual_ratios:
            manual_plans = [{"id": "manual_default", "ratios": manual_ratios}]
        if manual_plans is None:
            manual_plans = []
        if "manual" in methods:
            if not isinstance(manual_plans, list) or not manual_plans:
                raise ValueError(
                    "comparison_config.manual_plans is required for manual comparison"
                )
            normalized_plans = []
            seen_plan_ids: set[str] = set()
            for plan in manual_plans:
                if not isinstance(plan, dict):
                    raise ValueError("each manual plan must be an object")
                plan_id = str(plan.get("id", "")).strip()
                if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", plan_id):
                    raise ValueError("manual plan id must use 1-64 letters, digits, _ or -")
                if plan_id in seen_plan_ids:
                    raise ValueError(f"duplicate manual plan id: {plan_id}")
                seen_plan_ids.add(plan_id)
                ratios = plan.get("ratios", {})
                if not isinstance(ratios, dict) or not ratios:
                    raise ValueError(f"manual plan {plan_id} requires ratios")
                normalized_ratios = {
                    str(domain): float(ratio) for domain, ratio in ratios.items()
                }
                if any(not domain or ratio <= 0 for domain, ratio in normalized_ratios.items()):
                    raise ValueError(f"manual plan {plan_id} domains and ratios must be positive")
                strategy = plan.get("strategy", {})
                if not isinstance(strategy, dict):
                    raise ValueError(f"manual plan {plan_id} strategy must be an object")
                strategy_config = strategy.get("config", {})
                if not isinstance(strategy_config, dict):
                    raise ValueError(f"manual plan {plan_id} strategy.config must be an object")
                label = str(plan.get("label") or plan_id)
                if any(char in label for char in "\t\r\n"):
                    raise ValueError(f"manual plan {plan_id} label cannot contain tabs or newlines")
                normalized_plans.append({
                    "id": plan_id,
                    "label": label,
                    "ratios": normalized_ratios,
                    "strategy_path": str(strategy.get("script_path") or ""),
                    "strategy_config": strategy_config,
                })
        else:
            normalized_plans = []

        random_strategy = comparison.get("random_strategy", {})
        if not isinstance(random_strategy, dict):
            raise ValueError("comparison_config.random_strategy must be an object")
        if not isinstance(random_strategy.get("config", {}), dict):
            raise ValueError("comparison_config.random_strategy.config must be an object")

        output = request.get("output_uri") or str(
            workspace / "result" / request["job_id"] / "quadmix"
        )
        sampled = str(request.get("_training_dataset_uri") or Path(output) / "sampled_dataset")

        env = {
            "QUADMIX_SAMPLED_DATA": sampled,
            "PREPROCESSED_DATA_DIR": request["dataset_uri"],
            "SCHEMA_CONFIG": request["schema_uri"],
            "NUM_NPU": str(npu_devices),
            "TARGET_PARAM_DATA_RATIO": str(target_ratio),
            "COMPARISON_METHODS": ",".join(methods),
            "SEED": str(request.get('algorithm_config', {}).get('seed', 42)),
            "AMT_RUN_ID": os.environ.get("AMT_RUN_ID") or str(request["job_id"]),
            "MIX_GENERAL_DATA": "1" if config.get("mix_general_data", False) else "0",
            "NANOCHAT_DISABLE_WANDB": "1" if config.get("disable_wandb", True) else "0",
            "NANOCHAT_LOAD_OPTIMIZER": "1" if config.get("load_optimizer", False) else "0",
        }
        if config.get("data_world_size") is not None:
            world_size = int(config["data_world_size"])
            if world_size < 1:
                raise ValueError("nanochat data_world_size must be positive")
            env["AMT_DATA_WORLD_SIZE"] = str(world_size)
        for key, name, minimum in (("total_batch_size", "TRAIN_TOTAL_BATCH_SIZE", 1),
                                   ("token_budget", "TRAIN_TOKEN_BUDGET", 1),
                                   ("num_iterations", "TRAIN_NUM_ITERATIONS", 0),
                                   ("device_batch_size", "DEVICE_BATCH_SIZE", 1)):
            if key in config:
                value = config[key]
                if type(value) is not int or not minimum <= value <= 9007199254740991:
                    raise ValueError(f"nanochat {key} must be a valid integer")
                env[name] = str(value)
        if config.get("token_budget") and config.get("num_iterations"):
            raise ValueError("nanochat token budget and fixed steps cannot be combined")
        if normalized_plans:
            # The shell keeps backward compatibility with the first manual plan;
            # MANUAL_PLANS_JSON is the stable contract for multiple plans.
            normalized_ratios = normalized_plans[0]["ratios"]
            env["MANUAL_RATIO"] = ":".join(
                f"{domain}={ratio:g}" for domain, ratio in normalized_ratios.items()
            )
            env["MANUAL_PLANS_JSON"] = json.dumps(
                normalized_plans, ensure_ascii=False, separators=(",", ":")
            )
            first_strategy = normalized_plans[0]["strategy_path"]
            if first_strategy:
                env["MANUAL_STRATEGY_PATH"] = first_strategy
                env["MANUAL_STRATEGY_CONFIG_JSON"] = json.dumps(
                    normalized_plans[0]["strategy_config"], ensure_ascii=False,
                    separators=(",", ":"),
                )
        random_script = random_strategy.get("script_path")
        if random_script:
            env["RANDOM_STRATEGY_PATH"] = str(random_script)
            env["RANDOM_STRATEGY_CONFIG_JSON"] = json.dumps(
                random_strategy.get("config", {}), ensure_ascii=False,
                separators=(",", ":"),
            )
        if evaluator_id == "stem":
            env["STEM_DATA_DIR"] = request["dataset_uri"]

        optional = {
            "NANOCHAT_REPO": config.get("nanochat_repo"),
            "NANOCHAT_MODEL_DIR": config.get("model_dir"),
            "NANOCHAT_EVAL_BUNDLE_DIR": config.get("eval_bundle_dir"),
            "BASE_MODEL_TAG": config.get("base_model_tag"),
            "RESULT_DIR": config.get("result_dir"),
            "MID_CHECKPOINTS_OUTPUT_DIR": config.get("checkpoint_dir"),
            "PREPARED_COMPARISON_DATA_DIR": config.get(
                "prepared_comparison_data_dir"
            ),
        }
        env.update({key: str(value) for key, value in optional.items() if value})
        if config.get("skip_eval_download"):
            env["NANOCHAT_SKIP_EVAL_DOWNLOAD"] = "1"
        if config.get("prepare_only"):
            env["PREPARE_ONLY"] = "1"
        env.update(evaluator_env)

        if evaluator_id == "stem":
            script = workspace / "nanochat_mid_compare" / "run_stem_experiment.sh"
            executable = "bash"
            args = [str(script)]
        else:
            script = workspace / "nanochat_mid_compare" / "run_experiment.sh"
            executable = "bash"
            args = [str(script)]

        return [CommandSpec("nanochat-train-evaluate", executable, args, env, str(workspace))]
