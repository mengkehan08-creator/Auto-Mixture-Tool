"""Phase 2: STEM evaluation as a real in-process ``Evaluator``.

This is the canonical-contract implementation that *actually runs* STEM
benchmark evaluation (``nanochat_mid_compare`` + the platform validation
dispatcher) instead of merely capturing an eval environment. ``Evaluator.evaluate``
launches ``scripts/platform/run_nanochat_validation.py`` against a trained
checkpoint and parses the JSON metrics it emits.

The real benchmark needs the checkpoint + STEM validation data + nanochat eval
harness, so it cannot execute offline. ``evaluate`` accepts ``dry_run=True`` to
verify the contract and the resolved command without launching the benchmark.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from quadmix_platform.interfaces import Evaluator


class STEMEvaluator(Evaluator):
    """In-process STEM benchmark evaluator (wraps ``nanochat_mid_compare``)."""

    id = "stem-core"
    display_name = "STEM benchmark evaluation (in-process launcher)"

    def __init__(
        self,
        *,
        tasks: list[str] | None = None,
        validation_data_uri: str | None = None,
        benchmarks: str = "stem",
        nanochat_repo: str | None = None,
        experiment_script: str | Path | None = None,
        validation_dispatcher: str | Path | None = None,
        dry_run: bool = False,
    ) -> None:
        self.tasks = list(tasks) if tasks else None
        self.validation_data_uri = validation_data_uri
        self.benchmarks = benchmarks
        self.nanochat_repo = nanochat_repo
        self.experiment_script = experiment_script
        self.validation_dispatcher = validation_dispatcher
        self.dry_run = dry_run
        self.last_plan: dict[str, Any] | None = None

    # ------------------------------------------------------------------ #
    def _resolve(self, repo_root: Path) -> tuple[Path, Path]:
        dispatcher = Path(self.validation_dispatcher) if self.validation_dispatcher else (
            repo_root / "scripts" / "platform" / "run_nanochat_validation.py"
        )
        script = Path(self.experiment_script) if self.experiment_script else (
            repo_root / "nanochat_mid_compare" / "run_stem_experiment.sh"
        )
        return dispatcher, script

    def _build_env(self, checkpoint: dict[str, Any]) -> dict[str, str]:
        env = dict(os.environ)
        if self.tasks:
            env["STEM_TASKS"] = ",".join(self.tasks)
        if self.validation_data_uri:
            env["STEM_VALIDATION_DATA"] = str(self.validation_data_uri)
        env["EVAL_BENCHMARKS"] = self.benchmarks
        if self.nanochat_repo:
            env["NANOCHAT_REPO"] = self.nanochat_repo
        ckpt = checkpoint.get("checkpoint_uri") or checkpoint.get("checkpoint") or ""
        if ckpt:
            env["CHECKPOINT_URI"] = str(ckpt)
        return env

    # ------------------------------------------------------------------ #
    def evaluate(self, checkpoint: dict[str, Any], dataset: Any = None) -> dict[str, float]:
        repo_root = Path(__file__).resolve().parents[3]
        dispatcher, script = self._resolve(repo_root)
        env = self._build_env(checkpoint)
        command = [sys.executable, str(dispatcher), "--experiment-script", str(script)]

        if self.dry_run:
            self.last_plan = {"command": command, "env": {
                k: v for k, v in env.items()
                if k.startswith(("STEM_", "EVAL_", "NANOCHAT_", "CHECKPOINT_"))
            }}
            return {}

        proc = subprocess.run(command, env=env, cwd=str(repo_root),
                              capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(
                f"STEM evaluation failed (exit {proc.returncode}): {proc.stderr[-500:]}"
            )
        # The dispatcher prints a JSON metrics object on the last line.
        metrics: dict[str, float] = {}
        for line in reversed(proc.stdout.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    parsed = json.loads(line)
                    metrics = {k: float(v) for k, v in parsed.items() if _is_number(v)}
                except json.JSONDecodeError:
                    pass
                break
        return metrics


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
