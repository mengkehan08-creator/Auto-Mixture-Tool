"""Portable paths for sampled datasets passed between cloud jobs."""
from __future__ import annotations

import json
from pathlib import Path


def manual_plans(root: Path) -> list[dict]:
    root = root.resolve()
    plans = json.loads((root / "manual_plans_manifest.json").read_text(encoding="utf-8"))
    for plan in plans:
        stored = str(plan["data_dir"])
        # Older manifests used the first ModelArts job's absolute output path.
        if stored.startswith("/home/ma-user/modelarts/outputs/"):
            stored = Path(stored).name
        path = (root / stored).resolve()
        if not path.is_relative_to(root) or not path.is_dir():
            raise ValueError(f"采样集路径无效或未挂载：{stored}")
        if not any(path.glob("*.parquet")):
            raise ValueError(f"采样集没有 Parquet 分片：{path}")
        plan["data_dir"] = str(path)
    return plans


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--short", action="store_true")
    args = parser.parse_args()
    for plan in manual_plans(args.root):
        values = [plan["id"], plan["label"], plan["data_dir"]]
        if not args.short:
            values.append(plan["tokens"])
        print("\t".join(str(value).replace("\t", " ").replace("\n", " ") for value in values))


if __name__ == "__main__":
    main()
