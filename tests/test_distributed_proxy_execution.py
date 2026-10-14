"""Local node processes exercise real proxy training/evaluation without OBS or NPU."""
import json
import multiprocessing as mp
import os
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
import torch

from quadmix.core.proxy_model import ProxyConfig
from quadmix.core.types import ProxyResult, QuaDMixConfig
from quadmix.pipeline.distributed_proxy import DistributedProxyCoordinator
from quadmix.pipeline.essential_proxy_runner import EssentialWebProxyRunner
from quadmix.pipeline.param_sampler import ParameterSampler
from quadmix.pipeline.real_pipeline import QuaDMixPipeline
from quadmix.utils.concurrency import ConcurrencyConfig


class SmallProxyRunner(EssentialWebProxyRunner):
    def __init__(self, config, output_dir):
        # Tiny deterministic in-memory data; train/validate/save use the production methods.
        self.config = config
        self.output_dir = str(output_dir)
        self.device_type = "cpu"
        self.npu_device_id = 0
        self.model_variant = "test-small"
        self.model_config = ProxyConfig(n_layer=1, n_head=2, n_embd=16,
                                       vocab_size=32, block_size=8, intermediate_size=32)
        self.block_size = 8
        self.tiny_steps = 3
        self.max_step = 3
        self.global_batch_size = self.micro_batch_size = 2
        self.gradient_accumulation_steps = 1
        self.learning_rate = 0.01
        self.weight_decay = 0.1
        self.warmup_fraction = 0.04
        self.grad_clip = 1.0
        self.checkpoint_interval = 1
        self._seed_offset = config.seed
        self._concurrency = ConcurrencyConfig(cpu_count=1, max_compute_workers=1)
        self.metadata_manager = None
        self._mode = "legacy"
        self._domain_names = self._quality_names = None
        self.tokenizer = SimpleNamespace(pad_token_id=0, eos_token_id=1,
                                         get_vocab=lambda: {str(i): i for i in range(32)})
        self._num_docs = 128
        self._train_idx = np.arange(self._num_docs)
        self._normalized_quality = np.random.default_rng(19).random((self._num_docs, 2))
        self._domain_indices = {0: np.arange(64), 1: np.arange(64, 128)}
        self._token_counts = None
        self.rank_ref_size = 32
        self._val_token_ids = torch.tensor([[1, 2, 3, 4, 5, 6, 7, 8], [2, 4, 6, 8, 10, 12, 14, 16]])
        self._val_loss_mask = torch.ones_like(self._val_token_ids)
        self._val_task_labels = ["math", "physics"]

    def _load_tokens_for_experiment(self, selected_idx, **kwargs):
        return (torch.tensor(selected_idx).unsqueeze(1) + torch.arange(8)) % 31 + 1


def _array_descriptor(array, prefix):
    return SimpleNamespace(name="test-memory-" + prefix, array=array)


def _node_training(root, rank):
    torch.set_num_threads(1)
    config = QuaDMixConfig(num_domains=2, num_quality_criteria=2, seed=42, sampler_method="uniform")
    coordinator = DistributedProxyCoordinator(str(Path(root) / "coordination"), rank, 2,
                                              timeout_seconds=30, backend="local")
    with coordinator.failure_guard():
        parameters = ParameterSampler(config, seed=42).sample_batch(5)
        runner = SmallProxyRunner(config, Path(root) / f"node-{rank}/proxy_experiments")
        # The production shared-array attachment targets Linux; use arrays on local macOS.
        with patch("quadmix.pipeline.shared_memory.ndarray_to_shared", _array_descriptor), \
             patch("quadmix.pipeline.shared_memory.shared_to_ndarray", lambda info: info.array), \
             patch("torch.compile", lambda model, **kwargs: model):
            results, _ = QuaDMixPipeline(config)._stage4_proxy_experiments(
                runner, 5, parameters, 1, {}, coordinator,
            )
        if rank == 0:
            sampled = Path(runner.output_dir).parent / "sampled_dataset"
            sampled.mkdir(parents=True)
            (sampled / "data.json").write_text('{"ready": true}')
            (Path(root) / "gathered.json").write_text(json.dumps([
                {"id": r.metadata["experiment_id"], "loss": r.validation_loss,
                 "tasks": r.per_task_losses, "node": r.metadata["modelarts_node_rank"]}
                for r in results
            ]))
            coordinator.publish_final_output(sampled.parent)


