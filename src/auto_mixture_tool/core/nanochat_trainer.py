"""Phase 2: NanoChat mid-training as a real in-process ``Trainer``.

This is the canonical-contract implementation that *actually launches* NanoChat
mid-training (``nanochat_mid_compare``) instead of merely emitting a command
plan. ``Trainer.train`` materializes the (mixed) :class:`UnifiedDataset` to
disk, assembles the environment the experiment script expects, and runs it.

The real training is a cluster/NPU job driven by ``run_experiment.sh`` (or
``run_stem_experiment.sh`` for the STEM variant). It cannot execute offline, so
``train`` accepts ``dry_run=True`` to verify the contract and the resolved
command without launching nanochat.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from quadmix_platform.interfaces import Trainer, UnifiedDataset


class NanoChatTrainer(Trainer):
    """In-process NanoChat mid-training trainer (wraps ``nanochat_mid_compare``)."""

    id = "nanochat-core"
    display_name = "NanoChat mid-training (in-process launcher)"

    def __init__(
        self,
        *,
        experiment_script: str | Path | None = None,
        use_stem: bool = False,
        nanochat_repo: str | None = None,
        model_dir: str | None = None,
        base_model_tag: str | None = None,
        result_dir: str | None = None,
        preprocessed_data_dir: str | None = None,
        npu_devices: int = 8,
        target_param_data_ratio: float = 0.5,
        seed: int = 42,
        dry_run: bool = False,
        token_budget: int | None = None,
        total_batch_size: int | None = None,
        device_batch_size: int = 1,
        num_iterations: int = 0,
        eval_bundle_dir: str | None = None,
        load_optimizer: bool = False,
    ) -> None:
        self.use_stem = use_stem
        self.experiment_script = experiment_script
        self.nanochat_repo = nanochat_repo
        self.model_dir = model_dir
        self.base_model_tag = base_model_tag
        self.result_dir = result_dir
        self.preprocessed_data_dir = preprocessed_data_dir
        self.npu_devices = npu_devices
        self.target_param_data_ratio = target_param_data_ratio
        self.seed = seed
        self.dry_run = dry_run
        self.training_config = {"device_batch_size": device_batch_size, "num_iterations": num_iterations}
        for key, value in (("token_budget", token_budget), ("total_batch_size", total_batch_size)):
            if value is not None:
                self.training_config[key] = value
        self.eval_bundle_dir = eval_bundle_dir
        self.load_optimizer = load_optimizer

    # ------------------------------------------------------------------ #
    def _resolve_script(self, repo_root: Path) -> Path:
        if self.experiment_script is not None:
            return Path(self.experiment_script)
        name = "run_stem_experiment.sh" if self.use_stem else "run_experiment.sh"
        return repo_root / "nanochat_mid_compare" / name

    def _materialize(self, dataset: UnifiedDataset, output_dir: Path) -> Path:
        data_path = output_dir / "quadmix_sampled_data.jsonl"
        with open(data_path, "w", encoding="utf-8") as f:
            for s in dataset:
                row = {"id": s.id, "text": s.text, "domain": s.domain}
                row.update(s.metadata)
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return data_path

    def _build_env(self, data_path: Path, output_dir: Path, repo_root: Path) -> dict[str, str]:
        env = dict(os.environ)
        env["QUADMIX_SAMPLED_DATA"] = str(data_path)
        if self.preprocessed_data_dir:
            env["PREPROCESSED_DATA_DIR"] = self.preprocessed_data_dir
        if self.nanochat_repo:
            env["NANOCHAT_REPO"] = self.nanochat_repo
        if self.model_dir:
            env["NANOCHAT_MODEL_DIR"] = self.model_dir
        if self.base_model_tag:
            env["BASE_MODEL_TAG"] = self.base_model_tag
        env["NUM_NPU"] = str(self.npu_devices)
        env["TARGET_PARAM_DATA_RATIO"] = str(self.target_param_data_ratio)
        env["SEED"] = str(self.seed)
        env["RESULT_DIR"] = self.result_dir or str(output_dir / "nanochat_results")
        env["MID_CHECKPOINTS_OUTPUT_DIR"] = str(output_dir / "mid_checkpoints")
        env["NANOCHAT_DISABLE_WANDB"] = "1"
        env["NANOCHAT_LOAD_OPTIMIZER"] = "1" if self.load_optimizer else "0"
        names = {"token_budget": "TRAIN_TOKEN_BUDGET", "total_batch_size": "TRAIN_TOTAL_BATCH_SIZE",
                 "device_batch_size": "DEVICE_BATCH_SIZE", "num_iterations": "TRAIN_NUM_ITERATIONS"}
        for key, value in self.training_config.items():
            if type(value) is not int or value < (0 if key == "num_iterations" else 1):
                raise ValueError(f"Invalid NanoChat {key}")
            env[names[key]] = str(value)
        if self.training_config.get("token_budget") and self.training_config["num_iterations"]:
            raise ValueError("NanoChat token budget and fixed steps cannot be combined")
        if self.eval_bundle_dir:
            env["NANOCHAT_EVAL_BUNDLE_DIR"] = self.eval_bundle_dir
            env["NANOCHAT_SKIP_EVAL_DOWNLOAD"] = "1"
        return env

    # ------------------------------------------------------------------ #
    def train(self, dataset: UnifiedDataset, output_dir: str | Path) -> dict[str, Any]:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        repo_root = Path(__file__).resolve().parents[3]

        data_path = self._materialize(dataset, out)
        script = self._resolve_script(repo_root)
        env = self._build_env(data_path, out, repo_root)
        command = ["bash", str(script)]

        if self.dry_run:
            return {
                "checkpoint_uri": str(out / "mid_checkpoints"),
                "log_uri": env.get("RESULT_DIR", ""),
                "status": "planned",
                "command": command,
                "env": {k: v for k, v in env.items() if k.startswith(("QUADMIX_", "NANOCHAT_", "BASE_", "NUM_", "TARGET_", "SEED", "RESULT_", "PREPROCESSED_", "TRAIN_", "DEVICE_", "MID_", "AMT_"))},
                "data_path": str(data_path),
            }

        proc = subprocess.run(command, env=env, cwd=str(repo_root), check=False)
        if proc.returncode != 0:
            raise RuntimeError(
                f"NanoChat training failed (exit {proc.returncode}); script={script}"
            )
        return {
            "checkpoint_uri": str(out / "mid_checkpoints"),
            "log_uri": env.get("RESULT_DIR", ""),
            "status": "ran",
        }
