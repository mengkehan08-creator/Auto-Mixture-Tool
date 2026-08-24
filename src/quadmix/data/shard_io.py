"""Shard-level I/O workers for Parquet/JSON metadata and text reading.

Standalone functions designed for multiprocessing (spawn-safe, no `self`).
Moved from metadata_manager.py to isolate the I/O concern.
"""

import json
import os
import re
from itertools import chain
from collections import Counter
from typing import Any, Dict, Iterator, List, Optional, Tuple

import numpy as np
import numpy.typing as npt

from quadmix.data.dataset_schema import DatasetSchema
from quadmix.data.record_adapter import adapt_record


def _parse_shard_idx(basename: str) -> Optional[int]:
    m = re.search(r'(\d+)', basename)
    if m:
        return int(m.group(1))
    return None


_JSON_SUFFIXES = {".json", ".jsonl", ".jsonlines", ".ndjson"}
_JSON_WRAPPER_KEYS = ("samples", "data", "records", "examples", "items")


def is_json_shard(path: str) -> bool:
    suffix = os.path.splitext(path)[1].lower()
    return suffix in _JSON_SUFFIXES or (not suffix and os.path.basename(path).startswith("part-"))


def _iter_json_array(handle, chunk_size: int = 1024 * 1024) -> Iterator[Any]:
    """Stream a top-level JSON array without loading the complete shard."""
    decoder = json.JSONDecoder()
    buffer = ""
    position = 0
    started = False
    eof = False
    while True:
        if position >= len(buffer) and not eof:
            buffer = handle.read(chunk_size)
            position = 0
            eof = not buffer
        while position < len(buffer) and buffer[position].isspace():
            position += 1
        if not started:
            if position >= len(buffer):
                if eof:
                    raise ValueError("empty JSON array shard")
                continue
            if buffer[position] != "[":
                raise ValueError("expected a top-level JSON array")
            position += 1
            started = True
        while position < len(buffer) and (buffer[position].isspace() or buffer[position] == ","):
            position += 1
        if position < len(buffer) and buffer[position] == "]":
            return
        if position >= len(buffer):
            if eof:
                raise ValueError("unterminated JSON array")
            buffer = ""
            continue
        try:
            value, end = decoder.raw_decode(buffer, position)
        except json.JSONDecodeError:
            if eof:
                raise
            more = handle.read(chunk_size)
            buffer = buffer[position:] + more
            position = 0
            eof = not more
            continue
        yield value
        position = end
        if position > chunk_size:
            buffer = buffer[position:]
            position = 0


def iter_json_records(path: str) -> Iterator[dict[str, Any]]:
    """Yield records from JSONL, a JSON array, object, or wrapped array."""
    with open(path, "r", encoding="utf-8-sig") as handle:
        first = ""
        while True:
            char = handle.read(1)
            if not char:
                raise ValueError(f"empty JSON shard: {path}")
            if not char.isspace():
                first = char
                break
        handle.seek(0)
        if first == "[":
            values = _iter_json_array(handle)
            for row_number, value in enumerate(values, 1):
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{row_number}: JSON record must be an object")
                yield value
            return

        first_line = ""
        first_line_number = 0
        for first_line_number, line in enumerate(handle, 1):
            if line.strip():
                first_line = line
                break
        try:
            first_value = json.loads(first_line)
        except json.JSONDecodeError:
            # Pretty-printed single object/wrapped array. This representation is
            # supported for compatibility, but line-delimited JSON is preferred
            # for very large shards.
            handle.seek(0)
            value = json.load(handle)
            values = _unwrap_json_value(value, path)
            yield from values
            return

        next_line = ""
        next_line_number = first_line_number
        for next_line_number, line in enumerate(handle, first_line_number + 1):
            if line.strip():
                next_line = line
                break
        if next_line:
            if not isinstance(first_value, dict):
                raise ValueError(
                    f"{path}:{first_line_number}: JSONL record must be an object"
                )
            yield first_value
            lines = chain(
                [(next_line_number, next_line)],
                enumerate(handle, next_line_number + 1),
            )
            for line_number, line in lines:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{path}:{line_number}: invalid JSON record") from exc
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{line_number}: JSONL record must be an object")
                yield value
            return

        yield from _unwrap_json_value(first_value, path)


