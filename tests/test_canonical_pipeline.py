"""Offline smoke test for the Phase-1 canonical pipeline.

Runs the full 9-layer flow with the stdlib-only reference implementations
(RandomMixingAlgorithm + NoOpTrainer + StubEvaluator) and with a fake
command-driven bridge, proving the canonical contracts hold without numpy /
pandas. Run with:  PYTHONPATH=src python tests/test_canonical_pipeline.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from quadmix_platform.interfaces import UnifiedDataset
from quadmix_platform.models import CommandSpec

from auto_mixture_tool.core.dataset import CsvJsonlDataset, Sample
from auto_mixture_tool.core.evaluation import CommandDrivenEvaluator, StubEvaluator
from auto_mixture_tool.core.mixing import CommandDrivenMixingAlgorithm, RandomMixingAlgorithm
from auto_mixture_tool.core.pipeline import CanonicalPipeline
from auto_mixture_tool.core.training import CommandDrivenTrainer, NoOpTrainer


def _make_csv(tmp: Path) -> Path:
    import csv

    p = tmp / "sample.csv"
    rows = [
        ("The cat sat on the mat.", "web"),
        ("Photosynthesis converts light to energy.", "science"),
        ("def add(a, b): return a + b", "code"),
        ("Napoleon lost at Waterloo in 1815.", "history"),
    ]
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["text", "domain"])
        w.writerows(rows)
    return p


def test_reference_inprocess():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        csv_path = _make_csv(td)

        pipe = CanonicalPipeline.reference(seed=1, fraction=0.75)
        result = pipe.run(dataset_uri=str(csv_path), output_dir=td / "out", job_id="ref")

        assert result["status"] == "COMPLETED", result
        assert result["components"]["algorithm"] == "random-core"
        assert result["stages"]["unify"]["size"] == 4
        assert set(result["stages"]["unify"]["domains"]) == {"web", "science", "code", "history"}
        # RandomMixingAlgorithm selects 75% -> 3 of 4
        assert result["stages"]["mixing"]["selected_size"] == 3
        assert Path(result["stages"]["mixing"]["mixed_uri"]).exists()
        assert result["stages"]["training"]["status"] == "skipped"
        assert result["metrics"] == {"stub_score": 0.0}

        summary = json.loads((td / "out" / "pipeline_summary.json").read_text(encoding="utf-8"))
        assert summary["status"] == "COMPLETED"
        print("PASS reference/in-process:", json.dumps(result["stages"], ensure_ascii=False))


def test_command_bridge_captures_plans():
    """Command-driven bridges compile plans; pipeline records them without executing."""

    class FakeAdapter:
        id = "fake-algo"
        display_name = "Fake algorithm"

        def build(self, request, workspace):
            return [CommandSpec(name="stage1", executable="echo", args=["mix"])]

    class FakeTrainerAdapter:
        id = "fake-trainer"
        display_name = "Fake trainer"

        def build(self, request, workspace):
            return [CommandSpec(name="train", executable="echo", args=["train"])]

    class FakeValidator:
        id = "fake-validator"
        display_name = "Fake validator"

        def environment(self, config):
            return {"BENCHMARKS": "stem"}

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        csv_path = _make_csv(td)

        algo = CommandDrivenMixingAlgorithm(FakeAdapter(), workspace=td, job_id="cmd")
        trainer = CommandDrivenTrainer(FakeTrainerAdapter(), workspace=td, job_id="cmd")
        evaluator = CommandDrivenEvaluator(FakeValidator(), config={})
        pipe = CanonicalPipeline(algo, trainer, evaluator, mode="command")

        result = pipe.run(dataset_uri=str(csv_path), output_dir=td / "out", job_id="cmd")
        assert result["status"] == "COMPLETED", result
        # mixed_uri points at the serialized command plan, not real data
        assert Path(result["stages"]["mixing"]["mixed_uri"]).exists()
        assert result["stages"]["training"].get("status") == "planned"
        print("PASS command/bridge:", json.dumps(result["stages"]["mixing"], ensure_ascii=False))


if __name__ == "__main__":
    test_reference_inprocess()
    test_command_bridge_captures_plans()
    print("\nAll canonical pipeline smoke tests passed.")
