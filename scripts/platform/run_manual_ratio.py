#!/usr/bin/env python3
"""Manual per-domain ratio sampling baseline.

Reads a JSON file mapping domain name -> keep ratio and samples documents within
each domain independently. The output layout matches QuadMix's sampled dataset.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from quadmix.data.dataset_schema import DatasetSchema
from quadmix.data.metadata_manager import ShardMetadataManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual ratio sampling baseline")
    parser.add_argument("--dataset", required=True, help="preprocessed dataset directory")
    parser.add_argument("--schema", required=True, help="YAML schema config")
    parser.add_argument("--ratios", required=True, help="JSON file with domain->ratio mapping")
    parser.add_argument("--output", required=True, help="output directory")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--target-tokens", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    schema = DatasetSchema.from_yaml(args.schema)
    manager = ShardMetadataManager(args.dataset, schema=schema)
    ratios = json.loads(Path(args.ratios).read_text(encoding="utf-8"))

    rng = np.random.default_rng(args.seed)
    domain_names = manager.detected_domain_names
    selected_parts = []
    for domain_idx, name in enumerate(domain_names):
        mask = manager.domain_labels == domain_idx
        indices = np.nonzero(mask)[0]
        if len(indices) == 0:
            continue
        ratio = float(ratios.get(name, ratios.get(str(domain_idx), 0.0)))
        if ratio <= 0:
            continue
        n_select = max(1, int(len(indices) * ratio))
        chosen = rng.choice(indices, size=min(n_select, len(indices)), replace=False)
        selected_parts.append(chosen)

    selected = np.sort(np.concatenate(selected_parts)) if selected_parts else np.array([], dtype=np.int64)

    token_counts = manager.estimate_token_counts()
    if args.target_tokens > 0 and len(selected) > 0:
        cum = np.cumsum(token_counts[selected])
        cutoff = int(np.searchsorted(cum, args.target_tokens, side="right")) + 1
        selected = selected[:cutoff]

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    texts = manager.read_texts(selected) if len(selected) else []
    domains = manager.domain_labels[selected]

    import pandas as pd
    df = pd.DataFrame({schema.text_col: texts, schema.domain_col: domains})
    for i, col in enumerate(schema.quality_cols):
        df[col] = manager.quality_scores[selected, i]
    out_path = output / "sampled_dataset.parquet"
    df.to_parquet(out_path, index=False)

    summary = {
        "algorithm": "manual",
        "seed": args.seed,
        "ratios": ratios,
        "num_original_docs": int(manager.num_docs),
        "num_selected_docs": int(len(selected)),
        "selected_tokens": int(token_counts[selected].sum()) if len(selected) else 0,
        "output": str(out_path),
    }
    (output / "manual_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
