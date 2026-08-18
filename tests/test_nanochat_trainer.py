"""Phase 2-3 smoke test: NanoChatTrainer contract (offline).

Real NanoChat training needs nanochat + NPU, so it cannot execute offline.
These tests verify the contract, the resolved command/env (dry_run), and
registration -- proving the canonical ``Trainer`` integration point is wired.
"""

from __future__ import annotations

from quadmix_platform.interfaces import Trainer, UnifiedDataset
from auto_mixture_tool.core import (
    NanoChatTrainer,
    build_canonical_registry,
    get_trainer,
)


def _dummy_dataset():
    from auto_mixture_tool.core.dataset import CsvJsonlDataset

    ds = CsvJsonlDataset.__new__(CsvJsonlDataset)
    ds.path = __file__
    ds.schema = None

    class _S:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    ds._samples = [
        _S(id="0", text="the cat sat", domain="web", metadata={"q": 0.9}),
        _S(id="1", text="mitochondria atp", domain="science", metadata={"q": 0.8}),
    ]
    return ds


def test_nanochat_trainer_contract() -> None:
    t = NanoChatTrainer()
    assert isinstance(t, Trainer)
    assert t.id == "nanochat-core"
    print("[PASS] nanochat_trainer_contract")


def test_nanochat_dry_run_command() -> None:
    t = NanoChatTrainer(use_stem=True, dry_run=True, base_model_tag="d28")
    result = t.train(_dummy_dataset(), "/tmp/nanochat_out_dry")
    assert result["status"] == "planned"
    assert result["command"][0] == "bash"
    assert result["command"][1].endswith("run_stem_experiment.sh")
    assert result["env"]["BASE_MODEL_TAG"] == "d28"
    assert "QUADMIX_SAMPLED_DATA" in result["env"]
    print("[PASS] nanochat_dry_run_command ->", result["command"][1])


def test_nanochat_registered() -> None:
    reg = build_canonical_registry()
    ids = [c["id"] for c in reg["trainers"].catalog()]
    assert "nanochat-core" in ids
    assert get_trainer("nanochat-core").id == "nanochat-core"
    print("[PASS] nanochat_registered ->", ids)


if __name__ == "__main__":
    test_nanochat_trainer_contract()
    test_nanochat_dry_run_command()
    test_nanochat_registered()
    print("ALL PHASE-2-3 SMOKE TESTS PASSED")