def _dispatch_worker(worker_id, device_type, config, task_queue, result_queue):
    while (task := task_queue.get()) is not None:
        experiment_id, parameters = task[:2]
        # Finish in a different order from submission to exercise the collector mapping.
        time.sleep(0.01 if experiment_id % 2 else 0.05)
        result_queue.put(ProxyResult(parameters, float(experiment_id),
                                     metadata={"experiment_id": experiment_id}))
    result_queue.put(None)


def _crashing_worker(*args):
    os._exit(2)


def _hanging_worker(*args):
    time.sleep(120)


def _invalid_result_worker(worker_id, device_type, config, task_queue, result_queue):
    task = task_queue.get()
    result_queue.put(ProxyResult(task[1], 1.0, metadata={"experiment_id": 999}))
    result_queue.put(None)


def _duplicate_result_worker(worker_id, device_type, config, task_queue, result_queue):
    task = task_queue.get()
    result = ProxyResult(task[1], 1.0, metadata={"experiment_id": task[0]})
    result_queue.put(result)
    result_queue.put(result)
    result_queue.put(None)


def _dynamic_dispatch(root, failure):
    config = QuaDMixConfig(num_domains=2, num_quality_criteria=2, seed=42)
    runner = SmallProxyRunner(config, Path(root) / "proxy_experiments")
    runner._serialize_config = lambda *args: {}
    tokenized = []

    def tokenize(selected, ids, *args, **kwargs):
        tokenized.extend(ids)
        return {}

    runner._tokenize_batch_union = tokenize
    parameters = ParameterSampler(config, seed=42).sample_batch(3)
    worker = {None: _dispatch_worker, "crash": _crashing_worker,
              "hang": _hanging_worker, "invalid": _invalid_result_worker,
              "duplicate": _duplicate_result_worker, "launch": _dispatch_worker}[failure]
    launcher = (patch("multiprocessing.context.SpawnProcess.start", side_effect=OSError("process limit"))
                if failure == "launch" else nullcontext())
    with patch("quadmix.pipeline.essential_proxy_runner._worker_dynamic_loop", worker), launcher:
        try:
            results = runner.run_batch_parallel(parameters, [np.array([i]) for i in range(3)],
                num_workers=2, device_type="cpu", experiment_ids=[1, 3, 5],
                timeout_seconds=5 if failure == "hang" else None)
        except RuntimeError as error:
            (Path(root) / "dispatch.json").write_text(json.dumps({"error": str(error)}))
            return
    (Path(root) / "dispatch.json").write_text(json.dumps({
        "tokenized": tokenized, "results": [r.metadata for r in results],
    }))


def _join_processes(processes, timeout=45):
    deadline = time.monotonic() + timeout
    try:
        for process in processes:
            process.join(max(0, deadline - time.monotonic()))
        assert all(not p.is_alive() for p in processes), "distributed execution did not finish"
        assert [p.exitcode for p in processes] == [0] * len(processes)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)


