"""Example trusted manual strategy; selects larger documents first per domain."""

import numpy as np

STRATEGY_API_VERSION = "1"


def select(pool, context, config):
    descending = bool(config.get("descending", True))
    order = np.argsort(pool.estimated_tokens, kind="stable")
    if descending:
        order = order[::-1]
    cumulative = np.cumsum(pool.estimated_tokens[order])
    count = min(np.searchsorted(cumulative, context.token_budget, side="left") + 1, len(order))
    return order[:count]
