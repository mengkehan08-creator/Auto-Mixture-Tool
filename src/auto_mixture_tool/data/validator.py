"""Enhanced dataset validator for Auto-Mixture-Tool.

Extends the quick inspector in ``quadmix_platform.dataset_inspector`` with
sample-level statistics that matter for mixing algorithms: token/character
length distributions, near-duplicate rates, and quality-score health.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from quadmix.data.dataset_schema import DatasetSchema
from quadmix_platform.dataset_inspector import inspect_dataset as _base_inspect


@dataclass
class ValidationStatistics:
    num_rows_sampled: int = 0
    num_rows_total: int | None = None
    text_char_lengths: dict[str, Any] = field(default_factory=dict)
    duplicate_rate: float | None = None
    quality_score_stats: dict[str, dict[str, float]] = field(default_factory=dict)
    domain_distribution: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _character_length_stats(texts: list[str]) -> dict[str, Any]:
    lengths = [len(t) for t in texts]
    arr = np.array(lengths, dtype=np.float64)
    return {
        "mean": round(float(arr.mean()), 2),
        "std": round(float(arr.std()), 2),
        "min": int(arr.min()),
        "max": int(arr.max()),
        "median": round(float(np.median(arr)), 2),
        "p95": round(float(np.percentile(arr, 95)), 2),
        "empty": int((arr == 0).sum()),
    }


def _duplicate_rate(rows: list[dict[str, Any]], text_col: str) -> float:
    texts = [str(row.get(text_col, "")).strip() for row in rows]
    total = len(texts)
    if total < 2:
        return 0.0
    unique = len(set(texts))
    return round((total - unique) / total, 4)


def _quality_stats(rows: list[dict[str, Any]], quality_cols: list[str]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for col in quality_cols:
        values = []
        for row in rows:
            v = row.get(col)
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                continue
        if not values:
            continue
        arr = np.array(values, dtype=np.float64)
        result[col] = {
            "mean": round(float(arr.mean()), 4),
            "std": round(float(arr.std()), 4),
            "min": round(float(arr.min()), 4),
            "max": round(float(arr.max()), 4),
            "missing": sum(row.get(col) in (None, "") for row in rows),
        }
    return result


def _domain_distribution(rows: list[dict[str, Any]], domain_col: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(domain_col)
        key = str(value) if value is not None else "__null__"
        counts[key] = counts.get(key, 0) + 1
    return counts


def validate_dataset(
    dataset_path: str,
    schema_path: str,
    sample_size: int = 1000,
    format_validator_id: str = "quadmix",
) -> dict[str, Any]:
    """Run the base inspector plus extended statistics and a format check.

    The format check is a **swappable** module (``FormatValidatorAdapter``) that
    verifies the dataset matches a specific format standard — by default the
    QuadMix format (required columns, non-empty & expected domain labels,
    numeric quality columns, non-empty text).

    Returns a dict with ``valid``, ``errors``, ``warnings``, ``base`` (the
    original inspector output), ``statistics``, and ``format_check``.
    """
    base = _base_inspect(dataset_path, schema_path, sample_size)
    schema = DatasetSchema.from_yaml(str(Path(schema_path).expanduser().resolve()))

    # Re-read the sample as plain rows for extended stats.
    from quadmix_platform.dataset_inspector import _first_data_file, _read_sample
    source = _first_data_file(Path(dataset_path).expanduser().resolve())
    rows, _, _ = _read_sample(source, max(1, min(sample_size, 10000)))

    stats = ValidationStatistics(
        num_rows_sampled=len(rows),
        num_rows_total=base.get("total_rows"),
    )

    texts = [str(row.get(schema.text_col, "")) for row in rows]
    stats.text_char_lengths = _character_length_stats(texts)
    stats.duplicate_rate = _duplicate_rate(rows, schema.text_col)
    stats.quality_score_stats = _quality_stats(rows, schema.quality_cols)
    stats.domain_distribution = _domain_distribution(rows, schema.domain_col)

    # Additional warnings based on statistics.
    if stats.text_char_lengths.get("empty", 0) > 0:
        base["warnings"].append(
            f"{stats.text_char_lengths['empty']} sampled rows have empty text"
        )
    if stats.duplicate_rate and stats.duplicate_rate > 0.1:
        base["warnings"].append(
            f"near-duplicate rate is {stats.duplicate_rate:.1%}; consider deduplication"
        )
    if len(stats.domain_distribution) == 1:
        base["warnings"].append(
            "only one domain detected; domain-balanced mixing will be a no-op"
        )

    # Swappable data-format conformance check.
    from auto_mixture_tool.plugins.format_validators import get_format_validator
    try:
        format_validator = get_format_validator(format_validator_id)
        format_check = format_validator.validate(
            {"dataset_uri": dataset_path, "schema_uri": schema_path, "sample_size": sample_size}
        )
    except Exception as exc:  # noqa: BLE001 - never let format check crash validation
        format_check = {
            "valid": False,
            "errors": [f"format validator '{format_validator_id}' 执行失败: {exc}"],
            "warnings": [],
            "details": {},
        }

    base_errors = list(base.get("errors", []))
    base_warnings = list(base.get("warnings", []))
    fmt_errors = list(format_check.get("errors", []))
    fmt_warnings = list(format_check.get("warnings", []))

    # De-duplicate identical messages across the two layers.
    errors = sorted(set(base_errors) | set(fmt_errors))
    warnings = sorted(set(base_warnings) | set(fmt_warnings))
    valid = base["valid"] and format_check.get("valid", True) and not errors

    stats.warnings = warnings
    return {
        "valid": valid,
        "errors": errors,
        "warnings": warnings,
        "base": base,
        "statistics": stats.to_dict(),
        "format_check": format_check,
    }
