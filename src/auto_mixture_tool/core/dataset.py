"""Layer 5: Unified Dataset Interface -- concrete implementations.

``CsvJsonlDataset`` maps any CSV / JSON / JSONL file onto the internal
:class:`Sample` shape using a :class:`DatasetSchema`, so mixing algorithms,
trainers and evaluators never see the raw column names again.

* CSV / JSONL / **JSON (array of records)** use only the standard library, so
  the contract can be exercised offline. A ``.json`` file may be a plain array
  ``[{"text": ...}, ...]`` or wrapped in a common key (``samples`` / ``data`` /
  ``records`` / ``examples`` / ``items``); a single object is treated as one row.
* Parquet requires ``pyarrow`` (available on the cluster runtime).

``write_samples`` materializes a :class:`UnifiedDataset` to disk as either a
JSON array (``fmt="json"``) or line-delimited JSON (``fmt="jsonl"``).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Iterator

from quadmix_platform.interfaces import Sample, UnifiedDataset


class CsvJsonlDataset(UnifiedDataset):
    """A :class:`UnifiedDataset` backed by a CSV / JSON / JSONL file."""

    def __init__(self, path: str | Path, schema: Any = None) -> None:
        self.path = Path(path)
        self.schema = schema
        self._samples: list[Sample] = []
        self._load()

    # -- loading ----------------------------------------------------------
    def _load(self) -> None:
        suffix = self.path.suffix.lower()
        if suffix == ".jsonl":
            rows = self._read_jsonl()
        elif suffix == ".json":
            rows = self._read_json_array()
        elif suffix == ".csv":
            rows = self._read_csv()
        else:
            raise ValueError(f"unsupported dataset file type: {self.path.suffix or '<none>'}")
        self._samples = [self._to_sample(i, row) for i, row in enumerate(rows)]

    def _read_csv(self) -> list[dict[str, Any]]:
        with open(self.path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def _read_jsonl(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        with open(self.path, encoding="utf-8") as f:
            for line_number, line in enumerate(f, 1):
                line = line.strip()
                if line:
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise ValueError(
                            f"{self.path.name}:{line_number}: JSONL record must be an object"
                        )
                    out.append(value)
        return out

    def _read_json_array(self) -> list[dict[str, Any]]:
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key in ("samples", "data", "records", "examples", "items"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                # A bare object -> treat as a single record.
                data = [data]
        if not isinstance(data, list):
            raise ValueError(
                f"{self.path.name}: expected a JSON array of records, "
                f"got {type(data).__name__}"
            )
        if not all(isinstance(row, dict) for row in data):
            raise ValueError(f"{self.path.name}: every JSON record must be an object")
        return data

    def _to_sample(self, idx: int, row: dict[str, str]) -> Sample:
        schema = self.schema
        text_col = getattr(schema, "text_col", "text") if schema else "text"
        domain_col = getattr(schema, "domain_col", "domain") if schema else "domain"
        text = str(row.get(text_col, "") or "")
        domain = str(row.get(domain_col, "") or "")
        metadata = {k: v for k, v in row.items() if k not in (text_col, domain_col)}
        return Sample(id=f"{self.path.name}#{idx}", text=text, domain=domain, metadata=metadata)

    # -- UnifiedDataset contract -----------------------------------------
    def __iter__(self) -> Iterator[Sample]:
        return iter(self._samples)

    def domains(self) -> list[str]:
        seen: list[str] = []
        for s in self._samples:
            if s.domain and s.domain not in seen:
                seen.append(s.domain)
        return seen

    @property
    def size(self) -> int:
        return len(self._samples)

    def subset(self, indices: list[int]) -> "CsvJsonlDataset":
        invalid = [index for index in indices if not 0 <= index < len(self._samples)]
        if invalid:
            raise IndexError(f"dataset subset indices out of range: {invalid[:10]}")
        clone = CsvJsonlDataset.__new__(CsvJsonlDataset)
        clone.path = self.path
        clone.schema = self.schema
        clone._samples = [self._samples[i] for i in indices]
        return clone


class PlanDataset(UnifiedDataset):
    """A lightweight stand-in returned by command-driven bridges.

    When a component runs as an *external command* (QuadMix / NanoChat / STEM
    on a cluster), the actual selected dataset only materializes after the
    :class:`ExecutorAdapter` runs the command. ``PlanDataset`` satisfies the
    :class:`UnifiedDataset` contract while carrying the compiled command plan
    so the pipeline can pass it downstream without executing anything yet.
    """

    def __init__(self, plan: list[Any], source_uri: str = "") -> None:
        self.plan = plan
        self.source_uri = source_uri
        self.schema = None

    def __iter__(self) -> Iterator[Sample]:
        return iter([])

    def domains(self) -> list[str]:
        return []

    @property
    def size(self) -> int:
        return 0

    def subset(self, indices: list[int]) -> "PlanDataset":
        return self


def load_dataset(path: str | Path, schema: Any = None) -> UnifiedDataset:
    """Factory: build a :class:`UnifiedDataset` from any supported source.

    CSV / JSON / JSONL use the stdlib implementation here (``CsvJsonlDataset``);
    Parquet is supported when ``pyarrow`` is installed (the cluster runtime),
    otherwise a clear error is raised pointing at the cluster-side loader.
    """
    suffix = str(path).lower()
    if suffix.endswith(".parquet"):
        try:
            import pyarrow.parquet as pq  # type: ignore
        except ImportError as exc:  # pragma: no cover - offline env
            raise RuntimeError(
                "Parquet input requires pyarrow, which is available on the "
                "cluster runtime (pip install -e .). For offline testing use "
                "CSV / JSON / JSONL inputs."
            ) from exc
        return _ParquetDataset(path, schema, pq)
    return CsvJsonlDataset(path, schema)


class _ParquetDataset(UnifiedDataset):
    """Minimal pyarrow-backed :class:`UnifiedDataset` (cluster runtime)."""

    def __init__(self, path: str | Path, schema: Any, pq) -> None:
        self.path = Path(path)
        self.schema = schema
        self._pq = pq
        self._table = pq.read_table(str(path))

    def __iter__(self) -> Iterator[Sample]:
        cols = {name: self._table.column(name).to_pylist() for name in self._table.column_names}
        n = self._table.num_rows
        text_col = getattr(self.schema, "text_col", "text") if self.schema else "text"
        domain_col = getattr(self.schema, "domain_col", "domain") if self.schema else "domain"
        for i in range(n):
            row = {k: cols[k][i] for k in cols}
            yield Sample(
                id=f"{self.path.name}#{i}",
                text=str(row.get(text_col, "") or ""),
                domain=str(row.get(domain_col, "") or ""),
                metadata={k: v for k, v in row.items() if k not in (text_col, domain_col)},
            )

    def domains(self) -> list[str]:
        seen: list[str] = []
        for s in self:
            if s.domain and s.domain not in seen:
                seen.append(s.domain)
        return seen

    @property
    def size(self) -> int:
        return self._table.num_rows

    def subset(self, indices: list[int]) -> "_ParquetDataset":
        clone = _ParquetDataset.__new__(_ParquetDataset)
        clone.path = self.path
        clone.schema = self.schema
        clone._pq = self._pq
        clone._table = self._table.take(indices)
        return clone


# ---------------------------------------------------------------------- #
# Output serialization helpers (Layers 6 / 8)
# ---------------------------------------------------------------------- #
def _sample_to_row(sample: Sample) -> dict[str, Any]:
    """Render a :class:`Sample` back into a flat record."""
    row: dict[str, Any] = {"id": sample.id, "text": sample.text, "domain": sample.domain}
    row.update(sample.metadata or {})
    return row


def write_samples(samples: Iterable[Sample], uri: str | Path, fmt: str = "json") -> str:
    """Materialize ``samples`` to disk.

    ``fmt="json"``  -> a single JSON array (the default, matching the
                       "output dataset is JSON" requirement).
    ``fmt="jsonl"`` -> one JSON object per line.

    Returns the written file URI.
    """
    uri = str(uri)
    Path(uri).parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        with open(uri, "w", encoding="utf-8") as f:
            json.dump(
                [_sample_to_row(s) for s in samples],
                f,
                ensure_ascii=False,
                indent=2,
            )
    elif fmt == "jsonl":
        with open(uri, "w", encoding="utf-8") as f:
            for s in samples:
                f.write(json.dumps(_sample_to_row(s), ensure_ascii=False) + "\n")
    else:
        raise ValueError(f"unsupported dataset fmt: {fmt!r} (use 'json' or 'jsonl')")
    return uri
