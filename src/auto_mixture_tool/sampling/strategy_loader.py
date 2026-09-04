"""Load trusted, user-provided sampling strategies from mounted Python files.

Strategy files are trusted internal code.  They run in the training process and
receive numpy arrays without copying the complete dataset metadata.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

import numpy as np


@dataclass(frozen=True)
class CandidatePool:
    """Read-only candidate arrays; returned indices refer to these arrays."""

    shard_ids: np.ndarray
    document_ids: np.ndarray
    estimated_tokens: np.ndarray
    domain_ids: np.ndarray | None = None

    def __len__(self) -> int:
        return len(self.document_ids)


@dataclass(frozen=True)
class StrategyContext:
    method: str
    token_budget: int
    seed: int
    domain_name: str | None = None


def _load_module(path: str) -> ModuleType:
    source = Path(path)
    if not source.is_file() or source.suffix.lower() != ".py":
        raise ValueError(f"sampling strategy must be an existing .py file: {source}")
    spec = importlib.util.spec_from_file_location(
        f"auto_mixture_user_strategy_{abs(hash(source.resolve()))}", source
    )
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load sampling strategy: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if getattr(module, "STRATEGY_API_VERSION", None) != "1":
        raise ValueError(f"{source}: STRATEGY_API_VERSION must be '1'")
    if not callable(getattr(module, "select", None)):
        raise ValueError(f"{source}: callable select(pool, context, config) is required")
    return module


def select_indices(
    strategy_path: str | None,
    pool: CandidatePool,
    context: StrategyContext,
    config: Mapping[str, Any] | None = None,
) -> np.ndarray:
    """Run a custom strategy and validate its returned candidate indices."""

    if not strategy_path:
        raise ValueError("strategy_path is required")
    raw = _load_module(strategy_path).select(pool, context, dict(config or {}))
    indices = np.asarray(raw)
    if indices.ndim != 1 or not np.issubdtype(indices.dtype, np.integer):
        raise ValueError("strategy select() must return a one-dimensional integer sequence")
    indices = indices.astype(np.int64, copy=False)
    if len(indices) and (int(indices.min()) < 0 or int(indices.max()) >= len(pool)):
        raise ValueError("strategy returned an index outside the candidate pool")
    if len(np.unique(indices)) != len(indices):
        raise ValueError("strategy returned duplicate candidate indices")
    estimated = int(pool.estimated_tokens[indices].sum()) if len(indices) else 0
    if context.token_budget > 0 and estimated < int(context.token_budget * 0.9):
        raise ValueError(
            f"strategy selected about {estimated:,} tokens, below 90% of "
            f"the {context.token_budget:,} token budget"
        )
    return indices
