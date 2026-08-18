"""Algorithm plugins for data mixing / selection."""

from auto_mixture_tool.plugins.algorithms.manual import ManualRatioAlgorithm
from auto_mixture_tool.plugins.algorithms.quadmix import QuadMixAlgorithm
from auto_mixture_tool.plugins.algorithms.random import RandomAlgorithm

__all__ = ["QuadMixAlgorithm", "RandomAlgorithm", "ManualRatioAlgorithm"]
