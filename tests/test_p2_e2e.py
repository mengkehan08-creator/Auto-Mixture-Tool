"""Phase 2 end-to-end smoke test (offline).

Wires the real canonical components through ``CanonicalPipeline``:
  ManualRatioMixingAlgorithm (real, in-process selection)
  + NanoChatTrainer (dry-run launcher)
  + STEMEvaluator (dry-run launcher)

This exercises the full 9-layer flow with the *actual* Phase-2 subclasses
(algorithm runs for real; trainer/evaluator are launchers verified offline
via dry_run). Proves the object-level pluggability end to end.
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from auto_mixture_tool.core import (
    CanonicalPipeline,
    ManualRatioMixingAlgorithm,
    NanoChatTrainer,
    STEMEvaluator,
    load_dataset,
)


def _make_csv(tmp: Path) -> Path:
    p = tmp / "corpus.csv"
    rows = [
        ("The cat sat on the mat.", "web"),
        ("A friendly dog barked at the moon.", "web"),
        ("The sun rose over the hills.", "web"),
        ("She drank a cup of warm tea.", "web"),
        ("Photosynthesis converts light to energy.", "science"),
        ("Mitochondria produce cellular ATP.", "science"),
        ("def add(a, b): return a + b", "code"),
        ("for i in range(10): print(i)", "code"),
    ]
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["text", "domain"])
        for text, domain in rows:
            w.writerow([text, domain])
    return p


def test_p2_e2e_manual_nanochat_stem() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        csv_path = _make_csv(tmp)

        pipeline = CanonicalPipeline(
            algorithm=ManualRatioMixingAlgorithm(
                domain_ratios={"web": 0.5, "science": 0.25, "code": 0.25}, seed=7
            ),
            trainer=NanoChatTrainer(dry_run=True, base_model_tag="d28"),
            evaluator=STEMEvaluator(tasks=["algebra"], dry_run=True),
            mode="inprocess",
        )
        result = pipeline.run(
            dataset_uri=str(csv_path),
            output_dir=tmp / "out",
            job_id="p2-e2e",
        )

        assert result["status"] == "PLANNED", result
        assert result["components"]["algorithm"] == "manual-core"
        assert result["components"]["trainer"] == "nanochat-core"
        assert result["components"]["evaluator"] == "stem-core"
        # Real selection happened.
        assert result["stages"]["mixing"]["selected_size"] == 8
        mixed = Path(result["stages"]["mixing"]["mixed_uri"])
        assert mixed.exists()
        # Trainer/evaluator launchers recorded their plans.
        assert result["stages"]["training"]["status"] == "planned"
        assert result["stages"]["evaluation"] == {}
        print("[PASS] p2_e2e_manual_nanochat_stem -> components", result["components"])


if __name__ == "__main__":
    test_p2_e2e_manual_nanochat_stem()
    print("ALL PHASE-2 E2E SMOKE TESTS PASSED")