def test_two_nodes_train_evaluate_and_preserve_global_ids(tmp_path):
    processes = [mp.get_context("spawn").Process(target=_node_training, args=(str(tmp_path), rank))
                 for rank in range(2)]
    for process in processes:
        process.start()
    _join_processes(processes)
    gathered = json.loads((tmp_path / "gathered.json").read_text())
    assert [r["id"] for r in gathered] == list(range(5))
    assert [r["node"] for r in gathered] == [0, 1, 0, 1, 0]
    assert all(np.isfinite(r["loss"]) and set(r["tasks"]) == {"math", "physics"} for r in gathered)
    assert (tmp_path / "node-1/sampled_dataset/data.json").is_file()
    all_results = json.loads((tmp_path / "coordination/proxy_results/all.json").read_text())
    assert [r["metadata"]["experiment_id"] for r in all_results["results"]] == list(range(5))
    assert all_results["run_hash"]

    config = QuaDMixConfig(num_domains=2, num_quality_criteria=2, seed=42, sampler_method="uniform")
    parameters = ParameterSampler(config, seed=42).sample_batch(5)
    reference = SmallProxyRunner(config, tmp_path / "reference/proxy_experiments")
    with patch("quadmix.pipeline.shared_memory.ndarray_to_shared", _array_descriptor), \
         patch("quadmix.pipeline.shared_memory.shared_to_ndarray", lambda info: info.array), \
         patch("torch.compile", lambda model, **kwargs: model):
        results, _ = QuaDMixPipeline(config)._stage4_proxy_experiments(reference, 5, parameters, 1, {})
    for index, result in enumerate(results):
        directory = tmp_path / f"node-{index % 2}/proxy_experiments/exp_{index:04d}"
        meta = json.loads((directory / "meta.json").read_text())
        assert meta["experiment_id"] == index and meta["seed"] == 42 + index
        assert meta["num_steps"] == 3
        assert (directory / "model.pt").is_file()
        assert (directory / "checkpoint_trajectory.json").is_file()
        published = tmp_path / f"coordination/proxy_experiments/exp_{index:04d}"
        published_meta = json.loads((published / "meta.json").read_text())
        assert published_meta["run_hash"] == all_results["run_hash"]
        assert published_meta["modelarts_node_rank"] == index % 2
        assert published_meta["artifact_uri"] == str(published)
        assert (published / "checkpoint_trajectory.json").is_file()
        weights = torch.load(published / "model.pt", weights_only=True)
        reference_weights = torch.load(tmp_path / f"reference/proxy_experiments/exp_{index:04d}/model.pt",
                                       weights_only=True)
        for key in weights:
            torch.testing.assert_close(weights[key], reference_weights[key])
        np.testing.assert_array_equal(np.load(directory / "selected_indices.npy"),
                                      np.load(tmp_path / f"reference/proxy_experiments/exp_{index:04d}/selected_indices.npy"))
        assert gathered[index]["loss"] == pytest.approx(result.validation_loss, abs=1e-6)
        assert gathered[index]["tasks"] == pytest.approx(result.per_task_losses, abs=1e-6)


@pytest.mark.parametrize("failure", [None, "crash", "hang", "invalid", "duplicate", "launch"])
def test_dynamic_workers_use_global_ids_and_exit_on_failure(tmp_path, failure):
    process = mp.get_context("spawn").Process(target=_dynamic_dispatch, args=(str(tmp_path), failure))
    process.start()
    _join_processes([process], timeout=30)
    value = json.loads((tmp_path / "dispatch.json").read_text())
    if failure in ("invalid", "duplicate", "launch"):
        expected = {"invalid": "unexpected result for experiment 999",
                    "duplicate": "duplicate result for experiment", "launch": "launch failed"}[failure]
        assert expected in value["error"]
        return
    assert value["tokenized"] == [1, 3, 5]
    assert [r["experiment_id"] for r in value["results"]] == [1, 3, 5]
    if failure:
        expected = "worker_crash" if failure == "crash" else "execution_timeout"
        assert all(r.get("error") == expected for r in value["results"])
    else:
        assert all("error" not in r for r in value["results"])


def test_cli_notifies_other_nodes_when_resource_loading_fails(tmp_path, monkeypatch):
    from scripts.runners import run_essential_web_v1 as entrypoint
    args = SimpleNamespace(distributed_nodes=2, node_rank=1,
                           coordination_uri=str(tmp_path), coordination_timeout=1)
    monkeypatch.setenv("AMT_OBS_BACKEND", "local")
    monkeypatch.setattr(entrypoint, "build_parser", lambda: SimpleNamespace(parse_args=lambda: args))
    with patch.object(entrypoint, "run_pipeline", side_effect=FileNotFoundError("validation missing")):
        with pytest.raises(FileNotFoundError, match="validation missing"):
            entrypoint.main()
    primary = DistributedProxyCoordinator(str(tmp_path), 0, 2, backend="local")
    with pytest.raises(RuntimeError, match="node-1.*validation missing"):
        primary.wait_and_download_final_output(tmp_path / "output")


