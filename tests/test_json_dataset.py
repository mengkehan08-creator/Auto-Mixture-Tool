"""JSON in / JSON out: the dataset contract honours JSON on both ends.

Run offline (stdlib only):

    PYTHONPATH="src;<pyyaml-site-packages>" python tests/test_json_dataset.py
"""

import json
import tempfile
from pathlib import Path

from auto_mixture_tool.core import (
    CanonicalPipeline,
    ManualRatioMixingAlgorithm,
    NoOpTrainer,
    StubEvaluator,
    load_dataset,
)


def _make_json_array(tmp: Path) -> Path:
    p = tmp / "corpus.json"
    rows = [
        {"text": "The cat sat on the mat.", "domain": "web"},
        {"text": "A friendly dog barked at the moon.", "domain": "web"},
        {"text": "The sun rose over the hills.", "domain": "web"},
        {"text": "She drank a cup of warm tea.", "domain": "web"},
        {"text": "Photosynthesis converts light to energy.", "domain": "science"},
        {"text": "Mitochondria produce cellular ATP.", "domain": "science"},
        {"text": "def add(a, b): return a + b", "domain": "code"},
        {"text": "for i in range(10): print(i)", "domain": "code"},
    ]
    p.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def test_json_array_input() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ds = load_dataset(str(_make_json_array(tmp)))
        assert ds.size == 8, ds.size
        assert ds.domains() == ["web", "science", "code"], ds.domains()
        # metadata passthrough / text column mapping works
        texts = [s.text for s in ds]
        assert "The cat sat on the mat." in texts
    print("[PASS] test_json_array_input")


def test_json_wrapped_input() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        p = tmp / "wrapped.json"
        p.write_text(
            json.dumps({"samples": [{"text": "x", "domain": "web"}, {"text": "y", "domain": "code"}]}),
            encoding="utf-8",
        )
        ds = load_dataset(str(p))
        assert ds.size == 2, ds.size
        assert ds.domains() == ["web", "code"]
    print("[PASS] test_json_wrapped_input")


def test_pipeline_json_output_default() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        algo = ManualRatioMixingAlgorithm(
            domain_ratios={"web": 0.5, "science": 0.25, "code": 0.25}, seed=7
        )
        pipe = CanonicalPipeline(
            algorithm=algo, trainer=NoOpTrainer(), evaluator=StubEvaluator()
        )  # output_format defaults to "json"
        result = pipe.run(
            dataset_uri=str(_make_json_array(tmp)),
            output_dir=tmp / "out",
            job_id="json-out",
        )
        assert result["status"] == "COMPLETED", result
        out = Path(result["stages"]["mixing"]["mixed_uri"])
        assert out.exists()
        assert out.suffix == ".json"
        # Output dataset is a JSON array, parseable by json.load.
        written = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(written, list) and len(written) == 8, len(written)
        counts = {}
        for row in written:
            counts[row["domain"]] = counts.get(row["domain"], 0) + 1
        assert counts == {"web": 4, "science": 2, "code": 2}, counts
    print("[PASS] test_pipeline_json_output_default ->", counts)


def test_pipeline_jsonl_output_option() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        algo = ManualRatioMixingAlgorithm(
            domain_ratios={"web": 0.5, "science": 0.25, "code": 0.25}, seed=7
        )
        pipe = CanonicalPipeline(
            algorithm=algo,
            trainer=NoOpTrainer(),
            evaluator=StubEvaluator(),
            output_format="jsonl",
        )
        result = pipe.run(
            dataset_uri=str(_make_json_array(tmp)),
            output_dir=tmp / "out",
            job_id="jsonl-out",
        )
        out = Path(result["stages"]["mixing"]["mixed_uri"])
        assert out.suffix == ".jsonl"
        lines = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
        assert len(lines) == 8
    print("[PASS] test_pipeline_jsonl_output_option")


if __name__ == "__main__":
    test_json_array_input()
    test_json_wrapped_input()
    test_pipeline_json_output_default()
    test_pipeline_jsonl_output_option()
    print("ALL JSON DATASET TESTS PASSED")
