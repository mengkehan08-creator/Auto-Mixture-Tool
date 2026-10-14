#!/usr/bin/env python3
"""Filter nested STEM JSON shards and write QuadMix-native Parquet shards."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from auto_mixture_tool.data.validator import validate_dataset
from quadmix.data.dataset_schema import DatasetSchema
from quadmix.data.record_adapter import adapt_record
from quadmix.data.shard_io import is_json_shard, iter_json_records
from quadmix_platform.dataset_inspector import _data_files


def build_parquet_record(
    adapted: dict[str, Any],
    source_schema: DatasetSchema,
    output_schema: DatasetSchema,
    output_row: int,
) -> dict[str, Any]:
    """Map one accepted adapter record to the flat algorithm contract."""
    text = adapted[source_schema.text_col]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    result: dict[str, Any] = {
        output_schema.text_col: text,
        output_schema.domain_col: str(adapted[source_schema.domain_col]),
    }
    for quality_name in output_schema.quality_cols:
        result[quality_name] = float(adapted[quality_name])
    if output_schema.char_count_col is None:
        raise ValueError("output schema must define char_count_col")
    source_char_col = source_schema.char_count_col
    result[output_schema.char_count_col] = int(
        adapted[source_char_col] if source_char_col else len(text)
    )
    if output_schema.row_in_shard_col is None:
        raise ValueError("output schema must define row_in_shard_col")
    result[output_schema.row_in_shard_col] = int(output_row)
    return result


def _arrow_schema(output_schema: DatasetSchema):
    import pyarrow as pa

    fields = [
        pa.field(output_schema.text_col, pa.string(), nullable=False),
        pa.field(output_schema.domain_col, pa.string(), nullable=False),
    ]
    fields.extend(pa.field(name, pa.float64(), nullable=False) for name in output_schema.quality_cols)
    fields.append(pa.field(output_schema.char_count_col, pa.int64(), nullable=False))
    fields.append(pa.field(output_schema.row_in_shard_col, pa.int64(), nullable=False))
    return pa.schema(fields)


def convert_dataset(
    input_uri: str,
    source_schema_uri: str,
    output_uri: str,
    output_schema_uri: str,
    report_uri: str,
    rows_per_group: int = 10_000,
    compression: str = "zstd",
    shard_start: int | None = None,
    shard_end: int | None = None,
) -> dict[str, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("数据格式不符合算法要求: 转换 Parquet 需要安装 pyarrow") from exc

    source_schema = DatasetSchema.from_yaml(source_schema_uri)
    output_schema = DatasetSchema.from_yaml(output_schema_uri)
    sources = _data_files(
        Path(input_uri).expanduser().resolve(), shard_start, shard_end
    )
    unsupported = [str(source) for source in sources if not is_json_shard(str(source))]
    if unsupported:
        raise RuntimeError(
            "数据格式不符合算法要求: 转换模块仅支持 JSON/JSONL/无扩展名 part-* 输入: "
            f"{unsupported[:10]}"
        )

    output = Path(output_uri).expanduser().resolve()
    if output.exists():
        raise RuntimeError(f"数据格式不符合算法要求: 转换输出目录已存在: {output}")
    output.mkdir(parents=True)
    report_path = Path(report_uri).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    arrow_schema = _arrow_schema(output_schema)
    codec = compression

    scanned = accepted = 0
    rejection_reasons: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    output_files: list[str] = []

    for source_index, source in enumerate(sources):
        writer = None
        batch: list[dict[str, Any]] = []
        output_row = 0
        target = output / f"part-{source_index:05d}.parquet"
        try:
            for source_row, source_record in enumerate(iter_json_records(str(source))):
                scanned += 1
                adapted, reasons = adapt_record(source_record, source_schema, source_row)
                if adapted is None or reasons:
                    rejection_reasons.update(reasons or ["adapter_rejected"])
                    continue
                try:
                    record = build_parquet_record(
                        adapted, source_schema, output_schema, output_row
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    rejection_reasons.update([f"algorithm_field_error:{exc}"])
                    continue
                batch.append(record)
                accepted += 1
                output_row += 1
                domain_counts[record[output_schema.domain_col]] += 1
                if len(batch) >= rows_per_group:
                    if writer is None:
                        writer = pq.ParquetWriter(target, arrow_schema, compression=codec)
                        output_files.append(str(target))
                    writer.write_table(pa.Table.from_pylist(batch, schema=arrow_schema))
                    batch.clear()
            if batch:
                if writer is None:
                    writer = pq.ParquetWriter(target, arrow_schema, compression=codec)
                    output_files.append(str(target))
                writer.write_table(pa.Table.from_pylist(batch, schema=arrow_schema))
        finally:
            if writer is not None:
                writer.close()

    report: dict[str, Any] = {
        "source_unchanged": True,
        "source_files": len(sources),
        "shard_range": {"start": shard_start, "end": shard_end},
        "output_files": output_files,
        "scanned": scanned,
        "accepted": accepted,
        "rejected": scanned - accepted,
        "acceptance_rate": accepted / max(1, scanned),
        "rejection_reasons": dict(sorted(rejection_reasons.items())),
        "domain_distribution": dict(sorted(domain_counts.items())),
        "output_columns": [field.name for field in arrow_schema],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if accepted == 0:
        raise RuntimeError("数据格式不符合算法要求: 过滤后没有任何合格数据")
    missing_domains = [
        domain for domain in (output_schema.domain_names or []) if domain_counts[domain] == 0
    ]
    if missing_domains:
        raise RuntimeError(
            f"数据格式不符合算法要求: 转换后缺少领域数据: {missing_domains}"
        )

    validation = validate_dataset(
        str(output), output_schema_uri, sample_size=min(10_000, accepted)
    )
    report["post_conversion_validation"] = validation
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not validation["valid"]:
        raise RuntimeError(
            "数据格式不符合算法要求: " + "; ".join(validation["errors"])
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--source-schema", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--output-schema", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--rows-per-group", type=int, default=10_000)
    parser.add_argument("--compression", default="zstd")
    parser.add_argument("--shard-start", type=int)
    parser.add_argument("--shard-end", type=int)
    args = parser.parse_args()
    try:
        report = convert_dataset(
            args.input,
            args.source_schema,
            args.output,
            args.output_schema,
            args.report,
            args.rows_per_group,
            args.compression,
            args.shard_start,
            args.shard_end,
        )
    except Exception as exc:  # noqa: BLE001 - command boundary
        message = str(exc)
        if not message.startswith("数据格式不符合算法要求"):
            message = f"数据格式不符合算法要求: {message}"
        print(message, file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
