"""Plugin base classes for Auto-Mixture-Tool.

These are thin aliases around ``quadmix_platform.interfaces`` so the two
packages stay aligned. New plugins should subclass the adapters here and
implement the required ``build`` / ``environment`` / ``submit`` methods.
"""

from __future__ import annotations

from quadmix_platform.interfaces import (
    AlgorithmAdapter,
    Evaluator,
    ExecutorAdapter,
    FormatValidatorAdapter,
    MixingAlgorithm,
    Sample,
    Trainer,
    TrainerAdapter,
    UnifiedDataset,
    ValidatorAdapter,
)
from quadmix_platform.models import CommandSpec, JobRecord

# Canonical Phase-1 interfaces (the contract to stabilize before extracting
# QuadMix / NanoChat / STEM). ``*Adapter`` are the cluster-execution strategy.
__all__ = [
    "AlgorithmAdapter",
    "TrainerAdapter",
    "ValidatorAdapter",
    "ExecutorAdapter",
    "FormatValidatorAdapter",
    "MixingAlgorithm",
    "Trainer",
    "Evaluator",
    "UnifiedDataset",
    "Sample",
    "CommandSpec",
    "JobRecord",
]
