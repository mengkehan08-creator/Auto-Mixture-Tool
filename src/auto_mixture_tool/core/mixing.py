"""Layer 6: MixingAlgorithm implementations.

``RandomMixingAlgorithm`` is a *reference* in-process implementation proving the
interface works without touching QuadMix internals.

``CommandDrivenMixingAlgorithm`` is the Phase-1 bridge: it wraps an existing
``AlgorithmAdapter`` (e.g. ``QuadMixAlgorithm``) and adapts it to the canonical
``MixingAlgorithm`` contract by compiling it into a command plan. The real
selection happens when an ``ExecutorAdapter`` runs that plan on the cluster.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any

from quadmix_platform.interfaces import MixingAlgorithm, UnifiedDataset
from quadmix_platform.models import CommandSpec

from auto_mixture_tool.core.dataset import PlanDataset, write_samples


class RandomMixingAlgorithm(MixingAlgorithm):
    """Reference mixing algorithm: uniform random sampling baseline."""

    id = "random-core"
    display_name = "Random uniform mixing (reference)"

    def __init__(self, seed: int = 0, fraction: float = 1.0) -> None:
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("random-core fraction must be between 0 and 1")
        self.seed = seed
        self.fraction = fraction
        self._rng = random.Random(seed)
        self._selected: UnifiedDataset | None = None
        self._uri: str | None = None

    def fit(self, dataset: UnifiedDataset) -> None:
        self._rng = random.Random(self.seed)

    def select(self, dataset: UnifiedDataset) -> UnifiedDataset:
        n = dataset.size
        k = max(0, int(n * self.fraction))
        indices = self._rng.sample(range(n), k) if k < n else list(range(n))
        self._selected = dataset.subset(indices)
        return self._selected

    def export(self, output_dir: str | Path, fmt: str = "json") -> str:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ext = "jsonl" if fmt == "jsonl" else "json"
        uri = str(out / f"random_mixed.{ext}")
        samples = list(self._selected) if self._selected is not None else []
        write_samples(samples, uri, fmt=fmt)
        self._uri = uri
        return uri


class ManualRatioMixingAlgorithm(MixingAlgorithm):
    """In-process manual-ratio mixing.

    Unlike the command adapter (which shells out to
    ``scripts/platform/run_manual_ratio.py``), this implementation actually
    selects samples *from the in-memory* :class:`UnifiedDataset` according to
    fixed per-domain ratios -- proving the canonical contract works with a real
    selection, not just by emitting an external command.

    ``fit`` validates the requested domains; ``select`` allocates a count per
    domain proportional to ``domain_ratios`` and samples that many rows;
    ``export`` materializes the chosen subset to a JSON (default) or JSONL file.
    """

    id = "manual-core"
    display_name = "Manual ratio mixing (in-process)"

    def __init__(self, domain_ratios: dict[str, float] | None = None, seed: int = 42) -> None:
        self.domain_ratios = dict(domain_ratios or {})
        self.seed = seed
        self._selected: UnifiedDataset | None = None

    def fit(self, dataset: UnifiedDataset) -> None:
        if not self.domain_ratios:
            raise ValueError("manual-core requires non-empty domain_ratios")
        invalid = {
            domain: ratio for domain, ratio in self.domain_ratios.items()
            if not isinstance(ratio, (int, float)) or not math.isfinite(ratio) or ratio < 0
        }
        if invalid or sum(self.domain_ratios.values()) <= 0:
            raise ValueError(
                "manual-core domain_ratios must be finite, non-negative, and sum to > 0"
            )
        present = set(dataset.domains())
        unknown = [d for d in self.domain_ratios if d not in present]
        if unknown:
            raise ValueError(
                f"manual-core domain_ratios reference unknown domains: {unknown}; "
                f"available: {sorted(present)}"
            )

    def select(self, dataset: UnifiedDataset) -> UnifiedDataset:
        rnd = random.Random(self.seed)
        by_domain: dict[str, list[int]] = {}
        for i, sample in enumerate(dataset):
            by_domain.setdefault(sample.domain, []).append(i)

        total = sum(self.domain_ratios.values()) or 1.0
        n_total = dataset.size
        chosen: list[int] = []
        for domain, ratio in self.domain_ratios.items():
            pool = by_domain.get(domain, [])
            if not pool:
                continue
            k = int(round(ratio / total * n_total))
            k = max(0, min(k, len(pool)))
            chosen.extend(rnd.sample(pool, k) if k < len(pool) else pool)

        chosen.sort()
        self._selected = dataset.subset(chosen)
        return self._selected

    def export(self, output_dir: str | Path, fmt: str = "json") -> str:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ext = "jsonl" if fmt == "jsonl" else "json"
        uri = str(out / f"manual_mixed.{ext}")
        samples = list(self._selected) if self._selected is not None else []
        write_samples(samples, uri, fmt=fmt)
        return uri


class CommandDrivenMixingAlgorithm(MixingAlgorithm):
    """Bridge: adapt a command-emitting ``AlgorithmAdapter`` to this interface.

    The wrapped adapter's ``build()`` is called with a synthesized request to
    obtain the :class:`CommandSpec` plan. ``select`` returns a
    :class:`PlanDataset` carrying that plan (the data materializes at execution
    time); ``export`` writes the plan to disk and returns its URI.
    """

    def __init__(self, adapter: Any, workspace: str | Path, job_id: str = "local") -> None:
        self.adapter = adapter
        self.workspace = Path(workspace)
        self.job_id = job_id
        self.id = adapter.id
        self.display_name = getattr(adapter, "display_name", adapter.id)
        self._plan: list[CommandSpec] = []
        self._dataset_uri = ""

    def _request(self, dataset: UnifiedDataset) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "workspace": self.workspace,
            "dataset_uri": getattr(dataset, "path", "") or self._dataset_uri,
            "schema_uri": "",
            "output_uri": str(self.workspace / "result" / self.job_id / "quadmix"),
            "algorithm_config": {},
        }

    def fit(self, dataset: UnifiedDataset) -> None:
        self._dataset_uri = getattr(dataset, "path", "") or ""

    def select(self, dataset: UnifiedDataset) -> UnifiedDataset:
        self._plan = self.adapter.build(self._request(dataset), self.workspace)
        return PlanDataset(self._plan, getattr(dataset, "path", str(self._dataset_uri)))

    def export(self, output_dir: str | Path, fmt: str = "json") -> str:
        # Command-driven components emit a *plan* (consumed by the cluster
        # executor), not a materialized dataset; the fmt hint is ignored here.
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        uri = str(out / "mixing_plan.json")
        with open(uri, "w", encoding="utf-8") as f:
            json.dump([s.to_dict() for s in self._plan], f, indent=2, default=str)
        return uri