@pytest.mark.parametrize("environment,nodes,rank,error", [
    ({"AMT_EXPECTED_NODES": "2"}, None, None, "AMT_EXPECTED_NODES"),
    ({"MA_NUM_HOSTS": "2"}, 1, 0, "MA_NUM_HOSTS"),
    ({"MA_NUM_HOSTS": "2"}, None, None, "node-rank"),
    ({"MA_NUM_HOSTS": "2", "VC_TASK_INDEX": "1"}, 2, 0, "VC_TASK_INDEX"),
])
def test_cli_rejects_incomplete_or_inconsistent_node_identity(monkeypatch, environment, nodes, rank, error):
    from scripts.runners import run_essential_web_v1 as entrypoint
    for key in ("AMT_EXPECTED_NODES", "MA_NUM_HOSTS", "VC_TASK_INDEX"):
        monkeypatch.delenv(key, raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    args = SimpleNamespace(distributed_nodes=nodes, node_rank=rank)
    monkeypatch.setattr(entrypoint, "build_parser", lambda: SimpleNamespace(parse_args=lambda: args))
    with patch.object(entrypoint, "run_pipeline") as run, pytest.raises(ValueError, match=error):
        entrypoint.main()
    run.assert_not_called()


def test_manifest_tracks_effective_inputs_and_training_budget(tmp_path):
    config = QuaDMixConfig(num_domains=2, num_quality_criteria=2, seed=42)
    left = SmallProxyRunner(config, tmp_path / "left/proxy_experiments")
    right = SmallProxyRunner(config, tmp_path / "right/proxy_experiments")
    assert left.distributed_manifest() == right.distributed_manifest()
    right._val_token_ids[0, 0] += 1
    assert left.distributed_manifest()["validation"] != right.distributed_manifest()["validation"]
    right.tiny_steps += 1
    assert left.distributed_manifest()["training"] != right.distributed_manifest()["training"]
    right._normalized_quality[0, 0] += 1
    assert left.distributed_manifest()["dataset"] != right.distributed_manifest()["dataset"]


def test_manifest_accepts_identical_shards_at_different_mount_paths(tmp_path):
    from quadmix.data.dataset_schema import DatasetSchema
    from quadmix.data.metadata_manager import ShardMetadataManager
    schema = DatasetSchema(domain_col="domain", text_col="text", quality_cols=["q1", "q2"],
                           quality_directions=[True, True], domain_names=["math", "physics"],
                           char_count_col="chars", row_in_shard_col="row")
    rows = [{"domain": "math" if i % 2 else "physics", "text": f"document {i}",
             "q1": 0.2, "q2": 0.8, "chars": 10, "row": i} for i in range(6)]
    runners = []
    config = QuaDMixConfig(num_domains=2, num_quality_criteria=2, seed=42)
    for name in ("first-mount", "second-mount"):
        path = tmp_path / name
        path.mkdir()
        content = "\n".join(json.dumps(row) for row in rows)
        (path / "part-a.jsonl").write_text(content)
        (path / "part-b.jsonl").write_text("[]")
        (path / "part-c.jsonl").write_text(content)
        runner = SmallProxyRunner(config, path / "output/proxy_experiments")
        runner.metadata_manager = ShardMetadataManager(str(path), schema=schema, max_workers=1)
        assert runner.metadata_manager.shard_info[1]["num_docs"] == 0
        runners.append(runner)
    assert runners[0].distributed_manifest() == runners[1].distributed_manifest()
    runners[1].metadata_manager.doc_char_counts[0] += 1
    assert runners[0].distributed_manifest()["dataset"] != runners[1].distributed_manifest()["dataset"]


@pytest.mark.parametrize("settings", [
    {"algorithm_nodes": 2}, {"coordination_timeout": 0}, {"coordination_timeout": -1},
    {"coordination_timeout": float("nan")}, {"coordination_timeout": float("inf")},
])
def test_algorithm_adapter_rejects_invalid_distributed_settings(settings, tmp_path):
    from auto_mixture_tool.plugins.algorithms.quadmix import QuadMixAlgorithm
    with pytest.raises(ValueError):
        QuadMixAlgorithm().build({"dataset_uri": "data", "schema_uri": "schema",
                                  "output_uri": "output", "algorithm_config": settings}, tmp_path)
