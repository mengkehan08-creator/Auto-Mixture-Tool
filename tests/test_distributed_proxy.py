from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from quadmix.core.types import ParameterSet, ProxyResult, QuaDMixConfig
from quadmix.pipeline.distributed_proxy import (
    DistributedProxyCoordinator,
    parameter_set_hash,
)
from quadmix.pipeline.param_sampler import ParameterSampler


class DistributedProxyTests(unittest.TestCase):
    def test_two_nodes_publish_and_primary_gathers_in_global_order(self) -> None:
        config = QuaDMixConfig(
            num_domains=2, num_quality_criteria=2, seed=42,
            sampler_method="uniform",
        )
        parameters = ParameterSampler(config, seed=42).sample_batch(4)
        digest = parameter_set_hash(parameters)
        with tempfile.TemporaryDirectory() as raw:
            root = str(Path(raw) / "coordination")
            nodes = [
                DistributedProxyCoordinator(root, rank, 2, backend="local")
                for rank in range(2)
            ]
            for node in nodes:
                results = []
                for index in node.local_indices(4):
                    results.append(ProxyResult(
                        parameters=parameters[index],
                        validation_loss=float(index),
                        metadata={"experiment_id": index},
                    ))
                node.publish_results(results, digest)

            gathered = nodes[0].gather_results(config, 4, digest)
            self.assertEqual(
                [result.metadata["experiment_id"] for result in gathered],
                [0, 1, 2, 3],
            )
            np.testing.assert_allclose(
                gathered[3].parameters.flatten(), parameters[3].flatten()
            )

    def test_parameter_hash_is_deterministic_for_fixed_seed(self) -> None:
        config = QuaDMixConfig(
            num_domains=2, num_quality_criteria=2, seed=7,
            sampler_method="uniform",
        )
        left = ParameterSampler(config, seed=7).sample_batch(4)
        right = ParameterSampler(config, seed=7).sample_batch(4)
        self.assertEqual(parameter_set_hash(left), parameter_set_hash(right))


if __name__ == "__main__":
    unittest.main()
