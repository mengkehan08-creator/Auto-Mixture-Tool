"""Canonical contract registry (Phase 2 backbone).

Maps ``id`` -> a concrete ``MixingAlgorithm`` / ``Trainer`` / ``Evaluator``
implementation of the Phase-1 interfaces. This is the object-level equivalent
of ``quadmix_platform.service.PlatformService``'s adapter registries, but for
the *canonical* (in-process / same-contract) components rather than the
command-emitting adapters.

Registries are built lazily inside ``build_canonical_registry()`` (never at
module import time) so heavy implementations (QuadMix / NanoChat / STEM, which
need numpy / pandas) are only imported when actually requested -- keeping the
standard-library reference path importable offline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from quadmix_platform.interfaces import Evaluator, MixingAlgorithm, Trainer
from quadmix_platform.registry import ComponentRegistry

if TYPE_CHECKING:
    from auto_mixture_tool.core.evaluation import StubEvaluator
    from auto_mixture_tool.core.mixing import ManualRatioMixingAlgorithm, RandomMixingAlgorithm
    from auto_mixture_tool.core.training import NoOpTrainer


def build_canonical_registry() -> dict[str, ComponentRegistry]:
    """Return a fresh dict of registries pre-populated with built-in components."""
    from auto_mixture_tool.core.evaluation import StubEvaluator
    from auto_mixture_tool.core.mixing import ManualRatioMixingAlgorithm, RandomMixingAlgorithm
    from auto_mixture_tool.core.nanochat_trainer import NanoChatTrainer
    from auto_mixture_tool.core.quadmix_algorithm import QuadMixMixingAlgorithm
    from auto_mixture_tool.core.stem_evaluator import STEMEvaluator
    from auto_mixture_tool.core.training import NoOpTrainer

    algorithms = ComponentRegistry[MixingAlgorithm]()
    algorithms.register(RandomMixingAlgorithm())
    algorithms.register(ManualRatioMixingAlgorithm())
    algorithms.register(QuadMixMixingAlgorithm())

    trainers = ComponentRegistry[Trainer]()
    trainers.register(NoOpTrainer())
    trainers.register(NanoChatTrainer())

    evaluators = ComponentRegistry[Evaluator]()
    evaluators.register(StubEvaluator())
    evaluators.register(STEMEvaluator())

    return {"algorithms": algorithms, "trainers": trainers, "evaluators": evaluators}


def get_algorithm(component_id: str) -> MixingAlgorithm:
    return build_canonical_registry()["algorithms"].get(component_id)


def get_trainer(component_id: str) -> Trainer:
    return build_canonical_registry()["trainers"].get(component_id)


def get_evaluator(component_id: str) -> Evaluator:
    return build_canonical_registry()["evaluators"].get(component_id)
