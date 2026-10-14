"""
QuaDMix: Quality-Diversity Balanced Data Selection for Efficient LLM Pretraining

Implementation of the QuaDMix algorithm from:
  "QuaDMix: Quality-Diversity Balanced Data Selection for Efficient LLM Pretraining"
  Fengze Liu, Weidong Zhou, Binbin Liu, et al. (ByteDance, 2025)

Key reference: arXiv:2504.16511v2
"""

from importlib import import_module

__version__ = "2.0.0"

# Keep the public API while avoiding eager imports of pandas/torch/lightgbm.
# Lightweight platform services can now use DatasetSchema without loading the
# complete training stack; algorithm classes are imported on first access.
_LAZY_EXPORTS = {
    "QualityScore": ("quadmix.core.types", "QualityScore"),
    "DomainLabel": ("quadmix.core.types", "DomainLabel"),
    "MergedQualityConfig": ("quadmix.core.types", "MergedQualityConfig"),
    "SamplingConfig": ("quadmix.core.types", "SamplingConfig"),
    "QuaDMixConfig": ("quadmix.core.types", "QuaDMixConfig"),
    "ParameterSet": ("quadmix.core.types", "ParameterSet"),
    "ProxyResult": ("quadmix.core.types", "ProxyResult"),
    "ParameterSampler": ("quadmix.pipeline.param_sampler", "ParameterSampler"),
    "QuaDMixOptimizer": ("quadmix.pipeline.optimizer", "QuaDMixOptimizer"),
    "BaseProxyRunner": ("quadmix.pipeline.proxy_runner", "BaseProxyRunner"),
    "QuaDMixPipeline": ("quadmix.pipeline.real_pipeline", "QuaDMixPipeline"),
    "DatasetSchema": ("quadmix.data.dataset_schema", "DatasetSchema"),
}


def __getattr__(name):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = _LAZY_EXPORTS[name]
    value = getattr(import_module(module_name), attribute)
    globals()[name] = value
    return value

__all__ = [
    "QualityScore", "DomainLabel",
    "MergedQualityConfig", "SamplingConfig",
    "QuaDMixConfig", "ParameterSet", "ProxyResult",
    "ParameterSampler", "QuaDMixOptimizer",
    "BaseProxyRunner", "QuaDMixPipeline",
    "DatasetSchema",
]
