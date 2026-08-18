"""Phase 2 smoke test: real ManualRatio mixing through the canonical pipeline.

Pure standard library -- runs offline (no numpy / pandas needed).
"""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

from auto_mixture_tool.core import (
    CanonicalPipeline,
    ManualRatioMixingAlgorithm,
    NoOpTrainer,
    StubEvaluator,
    build_canonical_registry,
    get_algorithm,
    get_evaluator,
    get_trainer,
    load_dataset,
)


def _make_csv(tmp: Path) -> Path:
    p = tmp / "corpus.csv"
    # 8 rows: 4 web, 2 science, 2 code (no history) so the 0.5/0.25/0.25 split
    # is fully satisfiable and the expected selected counts are exact.
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


def test_manual_ratio_in_process() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        csv_path = _make_csv(tmp)

        algo = ManualRatioMixingAlgorithm(
            domain_ratios={"web": 0.5, "science": 0.25, "code": 0.25},
            seed=7,
        )
        pipeline = CanonicalPipeline(
            algorithm=algo, trainer=NoOpTrainer(), evaluator=StubEvaluator(), mode="inprocess"
        )
        result = pipeline.run(
            dataset_uri=str(csv_path),
            output_dir=tmp / "out",
            job_id="manual-smoke",
        )

        assert result["status"] == "COMPLETED", result
        # 0.5/0.25/0.25 of 8 -> 4 web, 2 science, 2 code
        assert result["stages"]["mixing"]["selected_size"] == 8
        out_json = Path(result["stages"]["mixing"]["mixed_uri"])
        assert out_json.exists()
        # default output format is JSON (array of records)
        assert out_json.suffix == ".json"
        written = json.loads(out_json.read_text(encoding="utf-8"))
        counts: dict[str, int] = {}
        for row in written:
            counts[row["domain"]] = counts.get(row["domain"], 0) + 1
        assert counts == {"web": 4, "science": 2, "code": 2}, counts
        assert "history" not in counts
        print("[PASS] manual_ratio_in_process ->", counts)


def test_manual_rejects_unknown_domain() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        csv_path = _make_csv(tmp)
        algo = ManualRatioMixingAlgorithm(domain_ratios={"web": 1.0, "nope": 0.0})
        try:
            algo.fit(load_dataset(str(csv_path)))
        except ValueError:
            print("[PASS] manual_rejects_unknown_domain")
            return
    raise AssertionError("expected ValueError for unknown domain")


def test_canonical_registry_and_from_config() -> None:
    reg = build_canonical_registry()
    assert [c["id"] for c in reg["algorithms"].catalog()] == [
        "random-core", "manual-core", "quadmix-core"
    ]
    assert get_algorithm("manual-core").id == "manual-core"
    assert get_trainer("none-core").id == "none-core"
    assert get_evaluator("stub-core").id == "stub-core"

    pipeline = CanonicalPipeline.from_config(
        algorithm_id="random-core", trainer_id="none-core", evaluator_id="stub-core"
    )
    assert pipeline.algorithm.id == "random-core"
    assert pipeline.trainer.id == "none-core"
    assert pipeline.evaluator.id == "stub-core"
    print("[PASS] canonical_registry_and_from_config")


if __name__ == "__main__":
    test_manual_ratio_in_process()
    test_manual_rejects_unknown_domain()
    test_canonical_registry_and_from_config()
    print("ALL PHASE-2-1 SMOKE TESTS PASSED")
