"""QuadMix data-format conformance validator.

Checks whether a dataset matches the format expected by the QuadMix algorithm:

* required columns exist (domain, each quality column, text, char_count);
* **column types** match the expected kinds (quality → numeric, char_count →
  integer, domain / text → string);
* domain **labels are present** (no null / empty labels);
* domain labels are **the expected labels** — every value must belong to the
  ``domain_names`` set declared in the schema (when ``domain_names`` is given);
* quality-score columns are numeric and not entirely null;
* text column is non-empty;
* **encoding** is clean UTF-8 — no replacement characters (U+FFFD / mojibake)
  and no unexpected control characters;
* **duplicate shard files** — within a directory dataset, no two shards share
  the same name or the same content (catches accidental double-ingestion).

This is a *swappable* module: implement ``FormatValidatorAdapter`` to support a
different format standard and register it in ``PlatformService``. The individual
rule groups can be disabled per-request via ``request["format_options"]``
(``{"check_column_types": false, "check_encoding": false,
"check_duplicate_files": false}``).
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

from quadmix.data.dataset_schema import DatasetSchema
from quadmix.data.shard_io import is_json_shard
from quadmix_platform.dataset_inspector import (
    _data_files,
    _adapt_sample,
    _read_sample,
)

from auto_mixture_tool.plugins.base import FormatValidatorAdapter

# Control characters that should not appear in normal text (excluding the
# harmless whitespace: \t \n \r).
_CONTROL_CHARS = (
    set(range(0x00, 0x09)) | {0x0B, 0x0C} | set(range(0x0E, 0x1F))
)
_REPLACEMENT_CHAR = "\ufffd"
# Only hash the first chunk of a shard to catch exact-duplicate ingestion
# without reading multi-GB parquet files into memory.
_DUP_HASH_BYTES = 8 * 1024 * 1024
_NATIVE_SUFFIXES = {".json", ".jsonl", ".jsonlines", ".ndjson", ".parquet"}


class QuadMixFormatValidator(FormatValidatorAdapter):
    id = "quadmix"
    display_name = "QuadMix data-format conformance"

    # Below these fractions the column is considered effectively unusable.
    _NULL_LABEL_ERROR = 0.0          # any missing domain label is an error
    _NULL_QUALITY_WARN = 0.2         # >20% missing quality -> warning
    _EMPTY_TEXT_WARN = 0.05          # >5% empty text -> warning
    _REPLACEMENT_ERROR = 0.0         # any mojibake -> error
    _CONTROL_WARN = 0.02             # >2% control chars -> warning
    _MAX_DUP_HASH_FILE_BYTES = 200 * 1024 * 1024  # skip hashing huge files

    def validate(self, request: dict[str, Any]) -> dict[str, Any]:
        dataset_uri = str(request["dataset_uri"])
        schema_uri = str(request["schema_uri"])
        sample_size = int(request.get("sample_size", 1000))
        options = request.get("format_options", {}) or {}

        errors: list[str] = []
        warnings: list[str] = []
        details: dict[str, Any] = {}

        try:
            schema = DatasetSchema.from_yaml(schema_uri)
        except Exception as exc:  # noqa: BLE001 - surface schema parse errors
            return {
                "valid": False,
                "errors": [f"无法解析 schema 配置: {exc}"],
                "warnings": warnings,
                "details": details,
            }

        dataset_path = Path(dataset_uri).expanduser().resolve()
        details["dataset_path"] = str(dataset_path)

        # Read the sample (encoding errors are caught and reported cleanly).
        try:
            sources = _data_files(dataset_path)
            limit = max(1, min(sample_size, 10000))
            per_file_limit = max(1, math.ceil(limit / len(sources)))
            rows: list[dict[str, Any]] = []
            file_dtypes: dict[str, dict[str, str]] = {}
            totals: list[int | None] = []
            for source in sources:
                file_rows, _, total_rows = _read_sample(source, per_file_limit)
                file_rows, dtypes, filter_report = _adapt_sample(file_rows, schema)
                rows.extend(file_rows)
                file_dtypes[str(source)] = dtypes
                totals.append(total_rows)
                details.setdefault("filter_preview_by_file", {})[str(source)] = filter_report
                if filter_report["rejected"]:
                    warnings.append(
                        f"{source.name}: 样本过滤通过 {filter_report['accepted']}/"
                        f"{filter_report['scanned']}，原因={filter_report['reasons']}"
                    )
            rows = rows[:limit]
        except UnicodeDecodeError as exc:
            return {
                "valid": False,
                "errors": [f"文件编码非 UTF-8，无法解析: {exc}"],
                "warnings": warnings,
                "details": details,
            }
        except Exception as exc:  # noqa: BLE001 - any read failure is a format error
            return {
                "valid": False,
                "errors": [f"无法读取数据文件: {exc}"],
                "warnings": warnings,
                "details": details,
            }

        details["inspected_files"] = [str(source) for source in sources]
        unsupported = [
            source.name for source in sources
            if source.suffix.lower() not in _NATIVE_SUFFIXES and not is_json_shard(str(source))
        ]
        if unsupported:
            errors.append(
                "当前 QuadMix 原生读取仅支持 JSON/JSONL/Parquet；"
                f"不支持且不会自动转换: {unsupported[:10]}"
            )
        details["total_rows"] = sum(value for value in totals if value is not None) if all(
            value is not None for value in totals
        ) else None
        details["sampled_rows"] = len(rows)
        details["column_dtypes_by_file"] = file_dtypes

        if not rows:
            return {
                "valid": False,
                "errors": ["应用数据过滤规则后没有剩余样本，无法满足 QuadMix 输入要求"],
                "warnings": warnings,
                "details": details,
            }

        # 1) Required columns present.
        required = [schema.domain_col] + list(schema.quality_cols) + [schema.text_col]
        if schema.char_count_col is not None:
            required.append(schema.char_count_col)
        for source_name, dtypes in file_dtypes.items():
            if not dtypes:
                continue
            missing_cols = [col for col in required if col not in dtypes]
            if missing_cols:
                errors.append(f"{Path(source_name).name}: 缺少 QuadMix 必需列: {missing_cols}")

        # 2) Column types.
        if options.get("check_column_types", True):
            type_reports: dict[str, Any] = {}
            for source_name, dtypes in file_dtypes.items():
                if not dtypes:
                    continue
                local_errors: list[str] = []
                local_warnings: list[str] = []
                local_details: dict[str, Any] = {}
                self._check_column_types(
                    schema, dtypes, local_errors, local_warnings, local_details
                )
                prefix = Path(source_name).name
                errors.extend(f"{prefix}: {message}" for message in local_errors)
                warnings.extend(f"{prefix}: {message}" for message in local_warnings)
                type_reports[source_name] = local_details.get("column_types", {})
            details["column_types_by_file"] = type_reports

        # 3) Domain labels: present and are the expected labels.
        self._check_domain_labels(schema, rows, errors, warnings, details)

        # 4) Quality columns: numeric and not entirely null.
        self._check_quality_columns(schema, rows, errors, warnings, details)

        # 5) Text column non-empty.
        self._check_text_nonempty(schema, rows, warnings, details)

        # 6) Encoding: no replacement / control characters.
        if options.get("check_encoding", True):
            self._check_encoding(schema, rows, errors, warnings, details)

        # 7) Duplicate shard files within a directory dataset.
        if options.get("check_duplicate_files", True):
            self._check_duplicate_files(dataset_path, warnings, details)

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "details": details,
        }

    # ------------------------------------------------------------------ #
    # Rule implementations
    # ------------------------------------------------------------------ #
    def _check_column_types(
        self,
        schema: DatasetSchema,
        dtypes: dict[str, str],
        errors: list[str],
        warnings: list[str],
        details: dict[str, Any],
    ) -> None:
        expected: dict[str, str] = {schema.text_col: "string", schema.domain_col: "string"}
        for col in schema.quality_cols:
            expected[col] = "numeric"
        if schema.char_count_col is not None:
            expected[schema.char_count_col] = "integer"

        type_report: dict[str, Any] = {}
        for col, kind in expected.items():
            dt = dtypes.get(col, "unknown")
            ok = _dtype_matches(dt, kind)
            type_report[col] = {"inferred": dt, "expected": kind, "ok": ok}
            if not ok:
                errors.append(
                    f"列 '{col}' 推断类型为 {dt}，但 QuadMix 期望其为 {_kind_cn(kind)}"
                )
        details["column_types"] = type_report

    def _check_domain_labels(
        self,
        schema: DatasetSchema,
        rows: list[dict[str, Any]],
        errors: list[str],
        warnings: list[str],
        details: dict[str, Any],
    ) -> None:
        domain_col = schema.domain_col
        null_labels = sum(
            1 for row in rows if row.get(domain_col) in (None, "", "nan", "None")
        )
        domains_seen = {
            str(row.get(domain_col))
            for row in rows
            if row.get(domain_col) not in (None, "", "nan", "None")
        }
        details["null_label_count"] = null_labels
        details["distinct_domain_labels"] = sorted(domains_seen)
        if null_labels > 0:
            errors.append(
                f"域标签缺失: {null_labels}/{len(rows)} 行 domain 列为空/null"
            )
        if schema.domain_names:
            allowed = set(map(str, schema.domain_names))
            unknown = sorted(domains_seen - allowed)
            details["unknown_labels"] = unknown
            if unknown:
                errors.append(
                    f"存在非预期域标签(不在 domain_names 中): {unknown[:10]}"
                    f"{' ...' if len(unknown) > 10 else ''}"
                )
            missing_expected = sorted(allowed - domains_seen)
            if missing_expected:
                warnings.append(
                    f"以下声明域在样本中未出现(可能正常): {missing_expected[:10]}"
                )

    def _check_quality_columns(
        self,
        schema: DatasetSchema,
        rows: list[dict[str, Any]],
        errors: list[str],
        warnings: list[str],
        details: dict[str, Any],
    ) -> None:
        quality_stats: dict[str, Any] = {}
        for col in schema.quality_cols:
            values = [row.get(col) for row in rows]
            non_null = [v for v in values if v not in (None, "")]
            numeric = sum(1 for v in non_null if _is_float(v))
            null_rate = (len(values) - len(non_null)) / max(1, len(values))
            quality_stats[col] = {
                "non_null": len(non_null),
                "numeric": numeric,
                "null_rate": round(null_rate, 4),
            }
            if len(non_null) == 0:
                errors.append(f"质量列 '{col}' 全部为空/null")
            elif numeric < len(non_null):
                errors.append(f"质量列 '{col}' 含非数值: {non_null[:5]}")
            elif null_rate > self._NULL_QUALITY_WARN:
                warnings.append(
                    f"质量列 '{col}' 缺失率 {null_rate:.0%} 偏高"
                )
        details["quality_stats"] = quality_stats

    def _check_text_nonempty(
        self,
        schema: DatasetSchema,
        rows: list[dict[str, Any]],
        warnings: list[str],
        details: dict[str, Any],
    ) -> None:
        empty_text = sum(
            1 for row in rows if not isinstance(row.get(schema.text_col), str)
            or not row.get(schema.text_col).strip()
        )
        details["empty_text_count"] = empty_text
        if empty_text > 0 and empty_text / len(rows) > self._EMPTY_TEXT_WARN:
            warnings.append(f"文本列为空占比 {empty_text / len(rows):.0%}")

    def _check_encoding(
        self,
        schema: DatasetSchema,
        rows: list[dict[str, Any]],
        errors: list[str],
        warnings: list[str],
        details: dict[str, Any],
    ) -> None:
        repl_rows = 0
        control_rows = 0
        control_chars = 0
        for row in rows:
            text = row.get(schema.text_col)
            if not isinstance(text, str):
                continue
            if _REPLACEMENT_CHAR in text:
                repl_rows += 1
            found = 0
            for ch in text:
                if ord(ch) in _CONTROL_CHARS:
                    found += 1
            if found:
                control_rows += 1
                control_chars += found
        details["encoding"] = {
            "rows_with_replacement_char": repl_rows,
            "rows_with_control_chars": control_rows,
            "control_char_count": control_chars,
        }
        if repl_rows > 0 and repl_rows / len(rows) > self._REPLACEMENT_ERROR:
            errors.append(
                f"编码异常: {repl_rows}/{len(rows)} 行文本含替换符(U+FFFD)，"
                f"疑似非 UTF-8/乱码，请检查数据源编码"
            )
        elif control_rows > 0 and control_rows / len(rows) > self._CONTROL_WARN:
            warnings.append(
                f"编码注意: {control_rows}/{len(rows)} 行含控制字符"
                f"({control_chars} 个)，可能影响下游分词"
            )

    def _check_duplicate_files(
        self,
        dataset_path: Path,
        warnings: list[str],
        details: dict[str, Any],
    ) -> None:
        if dataset_path.is_file():
            details["duplicate_files"] = {"is_directory": False}
            return

        files = _data_files(dataset_path)
        by_name: dict[str, list[str]] = {}
        for f in files:
            by_name.setdefault(f.name, []).append(str(f))
        dup_name = {n: ps for n, ps in by_name.items() if len(ps) > 1}

        by_hash: dict[str, list[str]] = {}
        for f in files:
            try:
                digest = _file_hash(f)
            except OSError:
                continue
            by_hash.setdefault(digest, []).append(str(f))
        dup_content = {h: ps for h, ps in by_hash.items() if len(ps) > 1}

        details["duplicate_files"] = {
            "is_directory": True,
            "total_files": len(files),
            "duplicate_by_name": [
                {"name": n, "paths": ps} for n, ps in dup_name.items()
            ],
            "duplicate_by_content": [
                {"paths": ps} for ps in dup_content.values()
            ],
        }
        if dup_name:
            warnings.append(
                f"检测到同名分片文件({len(dup_name)}组)，可能重复摄入: "
                + "; ".join(list(dup_name)[:5])
            )
        if dup_content:
            warnings.append(
                f"检测到内容相同的分片文件({len(dup_content)}组)，建议去重后再运行"
            )


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #
def _is_float(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _dtype_matches(dtype: str, kind: str) -> bool:
    dt = (dtype or "").lower()
    if kind == "string":
        return "int" not in dt and "float" not in dt and "double" not in dt
    if kind == "numeric":
        return "int" in dt or "float" in dt or "double" in dt
    if kind == "integer":
        return "int" in dt or "uint" in dt
    return False


def _kind_cn(kind: str) -> str:
    return {"string": "文本(string)", "numeric": "数值(numeric)", "integer": "整数(integer)"}[kind]


def _file_hash(path: Path) -> str:
    size = path.stat().st_size
    read_bytes = _DUP_HASH_BYTES if size > _DUP_HASH_BYTES else size
    h = hashlib.md5()
    with path.open("rb") as handle:
        if read_bytes:
            h.update(handle.read(read_bytes))
        else:
            h.update(b"")
    return h.hexdigest()
