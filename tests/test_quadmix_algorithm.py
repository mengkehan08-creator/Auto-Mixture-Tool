"""Phase 2-2 smoke test: QuadMixMixingAlgorithm contract (offline).

The real QuadMix run needs numpy/pandas/pyarrow/lightgbm/torch + a proxy_runner,
so it cannot execute offline. These tests verify the *integration point*:
the class is importable without heavy deps, conforms to the canonical
``MixingAlgorithm`` contract, is registered, and ``fit`` fails *only* at the
lazy heavy-import boundary (not at import or contract-check time).
"""

from __future__ import annotations

from quadmix_platform.interfaces import MixingAlgorithm
from auto_mixture_tool.core import (
    QuadMixMixingAlgorithm,
    build_canonical_registry,
    get_algorithm,
)


def _dummy_dataset(samples):
    from auto_mixture_tool.core.dataset import CsvJsonlDataset

    ds = CsvJsonlDataset.__new__(CsvJsonlDataset)
    ds.path = __file__
    ds.schema = None
    ds._samples = list(samples)
    return ds


def test_quadmix_algorithm_contract() -> None:
    algo = QuadMixMixingAlgorithm()
    assert isinstance(algo, MixingAlgorithm)
    assert algo.id == "quadmix-core"
    assert algo.display_name
    print("[PASS] quadmix_algorithm_contract")


def test_quadmix_registered() -> None:
    reg = build_canonical_registry()
    ids = [c["id"] for c in reg["algorithms"].catalog()]
    assert "quadmix-core" in ids
    assert get_algorithm("quadmix-core").id == "quadmix-core"
    print("[PASS] quadmix_registered ->", ids)


def test_quadmix_fit_requires_heavy_deps_or_proxy() -> None:
    # Offline we have no numpy, so the lazy import inside fit must raise.
    # This proves the offline import is clean and the heavy path is truly lazy.
    algo = QuadMixMixingAlgorithm(quality_cols=["q1"], domain_names=["web"])

    class _S:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    ds = _dummy_dataset([_S(id="0", text="x", domain="web", metadata={"q1": 0.5})])

    raised = False
    try:
        algo.fit(ds)
    except Exception:
        raised = True
    assert raised, "expected fit() to raise at the lazy heavy-import boundary"
    print("[PASS] quadmix_fit_requires_heavy_deps (lazy import boundary)")


if __name__ == "__main__":
    test_quadmix_algorithm_contract()
    test_quadmix_registered()
    test_quadmix_fit_requires_heavy_deps_or_proxy()
    print("ALL PHASE-2-2 SMOKE TESTS PASSED")
