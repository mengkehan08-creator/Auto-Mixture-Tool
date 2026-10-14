"""Phase 2-4 smoke test: STEMEvaluator contract (offline).

Real STEM benchmark evaluation needs the checkpoint + validation data + nanochat
harness, so it cannot execute offline. These tests verify the contract, the
resolved command/env (dry_run), and registration.
"""

from __future__ import annotations

from quadmix_platform.interfaces import Evaluator
from auto_mixture_tool.core import (
    STEMEvaluator,
    build_canonical_registry,
    get_evaluator,
)


def test_stem_evaluator_contract() -> None:
    ev = STEMEvaluator()
    assert isinstance(ev, Evaluator)
    assert ev.id == "stem-core"
    print("[PASS] stem_evaluator_contract")


def test_stem_dry_run_command() -> None:
    ev = STEMEvaluator(tasks=["algebra", "geometry"], validation_data_uri="/data/stem",
                       nanochat_repo="/repo/nanochat", dry_run=True)
    result = ev.evaluate({"checkpoint_uri": "/ckpt/d28_mid"})
    assert isinstance(result, dict)
    assert ev.last_plan is not None
    assert "python" in ev.last_plan["command"][0].lower()
    assert ev.last_plan["command"][-2] == "--experiment-script"
    assert ev.last_plan["env"]["STEM_TASKS"] == "algebra,geometry"
    assert ev.last_plan["env"]["STEM_VALIDATION_DATA"] == "/data/stem"
    assert ev.last_plan["env"]["NANOCHAT_REPO"] == "/repo/nanochat"
    print("[PASS] stem_dry_run_command ->", ev.last_plan["command"][-1])


def test_stem_registered() -> None:
    reg = build_canonical_registry()
    ids = [c["id"] for c in reg["evaluators"].catalog()]
    assert "stem-core" in ids
    assert get_evaluator("stem-core").id == "stem-core"
    print("[PASS] stem_registered ->", ids)


if __name__ == "__main__":
    test_stem_evaluator_contract()
    test_stem_dry_run_command()
    test_stem_registered()
    print("ALL PHASE-2-4 SMOKE TESTS PASSED")
