"""Example trusted random strategy: shuffle shorter documents first by bucket."""

import numpy as np

STRATEGY_API_VERSION = "1"


def select(pool, context, config):
    rng = np.random.default_rng(context.seed)
    bucket_size = int(config.get("bucket_size", 2048))
    order = np.argsort(pool.estimated_tokens, kind="stable")
    chunks = [order[i : i + bucket_size].copy() for i in range(0, len(order), bucket_size)]
    for chunk in chunks:
        rng.shuffle(chunk)
    ranked = np.concatenate(chunks) if chunks else np.array([], dtype=np.int64)
    cumulative = np.cumsum(pool.estimated_tokens[ranked])
    count = min(np.searchsorted(cumulative, context.token_budget, side="left") + 1, len(ranked))
    return ranked[:count]
