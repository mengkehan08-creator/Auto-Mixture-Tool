"""Scalable data sampling for QuaDMix — handles large datasets."""

from typing import Any

__all__ = [
    "sample_with_optimal_params",
]


def __getattr__(name: str) -> Any:
    if name == "sample_with_optimal_params":
        from quadmix.sampling.batch_sampler import sample_with_optimal_params

        return sample_with_optimal_params
    raise AttributeError(name)
