from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

from .interfaces import AlgorithmAdapter, ExecutorAdapter, TrainerAdapter, ValidatorAdapter
from .models import CommandSpec, JobRecord


class QuadMixAlgorithm(AlgorithmAdapter):
    id = "quadmix"
    display_name = "QuaDMix"

    def build(self, request: dict[str, Any], workspace: Path) -> list[CommandSpec]:
        config = request.get("algorithm_config", {})
        output = request.get("output_uri") or str(workspace / "result" / request["job_id"] / "quadmix")
        args = [
            str(workspace / "scripts" / "runners" / "run_essential_web_v1.py"),
            "--schema", request["schema_uri"],
            "--preprocessed-dir", request["dataset_uri"],
            "--output", output,
            "--num-experiments", str(config.get("num_experiments", 200)),
            "--num-search", str(config.get("num_search", 2000)),
            "--device-type", str(config.get("device_type", "cpu")),
            "--npu-devices", str(config.get("npu_devices", 1)),
            "--val-set", str(config.get("proxy_validation_set", "cap_v1")),
        ]
        return [CommandSpec("quadmix-selection", "python", args, cwd=str(workspace))]


class NanoChatTrainer(TrainerAdapter):
    id = "nanochat"
    display_name = "NanoChat mid-training"

    def __init__(self, validator: ValidatorAdapter) -> None:
        self.validator = validator

    def build(self, request: dict[str, Any], workspace: Path) -> list[CommandSpec]:
        config = request.get("trainer_config", {})
        validator_config = request.get("validator_config", {})
        if self.validator.id == "stem" and (validator_config.get("tasks") or validator_config.get("validation_data_uri")):
            script = workspace / "scripts" / "platform" / "run_nanochat_validation.py"
            executable = "python"
        else:
            script = workspace / "nanochat_mid_compare" / ("run_stem_experiment.sh" if self.validator.id == "stem" else "run_experiment.sh")
            executable = "bash"
        output = request.get("output_uri") or str(workspace / "result" / request["job_id"] / "quadmix")
        sampled = str(Path(output) / "sampled_dataset")
        env = {
            "QUADMIX_SAMPLED_DATA": sampled,
            "PREPROCESSED_DATA_DIR": request["dataset_uri"],
            "NUM_NPU": str(config.get("npu_devices", 8)),
            "TARGET_PARAM_DATA_RATIO": str(config.get("target_param_data_ratio", 0.5)),
        }
        if self.validator.id == "stem":
            # The existing STEM experiment uses a dedicated variable name.
            env["STEM_DATA_DIR"] = request["dataset_uri"]
        optional = {
            "NANOCHAT_REPO": config.get("nanochat_repo"),
            "NANOCHAT_MODEL_DIR": config.get("model_dir"),
            "BASE_MODEL_TAG": config.get("base_model_tag"),
            "RESULT_DIR": config.get("result_dir"),
        }
        env.update({key: str(value) for key, value in optional.items() if value})
        env.update(self.validator.environment(validator_config))
        args = [str(script)]
        if executable == "python":
            args.extend(["--experiment-script", str(workspace / "nanochat_mid_compare" / "run_stem_experiment.sh")])
        return [CommandSpec("nanochat-train-evaluate", executable, args, env, str(workspace))]


class NoTrainer(TrainerAdapter):
    id = "none"
    display_name = "Skip downstream training"

    def build(self, request: dict[str, Any], workspace: Path) -> list[CommandSpec]:
        return []


class NanoChatCoreValidator(ValidatorAdapter):
    id = "core"
    display_name = "NanoChat CORE benchmarks"

    def environment(self, config: dict[str, Any]) -> dict[str, str]:
        return {"EVAL_BENCHMARKS": str(config.get("benchmarks", "core"))}


class StemValidator(ValidatorAdapter):
    id = "stem"
    display_name = "Customizable STEM evaluation"

    def environment(self, config: dict[str, Any]) -> dict[str, str]:
        env = {"EVAL_BENCHMARKS": str(config.get("benchmarks", "stem"))}
        if config.get("validation_data_uri"):
            env["STEM_VALIDATION_DATA"] = str(config["validation_data_uri"])
        if config.get("tasks"):
            tasks = config["tasks"]
            env["STEM_TASKS"] = ",".join(tasks) if isinstance(tasks, list) else str(tasks)
        return env


class LocalExecutor(ExecutorAdapter):
    """Development executor: run each ``CommandSpec`` stage as a local subprocess.

    Intended for the dev environment (``pip install -e .`` + deps installed): it
    walks ``job.stages`` in order and invokes ``[executable, *args]`` with the
    stage's ``env`` (overlaid on the current environment) and ``cwd``. The first
    failing stage short-circuits the job. Returns ``(status, external_id, msg)``
    where ``external_id`` is the local PID of the last stage's process.
    """

    id = "local"
    display_name = "Local subprocess (dev)"

    def submit(self, job: JobRecord) -> tuple[str, str, str]:
        last_pid = ""
        for stage in job.stages:
            env = dict(os.environ)
            env.update({str(k): str(v) for k, v in stage.env.items()})
            cmd = [stage.executable, *stage.args]
            try:
                completed = subprocess.run(
                    cmd,
                    env=env,
                    cwd=stage.cwd,
                    check=False,
                )
            except FileNotFoundError as exc:
                return "FAILED", "", f"stage '{stage.name}' executable not found: {exc}"
            last_pid = str(completed.returncode)
            if completed.returncode != 0:
                return (
                    "FAILED",
                    last_pid,
                    f"stage '{stage.name}' exited with code {completed.returncode}",
                )
        return "SUCCEEDED", last_pid, "All stages completed locally."


class HpcClusterExecutor(ExecutorAdapter):
    """Executor that submits jobs to a High-Performance Computing cluster API.

    Production backend: the platform
    serializes the compiled ``CommandSpec`` stages into JSON and POSTs them to
    the cluster's REST submission endpoint. Use the ``local`` executor for dev.
    """

    id = "hpc-cluster"
    display_name = "HPC cluster API"

    def __init__(self, endpoint: str | None = None, token_env: str = "AMT_CLUSTER_TOKEN") -> None:
        self.endpoint = endpoint
        self.token_env = token_env

    def submit(self, job: JobRecord) -> tuple[str, str, str]:
        config = job.request.get("executor_config", {})
        endpoint = config.get("endpoint") or self.endpoint
        if not endpoint:
            raise ValueError("executor_config.endpoint is required for hpc-cluster")
        payload = json.dumps({"name": job.id, "stages": [stage.to_dict() for stage in job.stages]}).encode()
        headers = {"Content-Type": "application/json"}
        token = os.environ.get(config.get("token_env", self.token_env))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.load(response)
        return str(value.get("status", "SUBMITTED")), str(value.get("id", "")), "Submitted to HPC cluster API."