def _unwrap_json_value(value: Any, path: str) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        for key in _JSON_WRAPPER_KEYS:
            if isinstance(value.get(key), list):
                value = value[key]
                break
        else:
            yield value
            return
    if not isinstance(value, list):
        raise ValueError(f"{path}: expected a JSON object or array of objects")
    for row_number, row in enumerate(value, 1):
        if not isinstance(row, dict):
            raise ValueError(f"{path}:{row_number}: JSON record must be an object")
        yield row


def _read_shard_metadata_json(shard_path: str, schema: DatasetSchema) -> dict:
    """Read only schema-selected metadata from a JSON/JSONL shard."""
    basename = os.path.basename(shard_path)
    domain_values: List[Any] = []
    quality_values: List[List[float]] = []
    char_counts: List[int] = []
    row_values: List[int] = []
    rejection_counts: Counter[str] = Counter()
    scanned_records = 0
    computed_char_count = schema.needs_text_for_char_count()
    for position, source_record in enumerate(iter_json_records(shard_path)):
        scanned_records += 1
        record, reasons = adapt_record(source_record, schema, position)
        if record is None or reasons:
            rejection_counts.update(reasons or ["adapter_rejected"])
            continue
        try:
            text = record[schema.text_col]
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"column {schema.text_col!r} must be a non-empty string")
            domain_values.append(record[schema.domain_col])
            quality_values.append([float(record[column]) for column in schema.quality_cols])
            if schema.char_count_col is None:
                char_counts.append(len(text))
            else:
                char_counts.append(int(record[schema.char_count_col]))
            row_values.append(
                int(record.get(schema.row_in_shard_col, position))
                if schema.row_in_shard_col is not None else position
            )
        except KeyError as exc:
            raise ValueError(f"{shard_path}:{position + 1}: missing column {exc.args[0]!r}") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{shard_path}:{position + 1}: invalid metadata value: {exc}") from exc

    domain_cat_map = None
    if any(isinstance(value, str) for value in domain_values):
        if schema.domain_names is None:
            raise ValueError(
                f"domain_col '{schema.domain_col}' contains strings but schema.domain_names is missing"
            )
        domain_cat_map = {name: index for index, name in enumerate(schema.domain_names)}
        unknown_domains = sorted(
            {str(value) for value in domain_values if str(value) not in domain_cat_map}
        )
        if unknown_domains:
            raise ValueError(
                f"{shard_path}: domain values are not declared in schema.domain_names: "
                f"{unknown_domains[:10]}"
            )
        domain_arr = np.array(
            [domain_cat_map.get(str(value), -1) for value in domain_values],
            dtype=np.int64,
        )
    else:
        domain_arr = np.asarray(domain_values, dtype=np.int64)

    quality_arr = (
        np.asarray(quality_values, dtype=np.float64)
        if quality_values else np.empty((0, len(schema.quality_cols)), dtype=np.float64)
    )
    nan_count = int(np.isnan(quality_arr).sum())
    if nan_count:
        print(
            f"[ShardMetadataManager] WARNING: {basename} has {nan_count} NaN quality values; filling with 0.0"
        )
        quality_arr = np.nan_to_num(quality_arr, nan=0.0)
    return {
        "shard_idx": _parse_shard_idx(basename),
        "path": shard_path,
        "num_docs": len(domain_values),
        "domain": domain_arr,
        "quality": quality_arr,
        "char_count": np.asarray(char_counts, dtype=np.int64),
        "row_in_shard_col": np.asarray(row_values, dtype=np.int64),
        "domain_cat_map": domain_cat_map,
        "computed_char_count": computed_char_count,
        "filter_report": {
            "scanned": scanned_records,
            "accepted": len(domain_values),
            "rejected": scanned_records - len(domain_values),
            "reasons": dict(sorted(rejection_counts.items())),
        },
    }


