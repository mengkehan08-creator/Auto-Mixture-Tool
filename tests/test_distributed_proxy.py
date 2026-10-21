from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from unittest import mock
from concurrent.futures import ThreadPoolExecutor

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

    def test_gather_rejects_wrong_ownership_and_evaluation_tasks(self) -> None:
        config = QuaDMixConfig(num_domains=2, num_quality_criteria=2, seed=42)
        parameters = ParameterSampler(config, seed=42).sample_batch(2)
        digest = parameter_set_hash(parameters)
        with tempfile.TemporaryDirectory() as root:
            nodes = [DistributedProxyCoordinator(root, rank, 2, backend="local") for rank in range(2)]
            for rank, node in enumerate(nodes):
                node.publish_results([ProxyResult(
                    parameters[rank], float(rank), metadata={"experiment_id": rank},
                    per_task_losses={"math" if rank == 0 else "physics": float(rank)},
                )], digest)
            with self.assertRaisesRegex(RuntimeError, "评估任务"):
                nodes[0].gather_results(config, 2, digest)

            path = Path(root) / "proxy_results/node-1.json"
            payload = json.loads(path.read_text())
            for invalid_ids in ([0], [1, 1], []):
                with self.subTest(ids=invalid_ids):
                    payload["results"] = [{**payload["results"][0], "metadata": {"experiment_id": i}}
                                          for i in invalid_ids]
                    path.write_text(json.dumps(payload))
                    with self.assertRaisesRegex(RuntimeError, "编号"):
                        nodes[0].gather_results(config, 2, digest)
                    # Restore the one valid result for the next malformed payload.
                    payload["results"] = [{"parameters": parameters[1].flatten().tolist(),
                                           "validation_loss": 1, "metadata": {"experiment_id": 1}}]

    def test_failure_reaches_gather_and_final_output_wait(self) -> None:
        config = QuaDMixConfig(num_domains=2, num_quality_criteria=2)
        with tempfile.TemporaryDirectory() as root:
            nodes = [DistributedProxyCoordinator(root, rank, 2, backend="local") for rank in range(2)]
            with self.assertRaisesRegex(FileNotFoundError, "validation missing"):
                with nodes[1].failure_guard():
                    raise FileNotFoundError("validation missing")
            with mock.patch("quadmix.pipeline.distributed_proxy.time.sleep") as sleep:
                with self.assertRaisesRegex(RuntimeError, "node-1.*validation missing"):
                    nodes[0].gather_results(config, 2, "hash")
                with self.assertRaisesRegex(RuntimeError, "node-1.*validation missing"):
                    nodes[0].wait_and_download_final_output(Path(root) / "output")
                sleep.assert_not_called()

    def test_short_timeout_and_invalid_timeouts(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            for timeout in (0, -1, float("inf"), float("nan")):
                with self.assertRaises(ValueError):
                    DistributedProxyCoordinator(root, 0, 2, timeout, backend="local")
            node = DistributedProxyCoordinator(root, 0, 2, 0.01, backend="local")
            with self.assertRaises(TimeoutError):
                node.wait_and_download_final_output(Path(root) / "output")

    def test_nodes_agree_before_training_and_reject_reused_run(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            nodes = [DistributedProxyCoordinator(root, rank, 2, 2, backend="local") for rank in range(2)]
            manifest = {"dataset": "v1", "training": {"steps": 3}, "shape": (2, 8)}
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(node.verify_run, manifest) for node in nodes]
                for future in futures:
                    future.result(timeout=3)
            self.assertEqual(nodes[0].run_hash, nodes[1].run_hash)
            self.assertEqual(json.loads((Path(root) / "run_manifest.json").read_text())["training"],
                             {"steps": 3})
            with self.assertRaisesRegex(RuntimeError, "协调目录已被使用"):
                DistributedProxyCoordinator(root, 0, 2, backend="local").verify_run(manifest)

    def test_input_or_budget_mismatch_notifies_both_nodes(self) -> None:
        manifest = {key: "same" for key in ("dataset", "tokenizer", "validation", "model", "training")}
        for changed in manifest:
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as root:
                nodes = [DistributedProxyCoordinator(root, rank, 2, 2, backend="local") for rank in range(2)]

                def verify(rank):
                    with nodes[rank].failure_guard():
                        nodes[rank].verify_run(manifest if rank == 0 else {**manifest, changed: "different"})

                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(verify, rank) for rank in range(2)]
                    for future in futures:
                        with self.assertRaisesRegex(RuntimeError, "运行配置不一致"):
                            future.result(timeout=3)
                self.assertFalse((Path(root) / "manifests/_SUCCESS").exists())
                self.assertTrue((Path(root) / "failures/node-0.json").exists())

    def test_failed_or_nonfinite_metrics_are_never_published_as_success(self) -> None:
        config = QuaDMixConfig(num_domains=2, num_quality_criteria=2, seed=42)
        parameter = ParameterSampler(config, seed=42).sample_batch(1)[0]
        for loss, metadata, tasks in [
            (float("nan"), {}, None), (float("inf"), {}, None),
            (1.0, {"train_loss": float("nan")}, None),
            (1.0, {"val_loss": 2.0}, None),
            (1.0, {}, {"math": None}), (1.0, {}, {"math": float("inf")}),
            (1.0, {"error": "worker_crash"}, None),
        ]:
            with self.subTest(loss=loss, metadata=metadata, tasks=tasks), tempfile.TemporaryDirectory() as root:
                node = DistributedProxyCoordinator(root, 0, 2, backend="local")
                with self.assertRaises(RuntimeError):
                    node.publish_results([ProxyResult(parameter, loss,
                        metadata={"experiment_id": 0, **metadata}, per_task_losses=tasks)], "hash")
                self.assertFalse((Path(root) / "proxy_results/node-0._SUCCESS").exists())

    def test_gather_checks_actual_parameters_and_metrics(self) -> None:
        config = QuaDMixConfig(num_domains=2, num_quality_criteria=2, seed=42)
        parameters = ParameterSampler(config, seed=42).sample_batch(2)
        digest = parameter_set_hash(parameters)
        with tempfile.TemporaryDirectory() as root:
            nodes = [DistributedProxyCoordinator(root, rank, 2, backend="local") for rank in range(2)]
            for rank, node in enumerate(nodes):
                node.publish_results([ProxyResult(parameters[rank], float(rank),
                                                  metadata={"experiment_id": rank})], digest)
            path = Path(root) / "proxy_results/node-1.json"
            original = json.loads(path.read_text())
            for field, invalid, error in [("parameters", parameters[0].flatten().tolist(), "实际参数"),
                                          ("validation_loss", None, "无效指标")]:
                payload = json.loads(json.dumps(original))
                payload["results"][0][field] = invalid
                path.write_text(json.dumps(payload))
                with self.assertRaisesRegex(RuntimeError, error):
                    nodes[0].gather_results(config, 2, digest)

    def test_missing_artifacts_notify_other_nodes(self) -> None:
        config = QuaDMixConfig(num_domains=2, num_quality_criteria=2, seed=42)
        parameters = ParameterSampler(config, seed=42).sample_batch(2)
        with tempfile.TemporaryDirectory() as root:
            nodes = [DistributedProxyCoordinator(root, rank, 2, backend="local") for rank in range(2)]
            with self.assertRaises(FileNotFoundError), nodes[1].failure_guard():
                nodes[1].publish_results([ProxyResult(parameters[1], 1.0, metadata={"experiment_id": 1})],
                                         parameter_set_hash(parameters), Path(root) / "missing")
            with self.assertRaisesRegex(RuntimeError, "node-1.*缺少训练产物"):
                nodes[0].gather_results(config, 2, parameter_set_hash(parameters))


if __name__ == "__main__":
    unittest.main()
