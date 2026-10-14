"""Proxy experiment runner base class for QuaDMix.

The actual proxy runner is implemented in src/quadmix/pipeline/essential_proxy_runner.py.
This module provides the abstract interface.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Callable

from quadmix.core.types import ParameterSet, ProxyResult


def resolve_experiment_ids(count: int, experiment_ids: Optional[List[int]] = None) -> List[int]:
    ids = list(range(count)) if experiment_ids is None else list(experiment_ids)
    if (len(ids) != count or any(type(index) is not int or index < 0 for index in ids)
            or len(set(ids)) != count):
        raise ValueError("experiment_ids must contain one unique non-negative integer per experiment")
    return ids


class BaseProxyRunner(ABC):
    """Abstract base class for proxy experiment runners."""

    @abstractmethod
    def run_experiment(
        self,
        params: ParameterSet,
        experiment_id: int = 0,
    ) -> ProxyResult:
        """Run a single proxy experiment.

        Args:
            params: QuaDMix parameter configuration.
            experiment_id: Index for tracking.

        Returns:
            ProxyResult with validation loss.
        """
        ...

    def run_batch(
        self,
        params_list: List[ParameterSet],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        experiment_ids: Optional[List[int]] = None,
    ) -> List[ProxyResult]:
        """Run multiple proxy experiments.

        Args:
            params_list: List of parameter configurations.
            progress_callback: Optional callback(current, total).

        Returns:
            List of ProxyResult instances.
        """
        results = []
        ids = resolve_experiment_ids(len(params_list), experiment_ids)
        for i, (experiment_id, params) in enumerate(zip(ids, params_list)):
            result = self.run_experiment(params, experiment_id=experiment_id)
            results.append(result)
            if progress_callback:
                progress_callback(i + 1, len(params_list))
        return results
