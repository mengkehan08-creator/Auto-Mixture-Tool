"""Per-record adapters for schema-driven native dataset ingestion."""

from __future__ import annotations

import re
from typing import Any

from quadmix.data.dataset_schema import DatasetSchema


def adapt_record(
    record: dict[str, Any], schema: DatasetSchema, position: int
) -> tuple[dict[str, Any] | None, list[str]]:
    """Return ``(adapted_record, rejection_reasons)`` for one source record."""
    adapter_id = schema.record_adapter
    if not adapter_id:
        return record, []
    if adapter_id == "stem-sample-json-v1":
        return _adapt_stem_sample(record, schema, position)
    raise ValueError(f"unknown record_adapter: {adapter_id}")


def _adapt_stem_sample(
    record: dict[str, Any], schema: DatasetSchema, position: int
) -> tuple[dict[str, Any] | None, list[str]]:
    config = schema.filter_config or {}
    reasons: list[str] = []
    text = record.get("text")
    if not isinstance(text, str) or not text.strip():
        return None, ["missing_or_empty_text"]

    evaluation = record.get("stem_quality_eval")
    if not isinstance(evaluation, dict):
        return None, ["missing_stem_quality_eval"]

    domain, domain_score = _derive_domain(record, evaluation)
    if domain is None:
        return None, ["unmapped_domain"]
    if schema.domain_names and domain not in schema.domain_names:
        return None, ["domain_not_declared"]

    quality_source = {
        "stem_relevance": evaluation.get("stem_relevance"),
        "knowledge_value": evaluation.get("knowledge_value"),
        "notation_fidelity": evaluation.get("notation_fidelity"),
        "rigor_coherence": evaluation.get("rigor_coherence"),
        "noise_level": evaluation.get("noise_level"),
    }
    try:
        quality = {name: float(quality_source[name]) for name in schema.quality_cols}
    except (KeyError, TypeError, ValueError):
        return None, ["missing_or_invalid_quality_score"]

    expected = {
        "status": (record.get("status"), config.get("required_status", "SUCCESS")),
        "overall_verdict": (
            evaluation.get("overall_verdict"),
            config.get("required_verdict", "accept"),
        ),
        "correctness": (
            evaluation.get("correctness"),
            config.get("required_correctness", "Y"),
        ),
        "duplication": (
            evaluation.get("duplication_suspect"),
            config.get("required_duplication_suspect", "N"),
        ),
    }
    for reason, (actual, required) in expected.items():
        if required is not None and actual != required:
            reasons.append(f"{reason}_rejected")

    thresholds = config.get("min_quality", {}) or {}
    for name, minimum in thresholds.items():
        if name in quality and quality[name] < float(minimum):
            reasons.append(f"{name}_below_min")

    minimum_domain_score = config.get("min_primary_domain_score")
    if minimum_domain_score is not None and (
        domain_score is None or domain_score < float(minimum_domain_score)
    ):
        reasons.append("primary_domain_score_below_min")

    token_count = _token_count(record)
    minimum_tokens = config.get("min_token_num")
    maximum_tokens = config.get("max_token_num")
    if minimum_tokens is not None and (token_count is None or token_count < int(minimum_tokens)):
        reasons.append("token_num_below_min")
    if maximum_tokens is not None and token_count is not None and token_count > int(maximum_tokens):
        reasons.append("token_num_above_max")

    adapted: dict[str, Any] = {
        schema.text_col: text,
        schema.domain_col: domain,
        **quality,
    }
    if schema.char_count_col is not None:
        char_count = record.get("cut_text_len", record.get("raw_text_len", len(text)))
        try:
            adapted[schema.char_count_col] = int(char_count)
        except (TypeError, ValueError):
            return None, ["invalid_char_count"]
    if schema.row_in_shard_col is not None:
        # This must remain the physical row position so on-demand JSON text
        # reads can locate the source record without materializing a copy.
        adapted[schema.row_in_shard_col] = position
    adapted["source_id"] = str(record.get("uuid") or record.get("__id__") or position)
    return adapted, reasons


def _derive_domain(
    record: dict[str, Any], evaluation: dict[str, Any]
) -> tuple[str | None, float | None]:
    classifications = record.get("domain_category_cls_v1.3")
    if isinstance(classifications, list) and classifications:
        primary = classifications[0]
        if isinstance(primary, dict):
            name = str(primary.get("category_name", ""))
            domain = _domain_from_label(name)
            try:
                score = float(primary.get("score"))
            except (TypeError, ValueError):
                score = None
            if domain is not None:
                return domain, score

    domains = evaluation.get("stem_domains")
    if isinstance(domains, list):
        for value in domains:
            domain = _domain_from_label(str(value))
            if domain is not None:
                return domain, None
    return None, None


def _domain_from_label(label: str) -> str | None:
    value = label.strip().lower()
    segments = [part.strip() for part in re.split(r"[-/]", value) if part.strip()]
    mappings = (
        ("数学", {"数学", "mathematics", "math"}),
        ("化学", {"化学", "chemistry"}),
        ("生物学", {"生物学", "biology"}),
        ("物理", {"物理", "physics"}),
    )
    for domain, aliases in mappings:
        if any(segment in aliases for segment in segments) or value in aliases:
            return domain
    return None


def _token_count(record: dict[str, Any]) -> int | None:
    for key in ("token_num", "total_token_num"):
        try:
            if record.get(key) is not None:
                return int(record[key])
        except (TypeError, ValueError):
            return None
    token_length = record.get("token_length")
    if isinstance(token_length, dict):
        for value in token_length.values():
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None
