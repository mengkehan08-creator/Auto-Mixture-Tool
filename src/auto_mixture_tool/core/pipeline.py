"""Layer 2 (orchestration) over the canonical Phase-1 contracts.

``CanonicalPipeline`` wires the four core interfaces -- :class:`MixingAlgorithm`
(Layer 6), :class:`Trainer` (Layer 7a), :class:`Evaluator` (Layer 7b) -- together
with the :class:`UnifiedDataset` (Layer 5) and an optional swappable
``FormatValidatorAdapter`` (Layer 3/4) into one end-to-end run:

    上传数据 -> (格式校验) -> 统一数据集 -> 选择配比算法
            -> 生成训练数据 -> 训练 -> 验证 -> 结果分析

Two execution modes are supported:

* ``mode="inprocess"`` -- the components implement the contract directly (e.g.
  :class:`RandomMixingAlgorithm` + :class:`NoOpTrainer` + :class:`StubEvaluator`).
  The whole flow runs in the current process and needs only the standard
  library, which makes it the reference path for proving the contract offline.
* ``mode="command"`` -- the components are the Phase-1 bridges
  (``CommandDrivenMixingAlgorithm`` / ``CommandDrivenTrainer`` /
  ``CommandDrivenEvaluator``). ``fit`` / ``select`` / ``export`` / ``train``
  compile command plans instead of executing; the pipeline captures those plans
  so they can be shipped to a cluster by an ``ExecutorAdapter`` (Phase 2).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from quadmix_platform.interfaces import (
    Evaluator,
    FormatValidatorAdapter,
    MixingAlgorithm,
    Sample,
    Trainer,
    UnifiedDataset,
)

from auto_mixture_tool.core.dataset import load_dataset


class CanonicalPipeline:
    """End-to-end orchestrator built purely on the canonical interfaces."""

    def __init__(
        self,
        algorithm: MixingAlgorithm,
        trainer: Trainer,
        evaluator: Evaluator,
        format_validator: FormatValidatorAdapter | None = None,
        mode: str = "inprocess",
        output_format: str = "json",
    ) -> None:
        if mode not in {"inprocess", "command"}:
            raise ValueError("mode must be 'inprocess' or 'command'")
        if output_format not in {"json", "jsonl"}:
            raise ValueError("output_format must be 'json' or 'jsonl'")
        self.algorithm = algorithm
        self.trainer = trainer
        self.evaluator = evaluator
        self.format_validator = format_validator
        self.mode = mode
        self.output_format = output_format

    # ------------------------------------------------------------------ #
    # Factory: the stdlib-only reference path (no numpy / pandas needed).
    # ------------------------------------------------------------------ #
    @classmethod
    def reference(
        cls,
        *,
        seed: int = 0,
        fraction: float = 1.0,
        mode: str = "inprocess",
        format_validator: FormatValidatorAdapter | None = None,
        output_format: str = "json",
    ) -> "CanonicalPipeline":
        """Build a pipeline from the in-process reference implementations."""
        from auto_mixture_tool.core.evaluation import StubEvaluator
        from auto_mixture_tool.core.mixing import RandomMixingAlgorithm
        from auto_mixture_tool.core.training import NoOpTrainer

        return cls(
            algorithm=RandomMixingAlgorithm(seed=seed, fraction=fraction),
            trainer=NoOpTrainer(),
            evaluator=StubEvaluator(),
            format_validator=format_validator,
            mode=mode,
            output_format=output_format,
        )

    @classmethod
    def from_config(
        cls,
        *,
        algorithm_id: str = "random-core",
        trainer_id: str = "none-core",
        evaluator_id: str = "stub-core",
        mode: str = "inprocess",
        format_validator: FormatValidatorAdapter | None = None,
        output_format: str = "json",
    ) -> "CanonicalPipeline":
        """Assemble a pipeline by looking components up in the canonical registry."""
        from auto_mixture_tool.core.registry import build_canonical_registry

        reg = build_canonical_registry()
        return cls(
            algorithm=reg["algorithms"].get(algorithm_id),
            trainer=reg["trainers"].get(trainer_id),
            evaluator=reg["evaluators"].get(evaluator_id),
            format_validator=format_validator,
            mode=mode,
            output_format=output_format,
        )

    # ------------------------------------------------------------------ #
    # Run
    # ------------------------------------------------------------------ #
    def run(
        self,
        *,
        dataset_uri: str,
        output_dir: str | Path,
        schema: Any = None,
        sample_size: int = 0,
        job_id: str = "canonical",
    ) -> dict[str, Any]:
        """Execute the full 9-layer flow and return a structured result.

        The result dict is also written to ``<output_dir>/pipeline_summary.json``.
        """
        output_dir = Path(output_dir)
        (output_dir / "mixed").mkdir(parents=True, exist_ok=True)
        (output_dir / "ckpt").mkdir(parents=True, exist_ok=True)

        started = time.time()
        result: dict[str, Any] = {
            "job_id": job_id,
            "mode": self.mode,
            "components": {
                "algorithm": self.algorithm.id,
                "trainer": self.trainer.id,
                "evaluator": self.evaluator.id,
                "format_validator": self.format_validator.id if self.format_validator else None,
            },
            "stages": {},
        }

        # --- Layer 3/4: swappable data-format conformance gate ------------ #
        if self.format_validator is not None:
            fmt_req = {
                "dataset_uri": dataset_uri,
                "schema_uri": getattr(schema, "source_uri", "") if schema else "",
                "sample_size": sample_size,
            }
            fmt = self.format_validator.validate(fmt_req)
            result["stages"]["format_check"] = fmt
            if not fmt.get("valid", True):
                result["status"] = "REJECTED_FORMAT"
                result["error"] = "; ".join(fmt.get("errors", []))
                self._write_summary(output_dir, result, started)
                return result

        # --- Layer 5: unify raw data into the internal Sample shape ------- #
        dataset = load_dataset(dataset_uri, schema)
        result["stages"]["unify"] = {
            "dataset_uri": str(dataset_uri),
            "size": dataset.size,
            "domains": dataset.domains(),
        }

        # --- Layer 6: mixing algorithm ------------------------------------- #
        self.algorithm.fit(dataset)
        selected: UnifiedDataset = self.algorithm.select(dataset)
        mixed_uri = self.algorithm.export(output_dir / "mixed", fmt=self.output_format)
        result["stages"]["mixing"] = {
            "selected_size": selected.size,
            "mixed_uri": mixed_uri,
        }

        # --- Layer 7a: downstream training -------------------------------- #
        ckpt = self.trainer.train(selected, output_dir / "ckpt")
        result["stages"]["training"] = ckpt

        # --- Layer 7b: evaluation (kept separate from training) ----------- #
        metrics = self.evaluator.evaluate(ckpt, selected)
        result["stages"]["evaluation"] = metrics

        # --- Layer 8/9: result analysis ----------------------------------- #
        result["status"] = (
            "PLANNED"
            if self.mode == "command" or ckpt.get("status") == "planned"
            else "COMPLETED"
        )
        result["metrics"] = metrics
        self._write_summary(output_dir, result, started)
        return result

    # ------------------------------------------------------------------ #
    def _write_summary(self, output_dir: Path, result: dict[str, Any], started: float) -> None:
        result["elapsed_sec"] = round(time.time() - started, 4)
        (output_dir / "pipeline_summary.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
