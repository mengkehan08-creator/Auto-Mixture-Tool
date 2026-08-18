from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from quadmix.data.dataset_schema import DatasetSchema


SUPPORTED_SUFFIXES = {".parquet", ".csv", ".jsonl", ".json", ".txt"}


def _first_data_file(path: Path) -> Path:
    if path.is_file():
        return path
    if not path.is_dir():
        raise ValueError(f"dataset path does not exist: {path}")
    files = sorted(p for p in path.rglob("*") if p.suffix.lower() in SUPPORTED_SUFFIXES)
    if not files:
        raise ValueError(f"no supported data files found under: {path}")
    return files[0]


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
    if suffix in {".jsonl", ".json"}:
        with path.open("r", encoding="utf-8") as handle:
            if suffix == ".json":
                value = json.load(handle)
                values = value if isinstance(value, list) else value.get("data", [])
                rows = [row for row in values[:limit] if isinstance(row, dict)]
            else:
                rows = []
                for _, line in zip(range(limit), handle):
                    value = json.loads(line)
                    if isinstance(value, dict):
                        rows.append(value)
        columns = sorted({key for row in rows for key in row})
        return rows, _infer_types(rows, columns), None
    rows = [{"text": line.rstrip("\n")} for _, line in zip(range(limit), path.open("r", encoding="utf-8"))]
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
    source = _first_data_file(Path(dataset_path).expanduser().resolve())
    schema_file = Path(schema_path).expanduser().resolve()
    schema = DatasetSchema.from_yaml(str(schema_file))
    rows, dtypes, total_rows = _read_sample(source, max(1, min(sample_size, 1000)))
    columns = list(dtypes)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        schema._validate(columns, dtypes)
    except ValueError as exc:
        errors.append(str(exc))

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
        "inspected_file": str(source),
        "schema_path": str(schema_file),
        "format": source.suffix.lower().lstrip("."),
        "sampled_rows": len(rows),
        "total_rows": total_rows,
        "columns": dtypes,
        "errors": errors,
        "warnings": warnings,
    }
