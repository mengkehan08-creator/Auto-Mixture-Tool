from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from quadmix.pipeline.essential_proxy_runner import EssentialWebProxyRunner
from quadmix.pipeline.parallel_dispatch import _worker_dynamic_loop


class ProxyWorkerConfigTests(unittest.TestCase):
    def test_serialized_config_keeps_local_tokenizer_path(self) -> None:
        metadata = SimpleNamespace(
            _dir="/data",
            shard_info=[],
            num_domains=4,
            num_quality_criteria=5,
            detected_domain_names=[],
            detected_quality_names=[],
            quality_directions=[],
            domain_label_map={},
            schema=None,
        )
        runner = EssentialWebProxyRunner.__new__(EssentialWebProxyRunner)
        attributes = {
            "config": object(),
            "val_data_path": "/validation/stem_v2_tokenized.pt",
            "metadata_manager": metadata,
            "output_dir": "/output",
            "device_type": "npu",
            "model_variant": "tinyllama_1M",
            "global_batch_size": 8,
            "micro_batch_size": 2,
            "max_step": 3,
            "warmup_fraction": 0.04,
            "learning_rate": 4e-4,
            "weight_decay": 0.1,
            "grad_clip": 1.0,
            "tiny_steps": 10,
            "doc_limit": None,
            "block_size": 2048,
            "rank_ref_size": 10000,
            "checkpoint_interval": 1000,
            "token_cache_dir": "/cache",
            "tokenizer_path": "/inputs/quadmix_tokenizer_dir_4",
            "_domain_names": [],
            "_quality_names": [],
            "_quality_directions": [],
        }
        runner.__dict__.update(attributes)

        serialized = runner._serialize_config()

        self.assertEqual(
            serialized["tokenizer_path"],
            "/inputs/quadmix_tokenizer_dir_4",
        )

    @mock.patch("builtins.open", mock.mock_open())
    @mock.patch("quadmix.pipeline.essential_proxy_runner.EssentialWebProxyRunner")
    def test_worker_passes_serialized_tokenizer_path(self, runner: mock.Mock) -> None:
        task_queue = mock.Mock()
        task_queue.get.return_value = None
        result_queue = mock.Mock()
        config = {
            "config": object(),
            "preprocessed_dir": None,
            "val_data_path": "/validation/stem_v2_tokenized.pt",
            "output_dir": "/output",
            "model_variant": "tinyllama_1M",
            "global_batch_size": 8,
            "micro_batch_size": 2,
            "max_step": 3,
            "learning_rate": 4e-4,
            "weight_decay": 0.1,
            "grad_clip": 1.0,
            "tiny_steps": 10,
            "doc_limit": None,
            "test_block_size": 2048,
            "rank_ref_size": 10000,
            "token_cache_dir": "/cache",
            "tokenizer_path": "/inputs/quadmix_tokenizer_dir_4",
        }

        _worker_dynamic_loop(0, "cpu", config, task_queue, result_queue)

        self.assertEqual(
            runner.call_args.kwargs["tokenizer_path"],
            "/inputs/quadmix_tokenizer_dir_4",
        )
        result_queue.put.assert_called_once_with(None)


if __name__ == "__main__":
    unittest.main()
