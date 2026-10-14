"""STEM JSON filtering and Parquet normalization dataset plugin."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from auto_mixture_tool.plugins.base import CommandSpec
from auto_mixture_tool.plugins.format_validators.quadmix import QuadMixFormatValidator
from quadmix.data.dataset_schema import DatasetSchema
from quadmix.data.shard_io import is_json_shard
from quadmix_platform.dataset_inspector import _data_files


class StemJsonParquetDataset(QuadMixFormatValidator):
    """Filter nested STEM JSON records and emit QuadMix-native Parquet."""

    id = "stem-json-parquet"
    display_name = "STEM JSON filter and Parquet normalization"

    def validate(self, request: dict[str, Any]) -> dict[str, Any]:
        report = super().validate(request)
        errors = list(report.get("errors", []))
        try:
            schema = DatasetSchema.from_yaml(str(request["schema_uri"]))
            if schema.record_adapter != "stem-sample-json-v1":
                errors.append(
                    "stem-json-parquet 要求 source schema 使用 "
                    "record_adapter: stem-sample-json-v1"
                )
            unsupported = [
                source.name
                for source in _data_files(
                    Path(str(request["dataset_uri"])).resolve(),
                    request.get("dataset_config", {}).get("shard_start"),
                    request.get("dataset_config", {}).get("shard_end"),
                )
                if not is_json_shard(str(source))
            ]
            if unsupported:
                errors.append(
                    "stem-json-parquet 仅接受 JSON/JSONL/无扩展名 part-* 输入: "
                    f"{unsupported[:10]}"
                )
        except Exception as exc:  # noqa: BLE001 - return a validation report
            errors.append(f"无法检查 STEM JSON 转换配置: {exc}")
        report["errors"] = sorted(set(errors))
        report["valid"] = not report["errors"]
        return report

    def prepare(
        self, request: dict[str, Any], workspace: Path
    ) -> tuple[str, list[CommandSpec]]:
        config = request.get("dataset_config", {})
        rows_per_group = int(config.get("rows_per_group", 10_000))
        if rows_per_group <= 0:
            raise ValueError("dataset_config.rows_per_group must be positive")
        compression = str(config.get("compression", "zstd")).lower()
        if compression not in {"zstd", "snappy", "gzip", "brotli", "lz4", "none"}:
            raise ValueError("unsupported dataset_config.compression")
        shard_start = config.get("shard_start")
        shard_end = config.get("shard_end")

        output_root = Path(
            request.get("output_uri")
            or workspace / "result" / request["job_id"] / "quadmix"
        )
        prepared = output_root / f"prepared_parquet_{request['job_id']}"
        report = output_root / f"conversion_report_{request['job_id']}.json"
        output_schema = self._output_schema(request, workspace)
        args = [
            str(workspace / "scripts" / "platform" / "convert_stem_json_to_parquet.py"),
            "--input", str(request["dataset_uri"]),
            "--source-schema", str(request["schema_uri"]),
            "--output", str(prepared),
            "--output-schema", str(output_schema),
            "--report", str(report),
            "--rows-per-group", str(rows_per_group),
            "--compression", compression,
        ]
        if shard_start is not None:
            args.extend(["--shard-start", str(int(shard_start))])
        if shard_end is not None:
            args.extend(["--shard-end", str(int(shard_end))])
        stage = CommandSpec(
            "dataset-filter-convert-parquet",
            "python",
            args,
            cwd=str(workspace),
        )
        return str(prepared), [stage]

    def prepared_schema_uri(self, request: dict[str, Any], workspace: Path) -> str:
        return str(self._output_schema(request, workspace))

    @staticmethod
    def _output_schema(request: dict[str, Any], workspace: Path) -> Path:
        configured = request.get("dataset_config", {}).get("output_schema_uri")
        path = Path(configured) if configured else workspace / "configs" / "schema_stem_quadmix_parquet.yaml"
        return path if path.is_absolute() else workspace / path
