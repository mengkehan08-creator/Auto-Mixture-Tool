"""NanoChat mid-training plugin.

Wraps the existing ``nanochat_mid_compare`` scripts so they can be selected as a
pluggable trainer. The validator is injected at construction time, keeping the
training and evaluation methods decoupled.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from auto_mixture_tool.plugins.base import CommandSpec, TrainerAdapter, ValidatorAdapter


class NanoChatTrainer(TrainerAdapter):
    id = "nanochat"
    display_name = "NanoChat mid-training"

    def __init__(self, validator: ValidatorAdapter) -> None:
        self.validator = validator

    def build(self, request: dict[str, Any], workspace: Path) -> list[CommandSpec]:
        config = request.get("trainer_config", {})
        validator_config = request.get("validator_config", {})
        validator_env = self.validator.environment(validator_config)

        output = request.get("output_uri") or str(
            workspace / "result" / request["job_id"] / "quadmix"
        )
        sampled = str(Path(output) / "sampled_dataset")

        env = {
            "QUADMIX_SAMPLED_DATA": sampled,
            "PREPROCESSED_DATA_DIR": request["dataset_uri"],
            "NUM_NPU": str(config.get("npu_devices", 8)),
            "TARGET_PARAM_DATA_RATIO": str(config.get("target_param_data_ratio", 0.5)),
        }
        if self.validator.id == "stem":
            env["STEM_DATA_DIR"] = request["dataset_uri"]

        optional = {
            "NANOCHAT_REPO": config.get("nanochat_repo"),
            "NANOCHAT_MODEL_DIR": config.get("model_dir"),
            "BASE_MODEL_TAG": config.get("base_model_tag"),
            "RESULT_DIR": config.get("result_dir"),
        }
        env.update({key: str(value) for key, value in optional.items() if value})
        env.update(validator_env)

        # Custom STEM task / data path uses a Python dispatcher; otherwise shell.
        if self.validator.id == "stem" and (
            validator_config.get("tasks") or validator_config.get("validation_data_uri")
        ):
            script = workspace / "scripts" / "platform" / "run_nanochat_validation.py"
            executable = "python"
            args = [
                str(script),
                "--experiment-script",
                str(workspace / "nanochat_mid_compare" / "run_stem_experiment.sh"),
            ]
        else:
            script_name = (
                "run_stem_experiment.sh"
                if self.validator.id == "stem"
                else "run_experiment.sh"
            )
            script = workspace / "nanochat_mid_compare" / script_name
            executable = "bash"
            args = [str(script)]

        return [CommandSpec("nanochat-train-evaluate", executable, args, env, str(workspace))]
