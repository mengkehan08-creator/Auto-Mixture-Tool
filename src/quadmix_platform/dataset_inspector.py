from __future__ import annotations

import csv
import math
from collections import Counter
from itertools import islice
from pathlib import Path
from typing import Any, Iterable

from quadmix.data.dataset_schema import DatasetSchema
from quadmix.data.shard_io import is_json_shard, iter_json_records
from quadmix.data.record_adapter import adapt_record


SUPPORTED_SUFFIXES = {
    ".parquet", ".csv", ".json", ".jsonl", ".jsonlines", ".ndjson", ".txt"
}
CONTROL_FILENAMES = {"manifest.json", "shard_index.json", "metadata_shard_info.json"}


def _data_files(path: Path) -> list[Path]:
    if path.is_file():
        if path.suffix.lower() not in SUPPORTED_SUFFIXES and not is_json_shard(str(path)):
            raise ValueError(f"unsupported dataset file: {path}")
        return [path]
    if not path.is_dir():
        raise ValueError(f"dataset path does not exist: {path}")
    files = sorted(
        p for p in path.rglob("*")
        if p.is_file() and (p.suffix.lower() in SUPPORTED_SUFFIXES or is_json_shard(str(p)))
        and p.name not in CONTROL_FILENAMES
    )
    if not files:
        raise ValueError(f"no supported data files found under: {path}")
    return files


def _first_data_file(path: Path) -> Path:
    """Compatibility helper; new validation checks every returned data file."""
    return _data_files(path)[0]


def _read_sample(path: Path, limit: int) -> tuple[list[dict[str, Any]], dict[str, str], int | None]:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(path)
        schema = parquet.schema_arrow
        columns = [field.name for field in schema]
        rows = parquet.read_row_group(0).slice(0, limit).to_pylist() if parquet.num_row_groups else []
        return rows, {field.name: str(field.type) for field in schema}, parquet.metadata.num_rows
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = [row for _, row in zip(range(limit), reader)]
            columns = reader.fieldnames or []
        return rows, _infer_types(rows, columns), None
    if suffix in {".json", ".jsonl", ".jsonlines", ".ndjson"} or is_json_shard(str(path)):
        rows = list(islice(iter_json_records(str(path)), limit))
        columns = sorted({key for row in rows for key in row})
        return rows, _infer_types(rows, columns), None
    with path.open("r", encoding="utf-8") as handle:
        rows = [
            {"text": line.rstrip("\n")}
            for _, line in zip(range(limit), handle)
        ]
    return rows, {"text": "string"}, None


def _infer_types(rows: list[dict[str, Any]], columns: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for column in columns:
        values = [row.get(column) for row in rows if row.get(column) not in (None, "")]
        if not values:
            result[column] = "unknown"
            continue
        if all(_is_int(value) for value in values):
            result[column] = "int64"
        elif all(_is_float(value) for value in values):
            result[column] = "float64"
        else:
            result[column] = "string"
    return result


def _adapt_sample(
    rows: list[dict[str, Any]], schema: DatasetSchema
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    for position, source_record in enumerate(rows):
        record, local_reasons = adapt_record(source_record, schema, position)
        if record is None or local_reasons:
            reasons.update(local_reasons or ["adapter_rejected"])
        else:
            accepted.append(record)
    columns = sorted({key for row in accepted for key in row})
    return accepted, _infer_types(accepted, columns), {
        "scanned": len(rows),
        "accepted": len(accepted),
        "rejected": len(rows) - len(accepted),
        "acceptance_rate": len(accepted) / max(1, len(rows)),
        "reasons": dict(sorted(reasons.items())),
    }


def _is_int(value: Any) -> bool:
    try:
        int(value)
        return str(value).strip() == str(int(value))
    except (TypeError, ValueError):
        return False


def _is_float(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def inspect_dataset(dataset_path: str, schema_path: str, sample_size: int = 100) -> dict[str, Any]:
    sources = _data_files(Path(dataset_path).expanduser().resolve())
    schema_file = Path(schema_path).expanduser().resolve()
    schema = DatasetSchema.from_yaml(str(schema_file))
    limit = max(1, min(sample_size, 10000))
    per_file_limit = max(1, math.ceil(limit / len(sources)))
    rows: list[dict[str, Any]] = []
    dtype_reports: list[dict[str, str]] = []
    totals: list[int | None] = []
    errors: list[str] = []
    warnings: list[str] = []
    filter_reports: dict[str, dict[str, Any]] = {}
    for source in sources:
        file_rows, _, total_rows = _read_sample(source, per_file_limit)
        file_rows, dtypes, filter_report = _adapt_sample(file_rows, schema)
        rows.extend(file_rows)
        dtype_reports.append(dtypes)
        totals.append(total_rows)
        filter_reports[str(source)] = filter_report
        if filter_report["rejected"]:
            warnings.append(
                f"{source.name}: sample filter accepted {filter_report['accepted']}/"
                f"{filter_report['scanned']}; reasons={filter_report['reasons']}"
            )
        try:
            schema._validate(list(dtypes), dtypes)
        except ValueError as exc:
            errors.append(f"{source.name}: {exc}")
    rows = rows[:limit]
    merged_dtypes: dict[str, str] = {}
    for report in dtype_reports:
        for column, dtype in report.items():
            previous = merged_dtypes.get(column)
            if previous is None:
                merged_dtypes[column] = dtype
            elif previous != dtype:
                merged_dtypes[column] = f"mixed({previous},{dtype})"
    total_rows = sum(value for value in totals if value is not None) if all(
        value is not None for value in totals
    ) else None

    if not rows:
        errors.append("dataset sample is empty")
    else:
        text_values = [row.get(schema.text_col) for row in rows]
        empty_text = sum(not isinstance(value, str) or not value.strip() for value in text_values)
        if empty_text:
            errors.append(f"{empty_text}/{len(rows)} sampled rows have empty or non-string text")
        for column in schema.quality_cols:
            invalid = sum(not _is_float(row.get(column)) for row in rows)
            if invalid:
                errors.append(f"{column}: {invalid}/{len(rows)} sampled values are not numeric")
        domains = {str(row.get(schema.domain_col)) for row in rows if row.get(schema.domain_col) not in (None, "")}
        if not domains:
            errors.append(f"domain column '{schema.domain_col}' has no values in sample")
        elif len(domains) == 1:
            warnings.append("only one domain appears in the sample; diversity optimization may be ineffective")
        if schema.domain_names:
            unknown = sorted(domains - set(map(str, schema.domain_names)))
            if unknown:
                errors.append(f"domain values not declared in domain_names: {unknown[:10]}")

    return {
        "valid": not errors,
        "dataset_path": str(Path(dataset_path).resolve()),
        "inspected_file": str(sources[0]),
        "inspected_files": [str(source) for source in sources],
        "schema_path": str(schema_file),
        "format": (
            "json" if is_json_shard(str(sources[0]))
            else sources[0].suffix.lower().lstrip(".")
        ),
        "sampled_rows": len(rows),
        "total_rows": total_rows,
        "columns": merged_dtypes,
        "filter_preview": filter_reports,
        "errors": errors,
        "warnings": warnings,
    }