def read_shard_metadata(shard_path: str, schema: DatasetSchema) -> dict:
    if is_json_shard(shard_path):
        return _read_shard_metadata_json(shard_path, schema)
    return _read_shard_metadata_pyarrow(shard_path, schema)


def _read_shard_metadata_pyarrow(shard_path: str, schema: DatasetSchema) -> dict:
    import pyarrow.parquet as pq
    basename = os.path.basename(shard_path)
    parsed_idx = _parse_shard_idx(basename)

    read_cols = schema.metadata_read_columns()
    pf = pq.ParquetFile(shard_path)
    table = pf.read(columns=read_cols, use_threads=False)
    n = len(table)

    domain_col_data = table.column(schema.domain_col).to_numpy(zero_copy_only=False)
    if hasattr(domain_col_data.dtype, 'categories') or domain_col_data.dtype == object:
        import pandas as pd
        series = pd.Series(domain_col_data)
        if schema.domain_names is not None:
            all_cats = pd.CategoricalDtype(categories=schema.domain_names, ordered=False)
            cat_series = series.astype(all_cats)
            unseen = set(series.unique()) - set(schema.domain_names)
            if unseen:
                num_missing = int(sum(series.isin(unseen)))
                import warnings
                warnings.warn(
                    f"domain_col '{schema.domain_col}' 有 {num_missing} 条数据的值 "
                    f"不在 schema.domain_names 中 ({unseen})。"
                    f"这些值会被映射为 -1，在采样时被忽略。"
                    f"请在 domain_names 中补充这些值。"
                )
        else:
            raise ValueError(
                f"domain_col '{schema.domain_col}' is string/object type but "
                f"schema.domain_names is not provided. String domain columns "
                f"require domain_names in schema.yaml to ensure consistent "
                f"cross-shard categorical encoding. "
                f"Add domain_names to your schema config."
            )
        domain_arr = cat_series.cat.codes.to_numpy(dtype=np.int64)
        cat_map = dict(zip(
            cat_series.cat.categories,
            range(len(cat_series.cat.categories)),
        ))
    elif domain_col_data.dtype.kind in ('i', 'u'):
        domain_arr = domain_col_data.astype(np.int64)
        unique_vals = np.unique(domain_arr)
        if len(unique_vals) > 0 and (unique_vals.min() != 0 or
            unique_vals.max() != len(unique_vals) - 1 or
            not np.all(unique_vals == np.arange(len(unique_vals)))):
            sort_idx = np.argsort(unique_vals)
            sorted_vals = unique_vals[sort_idx]
            positions = np.searchsorted(sorted_vals, domain_arr)
            inv_order = np.empty_like(sort_idx)
            inv_order[sort_idx] = np.arange(len(sort_idx))
            domain_arr = inv_order[positions].astype(np.int64)
            cat_map = {str(v): i for i, v in enumerate(unique_vals)}
        else:
            cat_map = None
    else:
        raise ValueError(
            f"domain_col '{schema.domain_col}' has unsupported dtype "
            f"'{domain_col_data.dtype}'. Expected string/object or integer."
        )

    quality_arr = np.column_stack([
        table.column(c).to_numpy(zero_copy_only=False).astype(np.float64)
        for c in schema.quality_cols
    ])
    nan_count = np.isnan(quality_arr).sum()
    if nan_count > 0:
        pct = nan_count / quality_arr.size * 100
        print(f"[ShardMetadataManager] WARNING: quality scores have {nan_count} "
              f"NaN values ({pct:.1f}%), filling with 0.0. "
              f"建议在预处理时处理缺失值。")
        quality_arr = np.nan_to_num(quality_arr, nan=0.0)

    if schema.char_count_col is not None:
        char_count_arr = table.column(schema.char_count_col).to_numpy(
            zero_copy_only=False).astype(np.int64)
    elif schema.needs_text_for_char_count():
        import pandas as pd
        text_series = pd.Series(table.column(schema.text_col).to_numpy(zero_copy_only=False))
        char_count_arr = text_series.apply(
            lambda t: len(str(t)) if t is not None else 0
        ).to_numpy(dtype=np.int64)
    else:
        char_count_arr = np.zeros(n, dtype=np.int64)

    if schema.row_in_shard_col is not None and schema.row_in_shard_col in table.column_names:
        row_in_shard_arr = table.column(schema.row_in_shard_col).to_numpy(
            zero_copy_only=False).astype(np.int64)
    else:
        row_in_shard_arr = np.arange(n, dtype=np.int64)

    return {
        "shard_idx": parsed_idx,
        "path": shard_path,
        "num_docs": n,
        "domain": domain_arr,
        "quality": quality_arr,
        "char_count": char_count_arr,
        "row_in_shard_col": row_in_shard_arr,
        "domain_cat_map": cat_map,
        "computed_char_count": schema.needs_text_for_char_count(),
    }


