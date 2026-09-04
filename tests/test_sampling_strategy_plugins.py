from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from auto_mixture_tool.plugins.trainers.nanochat import NanoChatTrainer
from auto_mixture_tool.sampling import CandidatePool, StrategyContext, select_indices


ROOT = Path(__file__).resolve().parents[1]


def test_example_random_strategy_is_deterministic_and_valid() -> None:
    pool = CandidatePool(
        np.zeros(10, dtype=np.int64), np.arange(10), np.full(10, 10), np.zeros(10)
    )
    path = ROOT / "examples" / "strategies" / "random_length_aware.py"
    context = StrategyContext("random", 50, 7)
    first = select_indices(str(path), pool, context, {"bucket_size": 4})
    second = select_indices(str(path), pool, context, {"bucket_size": 4})
    assert first.tolist() == second.tolist()
    assert len(first) == 5


def test_nanochat_adapter_accepts_multiple_manual_plans() -> None:
    request = {
        "job_id": "abc123def456",
        "dataset_uri": "/data",
        "schema_uri": "/schema.yaml",
        "output_uri": "/output",
        "evaluator_id": "stem",
        "trainer_config": {},
        "comparison_config": {
            "methods": ["quadmix", "random", "manual"],
            "random_strategy": {"script_path": "/mnt/random.py", "config": {"x": 1}},
            "manual_plans": [
                {"id": "one", "ratios": {"math": 1}},
                {
                    "id": "two", "ratios": {"math": 0.4, "physics": 0.6},
                    "strategy": {"script_path": "/mnt/manual.py", "config": {"y": 2}},
                },
            ],
        },
    }
    spec = NanoChatTrainer().build(request, ROOT)[0]
    plans = json.loads(spec.env["MANUAL_PLANS_JSON"])
    assert [plan["id"] for plan in plans] == ["one", "two"]
    assert spec.env["RANDOM_STRATEGY_PATH"] == "/mnt/random.py"


def test_duplicate_manual_plan_ids_are_rejected() -> None:
    request = {
        "job_id": "abc123def456", "dataset_uri": "/data", "schema_uri": "/s",
        "comparison_config": {
            "methods": ["manual"],
            "manual_plans": [
                {"id": "same", "ratios": {"math": 1}},
                {"id": "same", "ratios": {"math": 1}},
            ],
        },
    }
    try:
        NanoChatTrainer().build(request, ROOT)
    except ValueError as exc:
        assert "duplicate manual plan id" in str(exc)
    else:
        raise AssertionError("duplicate plan id was accepted")
