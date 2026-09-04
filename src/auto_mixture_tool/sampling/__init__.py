"""Sampling strategy extension points used by comparison baselines."""

from .strategy_loader import CandidatePool, StrategyContext, select_indices

__all__ = ["CandidatePool", "StrategyContext", "select_indices"]
