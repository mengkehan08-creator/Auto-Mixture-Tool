"""Phase 2: QuadMix as a real in-process ``MixingAlgorithm``.

This is the canonical-contract implementation that *actually executes* the
QuadMix algorithm (``src/quadmix``) instead of merely emitting an external
command. It adapts the platform-agnostic :class:`UnifiedDataset` onto the
QuaDMix precomputed-input format and delegates the heavy lifting to
``quadmix.QuaDMixPipeline``.

Execution model (mirrors ``QuaDMixPipeline.run`` in precomputed mode):

* ``fit(dataset)``   -- spill the ``UnifiedDataset`` to a precomputed parquet
  (text / domain / quality columns), build the ``QuaDMixConfig`` +
  ``DatasetSchema``, and run the full pipeline (proxy experiments via the
  injected ``proxy_runner`` -> LightGBM regression -> optimal-parameter search
  -> final sampling). The resulting ``selected_indices`` are stored.
* ``select(dataset)`` -- return ``dataset.subset(selected_indices)``.
* ``export(output_dir)`` -- materialize the chosen subset to a JSONL file and
  write a ``quadmix_result.json`` summary.

All heavy dependencies (numpy / pandas / pyarrow / lightgbm / torch) are
imported *lazily inside* ``fit`` so this module is importable offline (the
standard-library reference path stays usable); the real run requires the
cluster runtime (``pip install -e .``) plus a ``proxy_runner``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quadmix_platform.interfaces import MixingAlgorithm, UnifiedDataset
from auto_mixture_tool.core.dataset import write_samples


class QuadMixMixingAlgorithm(MixingAlgorithm):
    """In-process QuadMix mixing algorithm (wraps ``src/quadmix``)."""

    id = "quadmix-core"
    display_name = "QuadMix (in-process, src/quadmix)"

    def __init__(
        self,
        *,
        domain_names: list[str] | None = None,
        quality_cols: list[str] | None = None,
        quality_names: list[str] | None = None,
        quality_directions: list[bool] | None = None,
        config: dict[str, Any] | None = None,
        seed: int = 42,
        proxy_runner: Any | None = None,
        text_col: str = "text",
        domain_col: str = "domain",
        output_format: str = "jsonl",
    ) -> None:
        self.domain_names = domain_names
        self.quality_cols = quality_cols
        self.quality_names = quality_names
        self.quality_directions = quality_directions
        self.config = dict(config or {})
        self.seed = seed
        self.proxy_runner = proxy_runner
        self.text_col = text_col
        self.domain_col = domain_col
        self.output_format = output_format

        self._selected_indices: list[int] | None = None
        self._samples: list[Any] | None = None
        self._domain_to_idx: dict[str, int] = {}
        self._pipeline_output: Any = None
        self._run_output_dir: str | None = None

    # ------------------------------------------------------------------ #
    def fit(self, dataset: UnifiedDataset) -> None:
        import tempfile

        # --- Resolve domain ordering ------------------------------------ #
        if self.domain_names:
            domain_names = list(self.domain_names)
        else:
            domain_names = list(dataset.domains())
        if not domain_names:
            raise ValueError("quadmix-core: dataset has no domains")
        self._domain_to_idx = {name: i for i, name in enumerate(domain_names)}

        # --- Resolve quality columns ------------------------------------ #
        quality_cols = self.quality_cols
        if not quality_cols:
            # Fall back to any numeric-looking metadata keys on the first sample.
            sample = next(iter(dataset), None)
            if sample is not None:
                quality_cols = [k for k, v in sample.metadata.items() if _looks_numeric(v)]
        if not quality_cols:
            raise ValueError(
                "quadmix-core requires quality_cols (numeric quality-score metadata "
                "columns) to run in precomputed mode. Pass quality_cols=... or ensure "
                "samples carry numeric quality metadata."
            )
        quality_names = self.quality_names or list(quality_cols)
        quality_directions = self.quality_directions or [True] * len(quality_cols)

        # --- Capture samples + build numpy-aligned arrays --------------- #
        samples = list(dataset)
        if not samples:
            raise ValueError("quadmix-core: empty dataset")
        texts: list[str] = []
        domain_labels: list[int] = []
        quality_rows: list[list[float]] = []
        for s in samples:
            texts.append(s.text)
            if s.domain not in self._domain_to_idx:
                raise ValueError(
                    f"quadmix-core: domain {s.domain!r} not in declared domain_names "
                    f"{domain_names}"
                )
            domain_labels.append(self._domain_to_idx[s.domain])
            row = []
            for col in quality_cols:
                if col not in s.metadata:
                    raise ValueError(f"quadmix-core: sample missing quality column {col!r}")
                row.append(float(s.metadata[col]))
            quality_rows.append(row)
        self._samples = samples

        # --- Lazy heavy imports (offline-safe) -------------------------- #
        import numpy as np
        import pyarrow as pa
        import pyarrow.parquet as pq
        from quadmix import DatasetSchema, QuaDMixConfig, QuaDMixPipeline

        # --- Spill to a precomputed parquet ----------------------------- #
        run_tmp = Path(tempfile.mkdtemp(prefix="quadmix_"))
        parquet_path = run_tmp / "precomputed.parquet"
        columns = {self.text_col: texts, self.domain_col: domain_labels}
        for i, col in enumerate(quality_cols):
            columns[col] = [r[i] for r in quality_rows]
        table = pa.table({k: pa.array(v) for k, v in columns.items()})
        pq.write_table(table, str(parquet_path))

        # --- Configure + run the real pipeline -------------------------- #
        config = QuaDMixConfig(
            num_domains=len(domain_names),
            num_quality_criteria=len(quality_cols),
            seed=self.seed,
            **self.config,
        )
        schema = DatasetSchema(
            domain_col=self.domain_col,
            quality_cols=list(quality_cols),
            quality_directions=list(quality_directions),
            text_col=self.text_col,
            domain_names=list(domain_names),
            quality_names=list(quality_names),
        )
        if self.proxy_runner is None:
            raise ValueError(
                "quadmix-core: a proxy_runner is required to run proxy experiments "
                "(train 1M-param models). Inject one, e.g. "
                "QuadMixMixingAlgorithm(proxy_runner=EssentialWebProxyRunner(...))."
            )

        pipeline = QuaDMixPipeline(config)
        run_output = run_tmp / "run_output"
        output = pipeline.run(
            data_path=str(parquet_path),
            schema=schema,
            output_dir=str(run_output),
            precomputed=True,
            output_format=self.output_format,
            domain_names=list(domain_names),
            quality_names=list(quality_names),
            quality_directions=list(quality_directions),
            proxy_runner=self.proxy_runner,
        )
        self._pipeline_output = output
        self._run_output_dir = str(run_output)
        self._selected_indices = [int(i) for i in output.selected_indices]

    # ------------------------------------------------------------------ #
    def select(self, dataset: UnifiedDataset) -> UnifiedDataset:
        if self._selected_indices is None:
            raise RuntimeError("quadmix-core.select() called before fit()")
        return dataset.subset(self._selected_indices)

    # ------------------------------------------------------------------ #
    def export(self, output_dir: str | Path, fmt: str = "json") -> str:
        if self._selected_indices is None or self._samples is None:
            raise RuntimeError("quadmix-core.export() called before fit()")
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        ext = "jsonl" if fmt == "jsonl" else "json"
        uri = str(out / f"quadmix_mixed.{ext}")
        write_samples(
            (self._samples[idx] for idx in self._selected_indices),
            uri,
            fmt=fmt,
        )

        # Companion summary drawn from the pipeline's structured output.
        summary = {
            "algorithm": self.id,
            "num_selected_docs": getattr(self._pipeline_output, "num_selected_docs", len(self._selected_indices)),
            "num_original_docs": getattr(self._pipeline_output, "num_original_docs", None),
            "domain_distribution_before": getattr(self._pipeline_output, "domain_distribution_before", None),
            "domain_distribution_after": getattr(self._pipeline_output, "domain_distribution_after", None),
            "search_lift": getattr(self._pipeline_output, "search_lift", None),
            "best_predicted_loss": getattr(self._pipeline_output, "best_predicted_loss", None),
        }
        (out / "quadmix_result.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        return uri


def _looks_numeric(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
