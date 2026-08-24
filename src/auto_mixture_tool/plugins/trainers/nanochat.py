"""NanoChat mid-training plugin.

Wraps the existing ``nanochat_mid_compare`` scripts as the current pluggable
training framework. Evaluation configuration is supplied by ``PlatformService``
at build time, so adding another evaluator does not create another trainer id.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from auto_mixture_tool.plugins.base import CommandSpec, TrainerAdapter


class NanoChatTrainer(TrainerAdapter):
    id = "nanochat"
    display_name = "NanoChat mid-training"

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

        output = request.get("output_uri") or str(
            workspace / "result" / request["job_id"] / "quadmix"
        )
        sampled = str(Path(output) / "sampled_dataset")

        env = {
            "QUADMIX_SAMPLED_DATA": sampled,
            "PREPROCESSED_DATA_DIR": request["dataset_uri"],
            "NUM_NPU": str(npu_devices),
            "TARGET_PARAM_DATA_RATIO": str(target_ratio),
        }
        if evaluator_id == "stem":
            env["STEM_DATA_DIR"] = request["dataset_uri"]

        optional = {
            "NANOCHAT_REPO": config.get("nanochat_repo"),
            "NANOCHAT_MODEL_DIR": config.get("model_dir"),
            "BASE_MODEL_TAG": config.get("base_model_tag"),
            "RESULT_DIR": config.get("result_dir"),
        }
        env.update({key: str(value) for key, value in optional.items() if value})
        env.update(evaluator_env)

        # STEM currently uses the Python dispatcher so task/data switches are
        # always forwarded consistently.
        if evaluator_id == "stem":
            script = workspace / "scripts" / "platform" / "run_nanochat_validation.py"
            executable = "python"
            args = [
                str(script),
                "--experiment-script",
                str(workspace / "nanochat_mid_compare" / "run_stem_experiment.sh"),
            ]
        else:
            script = workspace / "nanochat_mid_compare" / "run_experiment.sh"
            executable = "bash"
            args = [str(script)]

        return [CommandSpec("nanochat-train-evaluate", executable, args, env, str(workspace))]