def read_one_shard_texts_with_rows(
    shard_path: str,
    text_col: str,
    row_col: Optional[str],
    row_col_values: Optional[np.ndarray],
    has_row_in_shard: bool,
    is_row_col_sequential: bool,
    shard_total_rows: int,
) -> Tuple[List[str], np.ndarray]:
    """Read texts from a single shard using pyarrow, returning (texts, parsed_rows).

    texts[i] corresponds to parsed_rows[i].  parsed_rows is sorted ascending
    (matching the current df.sort_values(row_col) convention used by tokenize
    pipeline).  The caller maps parsed_rows to token array positions.

    Three strategies based on select ratio and row_col characteristics:
      1. No row_col or sequential row_col: read text column directly, numpy index
      2. High select ratio (>0.3): read full shard, filter in memory
      3. Low select ratio (≤0.3): pyarrow filter pushdown
    """
    import pyarrow.parquet as pq

    if not has_row_in_shard or row_col is None:
        table = pq.read_table(
            shard_path, columns=[text_col], use_threads=False
        )
        text_arr = table.column(text_col).to_numpy(zero_copy_only=False)
        texts = [str(v) if v is not None else "" for v in text_arr]
        parsed_rows = np.arange(len(texts), dtype=np.int64)
        return texts, parsed_rows

    n_requested = len(row_col_values)
    select_ratio = n_requested / max(shard_total_rows, 1)

    if is_row_col_sequential:
        table = pq.read_table(
            shard_path, columns=[text_col], use_threads=False
        )
        text_arr = table.column(text_col).to_numpy(zero_copy_only=False)
        texts = []
        for rv in row_col_values:
            idx = int(rv)
            if 0 <= idx < len(text_arr):
                val = text_arr[idx]
                texts.append(str(val) if val is not None else "")
            else:
                texts.append("")
        parsed_rows = row_col_values.astype(np.int64)
        return texts, parsed_rows

    if select_ratio > 0.3:
        table = pq.read_table(
            shard_path, columns=[row_col, text_col], use_threads=False
        )
        row_arr = table.column(row_col).to_numpy(zero_copy_only=False)
        text_arr = table.column(text_col).to_numpy(zero_copy_only=False)
        chunk_map: Dict = {}
        for k, v in zip(row_arr, text_arr):
            chunk_map[int(k)] = str(v) if v is not None else ""
        texts = [chunk_map.get(int(rv), "") for rv in row_col_values]
        parsed_rows = row_col_values.astype(np.int64)
        return texts, parsed_rows

    table = pq.read_table(
        shard_path,
        columns=[row_col, text_col],
        filters=[(row_col, "in", row_col_values.tolist())],
        use_threads=False,
    )
    row_arr = table.column(row_col).to_numpy(zero_copy_only=False)
    text_arr = table.column(text_col).to_numpy(zero_copy_only=False)
    sort_idx = np.argsort(row_arr)
    texts = [str(text_arr[i]) if text_arr[i] is not None else "" for i in sort_idx]
    parsed_rows = row_arr[sort_idx].astype(np.int64)
    return texts, parsed_rows


