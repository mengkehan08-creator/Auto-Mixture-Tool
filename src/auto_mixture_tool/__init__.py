"""Auto-Mixture-Tool: pluggable data mixing platform.

Public facade for the modular tool. The lower-level integration layer lives in
``quadmix_platform``; this package provides the user-facing CLI, API, pipeline
manager, and result analysis helpers.

``PlatformService`` / ``PipelineManager`` / ``ResultAnalyzer`` are exposed
lazily so that importing this package never triggers a circular import with
``quadmix_platform`` and never eagerly loads the numpy / pandas heavy path.
Use ``from auto_mixture_tool import PipelineManager`` etc. as before.
"""

from __future__ import annotations

__version__ = "0.1.0"


def __getattr__(name: str):
    if name == "PlatformService":
        from quadmix_platform.service import PlatformService

        return PlatformService
    if name == "PipelineManager":
        from .pipeline import PipelineManager

        return PipelineManager
    if name == "ResultAnalyzer":
        from .results.analysis import ResultAnalyzer

        return ResultAnalyzer
    if name == "CanonicalPipeline":
        from .core.pipeline import CanonicalPipeline

        return CanonicalPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["PipelineManager", "PlatformService", "ResultAnalyzer", "CanonicalPipeline"]
