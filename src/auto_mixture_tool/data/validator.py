"""Enhanced dataset validator for Auto-Mixture-Tool.

Extends the quick inspector in ``quadmix_platform.dataset_inspector`` with
sample-level statistics that matter for mixing algorithms: token/character
length distributions, near-duplicate rates, and quality-score health.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median, pstdev
from typing import Any

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
    if not texts:
        return {"mean": 0.0, "std": 0.0, "min": 0, "max": 0, "median": 0.0, "p95": 0.0, "empty": 0}
    lengths = [len(t) for t in texts]
    return {
        "mean": round(sum(lengths) / len(lengths), 2),
        "std": round(pstdev(lengths), 2),
        "min": min(lengths),
        "max": max(lengths),
        "median": round(float(median(lengths)), 2),
        "p95": round(_percentile(lengths, 0.95), 2),
        "empty": lengths.count(0),
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
        result[col] = {
            "mean": round(sum(values) / len(values), 4),
            "std": round(pstdev(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "missing": sum(row.get(col) in (None, "") for row in rows),
        }
    return result


def _percentile(values: list[int | float], fraction: float) -> float:
    """Return a linearly interpolated percentile without a NumPy dependency."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


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
    format_validator: Any | None = None,
    dataset_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the base inspector plus extended statistics and a format check.

    The format check is a **swappable** module (``FormatValidatorAdapter``) that
    verifies the dataset matches a specific format standard — by default the
    QuadMix format (required columns, non-empty & expected domain labels,
    numeric quality columns, non-empty text).

    Returns a dict with ``valid``, ``errors``, ``warnings``, ``base`` (the
    original inspector output), ``statistics``, and ``format_check``.
    """
    dataset_config = dataset_config or {}
    shard_start = dataset_config.get("shard_start")
    shard_end = dataset_config.get("shard_end")
    base = _base_inspect(
        dataset_path, schema_path, sample_size, shard_start, shard_end
    )
    schema = DatasetSchema.from_yaml(str(Path(schema_path).expanduser().resolve()))

    # Re-read the sample as plain rows for extended stats.
    from quadmix_platform.dataset_inspector import _adapt_sample, _data_files, _read_sample
    sources = _data_files(
        Path(dataset_path).expanduser().resolve(), shard_start, shard_end
    )
    limit = max(1, min(sample_size, 10000))
    per_file_limit = max(1, (limit + len(sources) - 1) // len(sources))
    rows: list[dict[str, Any]] = []
    for source in sources:
        file_rows, _, _ = _read_sample(source, per_file_limit)
        file_rows, _, _ = _adapt_sample(file_rows, schema)
        rows.extend(file_rows)
    rows = rows[:limit]

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
            f"exact duplicate rate is {stats.duplicate_rate:.1%}; consider deduplication"
        )
    if len(stats.domain_distribution) == 1:
        base["warnings"].append(
            "only one domain detected; domain-balanced mixing will be a no-op"
        )

    # Swappable data-format conformance check.
    if format_validator is None:
        from auto_mixture_tool.plugins.format_validators.quadmix import QuadMixFormatValidator

        format_validator = QuadMixFormatValidator()
    try:
        format_check = format_validator.validate(
            {
                "dataset_uri": dataset_path,
                "schema_uri": schema_path,
                "sample_size": sample_size,
                "dataset_config": dataset_config,
            }
        )
    except Exception as exc:  # noqa: BLE001 - never let format check crash validation
        format_check = {
            "valid": False,
            "errors": [f"dataset validator '{getattr(format_validator, 'id', 'unknown')}' 执行失败: {exc}"],
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


def audit_dataset(
    dataset_path: str,
    schema_path: str,
    dataset_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Scan every native shard and report algorithm compatibility/filtering.

    Unlike the sample-based preflight validator, this function reads every
    record. It does not rewrite source data or create a converted copy.
    """
    from quadmix.data.shard_io import is_json_shard, read_shard_metadata
    from quadmix_platform.dataset_inspector import _data_files

    schema = DatasetSchema.from_yaml(str(Path(schema_path).expanduser().resolve()))
    dataset_config = dataset_config or {}
    sources = _data_files(
        Path(dataset_path).expanduser().resolve(),
        dataset_config.get("shard_start"),
        dataset_config.get("shard_end"),
    )
    scanned = accepted = rejected = 0
    reasons: dict[str, int] = {}
    errors: list[str] = []
    per_file: dict[str, Any] = {}
    domain_counts = [0] * len(schema.domain_names or [])

    for source in sources:
        if source.suffix.lower() != ".parquet" and not is_json_shard(str(source)):
            errors.append(f"{source}: unsupported native QuadMix input")
            continue
        try:
            result = read_shard_metadata(str(source), schema)
        except Exception as exc:  # noqa: BLE001 - retain errors for all shards
            errors.append(f"{source}: {exc}")
            continue
        report = result.get("filter_report", {
            "scanned": result["num_docs"],
            "accepted": result["num_docs"],
            "rejected": 0,
            "reasons": {},
        })
        per_file[str(source)] = report
        scanned += int(report["scanned"])
        accepted += int(report["accepted"])
        rejected += int(report["rejected"])
        for reason, count in report.get("reasons", {}).items():
            reasons[reason] = reasons.get(reason, 0) + int(count)
        if domain_counts:
            for value in result["domain"].tolist():
                if 0 <= int(value) < len(domain_counts):
                    domain_counts[int(value)] += 1

    named_domain_counts = {
        name: domain_counts[index]
        for index, name in enumerate(schema.domain_names or [])
    }
    missing_domains = [name for name, count in named_domain_counts.items() if count == 0]
    if accepted == 0:
        errors.append("no records remain after applying dataset filters")
    if missing_domains:
        errors.append(f"required domains have no accepted records: {missing_domains}")
    return {
        "valid": not errors,
        "algorithm_compatible": not errors,
        "scanned": scanned,
        "accepted": accepted,
        "rejected": rejected,
        "acceptance_rate": accepted / max(1, scanned),
        "rejection_reasons": dict(sorted(reasons.items())),
        "domain_distribution": named_domain_counts,
        "missing_domains": missing_domains,
        "errors": errors,
        "per_file": per_file,
        "source_unchanged": True,
    }
