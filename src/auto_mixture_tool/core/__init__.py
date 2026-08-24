"""Phase 1 canonical building blocks.

These implement the four core interfaces defined in
``quadmix_platform.interfaces`` so the contract is usable *before* the real
QuadMix / NanoChat / STEM code is extracted into it (Phase 2).

- :mod:`core.dataset`   -- Unified Dataset Interface (Layer 5)
- :mod:`core.mixing`    -- MixingAlgorithm reference + command bridge (Layer 6)
- :mod:`core.training`  -- Trainer reference + command bridge (Layer 7a)
- :mod:`core.evaluation`-- Evaluator reference + command bridge (Layer 7b)
"""

from auto_mixture_tool.core.dataset import (
    CsvJsonlDataset,
    PlanDataset,
    Sample,
    UnifiedDataset,
    load_dataset,
    write_samples,
)
from auto_mixture_tool.core.evaluation import (
    CommandDrivenEvaluator,
    Evaluator,
    StubEvaluator,
)
from auto_mixture_tool.core.stem_evaluator import STEMEvaluator
from auto_mixture_tool.core.mixing import (
    CommandDrivenMixingAlgorithm,
    ManualRatioMixingAlgorithm,
    MixingAlgorithm,
    RandomMixingAlgorithm,
)
from auto_mixture_tool.core.quadmix_algorithm import QuadMixMixingAlgorithm
from auto_mixture_tool.core.registry import (
    build_canonical_registry,
    get_algorithm,
    get_evaluator,
    get_trainer,
)
from auto_mixture_tool.core.training import (
    CommandDrivenTrainer,
    NoOpTrainer,
    Trainer,
)
from auto_mixture_tool.core.nanochat_trainer import NanoChatTrainer
from auto_mixture_tool.core.pipeline import CanonicalPipeline

__all__ = [
    "Sample",
    "UnifiedDataset",
    "CsvJsonlDataset",
    "PlanDataset",
    "load_dataset",
    "write_samples",
    "MixingAlgorithm",
    "RandomMixingAlgorithm",
    "ManualRatioMixingAlgorithm",
    "QuadMixMixingAlgorithm",
    "CommandDrivenMixingAlgorithm",
    "Trainer",
    "NoOpTrainer",
    "NanoChatTrainer",
    "CommandDrivenTrainer",
    "Evaluator",
    "StubEvaluator",
    "STEMEvaluator",
    "CommandDrivenEvaluator",
    "CanonicalPipeline",
    "build_canonical_registry",
    "get_algorithm",
    "get_trainer",
    "get_evaluator",
]
