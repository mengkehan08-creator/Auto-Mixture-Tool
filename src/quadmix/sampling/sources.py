"""Lightweight helpers for resolving sampled Parquet artifacts."""

from __future__ import annotations

from pathlib import Path


def resolve_parquet_source(path: str) -> list[str]:
    """Return only Parquet files from a file or sampled-dataset directory."""
    source = Path(path)
    if source.is_dir():
        shards = sorted(str(candidate) for candidate in source.glob("*.parquet"))
        if not shards:
            raise ValueError(f"Directory '{path}' contains no .parquet files")
        return shards
    if source.is_file():
        return [str(source)]
    raise FileNotFoundError(
        f"Parquet source not found: {path} (not a file or directory)"
    )
