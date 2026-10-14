"""Same-model multi-node launch, checkpoint handoff and global evaluation."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import socket
import secrets
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from nanochat_mid_compare.distributed_runtime import (
    Topology, checkpoint_manifest, resolve_topology, sync_checkpoint, validate_training_data,
)


def node_env(**extra):
    return dict(MA_NUM_HOSTS="2", VC_TASK_INDEX="1", VC_WORKER_HOSTS="10.0.0.1,10.0.0.2",
                AMT_RUN_ID="one-job", **extra)


def test_modelarts_and_explicit_launch_settings():
    topology = resolve_topology(8, node_env(AMT_EXPECTED_NODES="2"))
    assert topology == Topology(2, 1, 8, "10.0.0.1", 29500)
    assert topology.world_size == 16
    assert "--rdzv_endpoint=10.0.0.1:29501" in topology.torchrun_args(evaluation=True)
    explicit = {"NNODES": "3", "NODE_RANK": "2", "MASTER_ADDR": "worker-0", "MASTER_PORT": "30500", "AMT_RUN_ID": "job"}
    assert resolve_topology(1, explicit) == Topology(3, 2, 1, "worker-0", 30500)
    assert resolve_topology(1, {}) == Topology(1, 0, 1, "127.0.0.1", 29500)


@pytest.mark.parametrize("changes,error", [
    ({"VC_TASK_INDEX": ""}, "requires NODE_RANK"),
    ({"VC_TASK_INDEX": "2"}, "outside"),
    ({"NODE_RANK": "0"}, "Conflicting"),
    ({"MA_NUM_HOSTS": "0"}, "Invalid node/device count"),
    ({"AMT_EXPECTED_NODES": "3"}, "expected=3"),
    ({"MASTER_PORT": "65534"}, "Invalid master"),
    ({"AMT_RUN_ID": ""}, "AMT_RUN_ID"),
    ({"VC_WORKER_HOSTS": ""}, "requires NODE_RANK"),
])
def test_bad_topology_fails_before_torchrun(changes, error):
    env = node_env()
    env.update(changes)
    with pytest.raises(ValueError, match=error):
        resolve_topology(8, env, hostname="laptop")


def test_climb_statefulset_dns_fallback(tmp_path):
    hosts = tmp_path / "hosts"
    hosts.write_text("10.0.0.4 job-worker-3.job.namespace.svc.cluster.local job-worker-3\n"
                     "10.0.0.1 job-worker-0.job.namespace.svc.cluster.local\n")
    topology = resolve_topology(8, {"MA_NUM_HOSTS": "4", "AMT_RUN_ID": "job"},
                                hostname="job-worker-3", hosts_file=hosts)
    assert topology == Topology(4, 3, 8, "10.0.0.1", 29500)
    # The configured job node count is sufficient when the platform doesn't
    # expose MA_NUM_HOSTS (the situation exercised by Climb's DNS fallback).
    assert resolve_topology(8, {"AMT_EXPECTED_NODES": "4", "AMT_RUN_ID": "job"},
                            hostname="job-worker-3", hosts_file=hosts) == topology


def test_platform_run_id_and_training_world_size_reach_sampling(monkeypatch, tmp_path):
    from auto_mixture_tool.plugins.trainers.nanochat import NanoChatTrainer
    monkeypatch.setenv("AMT_RUN_ID", "platform-job")
    request = {"job_id": "node-local-request", "dataset_uri": "/data", "schema_uri": "/schema",
               "trainer_config": {"data_world_size": 32}}
    command = NanoChatTrainer().build(request, tmp_path)[0]
    assert command.env["AMT_RUN_ID"] == "platform-job"
    assert command.env["AMT_DATA_WORLD_SIZE"] == "32"


def test_preparation_uses_training_nodes_instead_of_mixing_nodes(tmp_path, monkeypatch):
    from auto_mixture_tool.modelarts import stage_runner
    from auto_mixture_tool.pipeline import PipelineManager
    monkeypatch.setattr(stage_runner, "OUTPUT", tmp_path)
    config = {"training_nodes": 4, "training": {"devices_per_node": 8},
              "strategies": [{"id": "quadmix", "type": "quadmix"}]}
    with patch.object(PipelineManager, "submit", return_value={"status": "SUCCEEDED"}) as submit:
        stage_runner.run_mixing(config)
    assert submit.call_args.args[0]["trainer_config"]["data_world_size"] == 32


def test_nonmaster_with_explicit_rank_does_not_publish_primary_artifacts(tmp_path, monkeypatch):
    from auto_mixture_tool.modelarts import stage_runner, evaluation_job
    for key in ("MA_NUM_HOSTS", "VC_TASK_INDEX", "MA_NODE_RANK", "VC_NODE_RANK", "AMT_EXPECTED_NODES"):
        monkeypatch.delenv(key, raising=False)
    for key, value in {"NNODES": "2", "NODE_RANK": "1", "MASTER_ADDR": "127.0.0.1", "AMT_RUN_ID": "job"}.items():
        monkeypatch.setenv(key, value)
    config = {"split_evaluation": True, "training": {}, "evaluation": {"datasets": []},
              "strategies": [{"id": "random", "type": "random"}]}
    (tmp_path / "random_data").mkdir()
    (tmp_path / "random_data/part.parquet").touch()
    with patch.object(stage_runner, "_prepared_data_dir", return_value=tmp_path), \
            patch.object(stage_runner.subprocess, "run") as run, \
            patch.object(evaluation_job, "publish_models") as publish:
        stage_runner.run_training(config)
    run.assert_called_once()
    publish.assert_not_called()


def test_row_groups_must_cover_every_global_rank(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    table = pa.table({"text": ["one", "two"]})
    for i in range(4):
        pq.write_table(table, tmp_path / f"shard_{i:05d}.parquet", row_group_size=2)
    # dev-data-mix deals groups across files, leaving the final file for val.
    validate_training_data(tmp_path, 2)
    with pytest.raises(ValueError, match="Training row groups.*WORLD_SIZE=4"):
        validate_training_data(tmp_path, 4)
    with pytest.raises(ValueError, match="Validation row groups"):
        validate_training_data(tmp_path, 2, validation=True)


def test_training_shards_cannot_be_empty_corrupt_or_missing_text(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    pq.write_table(pa.table({'text': pa.array([], type=pa.string())}), tmp_path / 'shard_00000.parquet')
    pq.write_table(pa.table({'text': ['val']}), tmp_path / 'shard_99999.parquet')
    with pytest.raises(ValueError, match='Training row groups'):
        validate_training_data(tmp_path, 1)
    pq.write_table(pa.table({'other': ['x']}), tmp_path / 'shard_00000.parquet')
    with pytest.raises(ValueError, match='Invalid training shard'):
        validate_training_data(tmp_path, 1)
    (tmp_path / 'shard_00000.parquet').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='Invalid training shard'):
        validate_training_data(tmp_path, 1)


def test_general_data_mixing_preserves_multi_node_row_group_coverage(tmp_path, monkeypatch):
    import importlib.util
    from types import SimpleNamespace
    import pyarrow as pa
    import pyarrow.parquet as pq
    source, output = tmp_path / "stem", tmp_path / "mixed"
    source.mkdir()
    for i in range(2):
        pq.write_table(pa.table({"text": ["stem"] * 64}), source / f"shard_{i:05d}.parquet", row_group_size=1)
    general = tmp_path / "general.parquet"
    pq.write_table(pa.table({"text": ["general"] * 64}), general)
    def stream(paths):
        for path in paths:
            yield from pq.read_table(path)["text"].to_pylist()
    monkeypatch.setitem(sys.modules, "nanochat.dataset", SimpleNamespace(
        stream_texts_uniform=stream, download_single_file=None, index_to_filename=None, MAX_SHARD=0))
    monkeypatch.setenv("RANK_SIZE", "32")
    with patch.object(sys, "path", list(sys.path)):
        spec = importlib.util.spec_from_file_location("mixing_fixture", Path(__file__).resolve().parents[1] / "nanochat_mid_compare/mix_general_data.py")
        mixing = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mixing)
        mixing.mix_data(source, [str(general)], output, num_output_files=2, batch_per_file=64)
    validate_training_data(output, 32)
    assert sum(pq.ParquetFile(path).metadata.num_rows for path in sorted(output.glob("*.parquet"))[:-1]) == 128


def free_port_triplet():
    for _ in range(30):
        sockets = []
        try:
            first = socket.socket()
            sockets.append(first)
            # Keep rendezvous ports below the OS ephemeral range: a train or
            # relay client could otherwise take port+1 before eval binds it.
            port = 20000 + secrets.randbelow(9000)
            first.bind(("127.0.0.1", port))
            for extra in (1, 2):
                peer = socket.socket()
                sockets.append(peer)
                peer.bind(("127.0.0.1", port + extra))
            return port
        except OSError:
            continue
        finally:
            for connection in sockets:
                connection.close()
    raise RuntimeError("No free local port triplet")


def checkpoints(root):
    root.mkdir()
    (root / "model_000005.pt").write_bytes(b"weights" * 300000)
    (root / "meta_000005.json").write_text('{"step":5}')
    (root / "optim_000005_rank0.pt").write_bytes(b"do not relay optimizer")


def relay_pair(source, target, *, job="one-job", timeout=5):
    port = free_port_triplet()
    topologies = [Topology(2, rank, 1, "127.0.0.1", port) for rank in range(2)]
    with ThreadPoolExecutor(max_workers=2) as workers:
        master = workers.submit(sync_checkpoint, source, topologies[0], "one-job", "mid:model", timeout=timeout)
        peer = workers.submit(sync_checkpoint, target, topologies[1], job, "mid:model", timeout=timeout)
        return master, peer


def test_relay_copies_only_matching_model_and_meta_atomically(tmp_path):
    source, target = tmp_path / "node0", tmp_path / "node1"
    checkpoints(source)
    master, peer = relay_pair(source, target)
    assert master.result() == peer.result() == 5
    assert sorted(path.name for path in target.iterdir()) == ["meta_000005.json", "model_000005.pt"]
    assert (target / "model_000005.pt").read_bytes() == (source / "model_000005.pt").read_bytes()


def test_wrong_job_identity_fails_both_nodes(tmp_path):
    source, target = tmp_path / "node0", tmp_path / "node1"
    checkpoints(source)
    master, peer = relay_pair(source, target, job="old-job")
    for future in (master, peer):
        with pytest.raises(ValueError, match="identity mismatch"):
            future.result()
    assert not target.exists()


def test_corrupt_transfer_is_rejected_without_publishing_files(tmp_path):
    source, target = tmp_path / "node0", tmp_path / "node1"
    checkpoints(source)
    def altered_manifest(*args):
        value = checkpoint_manifest(*args)
        (source / "model_000005.pt").write_bytes(b"damaged" * 300000)
        return value
    with patch("nanochat_mid_compare.distributed_runtime.checkpoint_manifest", side_effect=altered_manifest):
        master, peer = relay_pair(source, target, timeout=2)
    with pytest.raises(ValueError, match="checksum mismatch"):
        peer.result()
    with pytest.raises(ValueError, match="synchronization failed"):
        master.result()
    assert not list(target.iterdir())


def test_one_failed_peer_releases_other_peers_with_failure(tmp_path):
    source = tmp_path / "node0"
    checkpoints(source)
    port = free_port_triplet()
    topology = [Topology(3, rank, 1, "127.0.0.1", port) for rank in range(3)]
    with ThreadPoolExecutor(max_workers=3) as workers:
        master = workers.submit(sync_checkpoint, source, topology[0], "job", "mid:model", timeout=3)
        first = workers.submit(sync_checkpoint, tmp_path / "node1", topology[1], "job", "mid:model", timeout=3)
        last = workers.submit(sync_checkpoint, tmp_path / "node2", topology[2], "wrong-job", "mid:model", timeout=3)
    for future in (master, first, last):
        # A connection queued when the failed server shuts down can receive
        # a TCP reset instead of the protocol error. Both must fail the job.
        with pytest.raises((ValueError, OSError)):
            future.result()


def test_missing_meta_or_peer_never_reports_success(tmp_path):
    source = tmp_path / "node0"
    checkpoints(source)
    topology = Topology(2, 0, 1, "127.0.0.1", free_port_triplet())
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="timed out"):
        sync_checkpoint(source, topology, "job", "mid:model", timeout=0.1)
    assert time.monotonic() - started < 3
    (source / "meta_000005.json").unlink()
    with pytest.raises(ValueError, match="Incomplete model"):
        sync_checkpoint(source, topology, "job", "mid:model", timeout=0.1)
    with pytest.raises(TimeoutError, match="timed out"):
        sync_checkpoint(tmp_path / "node1", Topology(2, 1, 1, "127.0.0.1", topology.master_port),
                        "job", "mid:model", timeout=0.1)


def test_two_cpu_nodes_train_one_model_then_relay_and_evaluate(tmp_path):
    torch = pytest.importorskip("torch")
    if not torch.distributed.is_gloo_available():
        pytest.skip("Gloo is unavailable")
    fixture = Path(__file__).parent / "fixtures/nanochat_distributed_smoke.py"
    root = Path(__file__).resolve().parents[1]
    directories = [tmp_path / f"node{rank}" for rank in range(2)]
    port = free_port_triplet()
    topology = [Topology(2, rank, 1, "127.0.0.1", port) for rank in range(2)]
    env = dict(os.environ, PYTHONPATH=str(root) + os.pathsep + os.environ.get("PYTHONPATH", ""),
               OMP_NUM_THREADS="1", GLOO_SOCKET_IFNAME="lo0" if sys.platform == "darwin" else "lo")

    def launch(nodes, outputs, mode):
        processes = [subprocess.Popen([sys.executable, "-m", "torch.distributed.run",
                     *node.torchrun_args(evaluation=mode == "eval", timeout=30), str(fixture), mode, str(output)],
                     env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                     for node, output in zip(nodes, outputs)]
        try:
            for process in processes:
                logs, _ = process.communicate(timeout=45)
                assert process.returncode == 0, logs
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)

    launch(topology, directories, "train")
    assert not (directories[1] / "model_000005.pt").exists()
    master, peer = relay_pair(*directories)
    assert master.result() == peer.result() == 5
    launch(topology, directories, "eval")
    reference = tmp_path / "single"
    single = [Topology(1, 0, 1, "127.0.0.1", free_port_triplet())]
    launch(single, [reference], "train")
    launch(single, [reference], "eval")
    weights = torch.load(reference / "model_000005.pt", weights_only=True)
    for directory in directories:
        actual = torch.load(directory / "model_000005.pt", weights_only=True)
        for name, value in weights.items():
            torch.testing.assert_close(actual[name], value, rtol=1e-6, atol=1e-7)
    baseline = json.loads((reference / "eval-rank0.json").read_text())
    results = [json.loads((directory / f"eval-rank{rank}.json").read_text()) for rank, directory in enumerate(directories)]
    assert all(result["accuracy"] == baseline["accuracy"] for result in results)
    assert all(result["mse"] == pytest.approx(baseline["mse"], abs=1e-6) for result in results)
    assert sorted(sum((result["seen"] for result in results), [])) == list(range(13))
