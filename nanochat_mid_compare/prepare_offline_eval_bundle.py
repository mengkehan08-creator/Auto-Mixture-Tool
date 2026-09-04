"""Materialize a mounted NanoChat evaluation bundle without network access."""

from __future__ import annotations

import argparse
import os
import zipfile
from pathlib import Path


def _link_children(source: Path, runtime: Path) -> None:
    for item in source.iterdir():
        if item.suffix.lower() == ".zip":
            continue
        target = runtime / item.name
        if target.exists() or target.is_symlink():
            continue
        target.symlink_to(item.resolve(), target_is_directory=item.is_dir())


def materialize(source: Path, runtime: Path) -> None:
    if not source.is_dir() or not any(source.iterdir()):
        raise ValueError(f"offline evaluation bundle is missing or empty: {source}")
    runtime.mkdir(parents=True, exist_ok=True)
    _link_children(source, runtime)
    nested = source / "eval_bundle"
    if nested.is_dir():
        _link_children(nested, runtime)
    for archive in source.rglob("*.zip"):
        if not zipfile.is_zipfile(archive):
            raise ValueError(f"invalid evaluation zip: {archive}")
        marker = runtime / f".{archive.name}.extracted"
        if marker.exists():
            continue
        with zipfile.ZipFile(archive) as handle:
            handle.extractall(runtime)
        marker.write_text(str(archive), encoding="utf-8")
    os.environ["NANOCHAT_BASE_DIR"] = str(runtime)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("runtime")
    args = parser.parse_args()
    materialize(Path(args.source), Path(args.runtime))
    print(f"Offline evaluation assets ready: {args.runtime}")


if __name__ == "__main__":
    main()