def read_one_shard_texts(
    shard_path: str,
    text_col: str,
    row_col: Optional[str],
    row_col_values: Optional[np.ndarray],
    local_rows: np.ndarray,
    shard_total_rows: int,
    is_row_col_sequential: bool,
) -> List[str]:
    """Read texts from a single shard, returning only the requested texts.

    When row_col is None: reads text column, indexes by local_rows (selective,
    memory-efficient for sparse requests).

    When row_col is present: delegates to read_one_shard_texts_with_rows,
    discarding parsed_rows (the caller already has local_rows for mapping).
    """
    if is_json_shard(shard_path):
        requested = row_col_values if row_col is not None else local_rows
        pending = {int(value) for value in requested}
        found: Dict[int, str] = {}
        for position, record in enumerate(iter_json_records(shard_path)):
            key = int(record.get(row_col, position)) if row_col is not None else position
            if key in pending:
                value = record.get(text_col, "")
                found[key] = str(value) if value is not None else ""
                pending.remove(key)
                if not pending:
                    break
        if pending:
            raise IndexError(
                f"{shard_path}: requested JSON row ids were not found: {sorted(pending)[:10]}"
            )
        return [found[int(value)] for value in requested]

    if row_col is None:
        import pyarrow.parquet as pq
        n_requested = len(local_rows)
        if n_requested < shard_total_rows * 0.05 and shard_total_rows > 1000:
            import logging
            logging.getLogger(__name__).warning(
                f"Reading {shard_total_rows} rows from shard for only {n_requested} "
                f"requested rows (ratio {n_requested/max(shard_total_rows,1):.2%}). "
                f"Consider adding row_in_shard_col to schema for efficient filtering."
            )
        table = pq.read_table(
            shard_path, columns=[text_col], use_threads=False
        )
        text_arr = table.column(text_col).to_numpy(zero_copy_only=False)
        result = []
        for i in local_rows:
            if 0 <= int(i) < len(text_arr):
                val = text_arr[int(i)]
                result.append(str(val) if val is not None else "")
            else:
                result.append("")
        return result

    texts, parsed_rows = read_one_shard_texts_with_rows(
        shard_path, text_col, row_col, row_col_values,
        True, is_row_col_sequential, shard_total_rows,
    )
    text_map = dict(zip(parsed_rows.tolist(), texts))
    return [text_map.get(int(rv), "") for rv in row_col_values]


def assemble_texts_array(
    global_indices: npt.NDArray[np.int64],
    shard_groups: Dict[int, Tuple[str, npt.NDArray[np.int64]]],
    shard_results: Dict[int, List[str]],
    shard_starts: npt.NDArray[np.int64],
) -> List[str]:
    """Vectorized text assembly via argsort + searchsorted.

    Correct for both unique and duplicate ``global_indices``; auto-branches
    to a per-text loop only when duplicates exist in a shard.
    """
    n = len(global_indices)
    if n == 0:
        return []
    gids = np.asarray(global_indices, dtype=np.int64)
    order = np.argsort(gids, kind="stable")
    sorted_gids = gids[order]
    result = np.full(n, "", dtype=object)
    for sid, (_shard_path, local_rows) in shard_groups.items():
        texts = shard_results[sid]
        shard_gids = shard_starts[sid] + np.asarray(local_rows, dtype=np.int64)
        left = np.searchsorted(sorted_gids, shard_gids, side="left")
        right = np.searchsorted(sorted_gids, shard_gids, side="right")
        if np.array_equal(left + 1, right):
            result[order[left]] = texts
        else:
            for i in range(len(texts)):
                lo = int(left[i])
                hi = int(right[i])
                for pos in order[lo:hi]:
                    result[pos] = texts[i]
    return result.tolist()
