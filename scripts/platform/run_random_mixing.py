#!/usr/bin/env python3
"""Random uniform sampling baseline.

Selects documents uniformly at random from a preprocessed dataset until a target
token or document budget is reached. The output mirrors QuadMix's sampled
dataset layout so downstream trainers can consume it transparently.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

from quadmix.data.dataset_schema import DatasetSchema
from quadmix.data.metadata_manager import ShardMetadataManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Random uniform sampling baseline")
    parser.add_argument("--dataset", required=True, help="preprocessed dataset directory")
    parser.add_argument("--schema", required=True, help="YAML schema config")
    parser.add_argument("--output", required=True, help="output directory")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--target-tokens", type=int, default=0)
    parser.add_argument("--target-docs", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    schema = DatasetSchema.from_yaml(args.schema)
    manager = ShardMetadataManager(args.dataset, schema=schema)

    rng = np.random.default_rng(args.seed)
    n_docs = manager.num_docs
    token_counts = manager.estimate_token_counts()

    if args.target_tokens > 0:
        perm = rng.permutation(n_docs)
        cum_tokens = np.cumsum(token_counts[perm])
        cutoff = int(np.searchsorted(cum_tokens, args.target_tokens, side="right")) + 1
        selected = perm[: min(cutoff, n_docs)]
    elif args.target_docs > 0:
        selected = rng.choice(n_docs, size=min(args.target_docs, n_docs), replace=False)
    else:
        selected = rng.permutation(n_docs)

    selected = np.sort(selected)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    texts = manager.read_texts(selected)
    domains = manager.domain_labels[selected]

    import pandas as pd
    df = pd.DataFrame({
        schema.text_col: texts,
        schema.domain_col: domains,
    })
    for i, col in enumerate(schema.quality_cols):
        df[col] = manager.quality_scores[selected, i]
    out_path = output / "sampled_dataset.parquet"
    df.to_parquet(out_path, index=False)

    summary = {
        "algorithm": "random",
        "seed": args.seed,
        "num_original_docs": int(n_docs),
        "num_selected_docs": int(len(selected)),
        "selected_tokens": int(token_counts[selected].sum()),
        "output": str(out_path),
    }
    (output / "random_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
