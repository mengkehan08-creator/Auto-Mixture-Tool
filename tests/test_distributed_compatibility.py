"""Regression coverage for OBS directory layout and shared node identity."""
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from quadmix.pipeline.distributed_proxy import ArtifactStore
from quadmix.sampling.sources import resolve_parquet_source
from scripts.runners import run_essential_web_v1 as entrypoint


@pytest.mark.parametrize("direction", ["upload", "download"])
def test_obsutil_directories_keep_contents_at_the_requested_root(tmp_path, monkeypatch, direction):
    remote = tmp_path / "obs"
    source = tmp_path / "source"
    uri = "obs://bucket/run/sampled_dataset"

    def local(value):
        return remote / value.removeprefix("obs://") if value.startswith("obs://") else Path(value)

    def execute(args, **kwargs):
        # obsutil cp -r includes the source folder unless -flat is specified.
        assert args[:2] == ["obsutil", "cp"] and "-r" in args
        source, target = local(args[2]), local(args[3])
        if "-flat" not in args:
            target = target / source.name
        shutil.copytree(source, target, dirs_exist_ok=True)

    monkeypatch.setattr("quadmix.pipeline.distributed_proxy.subprocess.run", execute)
    original = source if direction == "upload" else local(uri)
    original.mkdir(parents=True)
    (original / "part.parquet").write_bytes(b"parquet")
    (original / "metadata").mkdir()
    (original / "metadata/info.json").write_text("{}")
    store = ArtifactStore("obsutil")
    if direction == "upload":
        store.upload_directory(source, uri)
        target = local(uri)
    else:
        target = tmp_path / "node1/sampled_dataset"
        store.download_directory(uri, target)
    assert resolve_parquet_source(str(target)) == [str(target / "part.parquet")]
    assert (target / "metadata/info.json").read_text() == "{}"
    assert not (target / original.name).exists()


@pytest.fixture
def node_environment(monkeypatch):
    for key in ("AMT_EXPECTED_NODES", "NNODES", "MA_NUM_HOSTS", "NODE_RANK",
                "MA_NODE_RANK", "VC_NODE_RANK", "VC_TASK_INDEX", "MASTER_ADDR",
                "MA_MASTER_ADDR", "VC_MASTER_ADDR", "VC_WORKER_HOSTS", "AMT_RUN_ID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AMT_OBS_BACKEND", "local")
    monkeypatch.setattr("socket.gethostname", lambda: "laptop")


@pytest.mark.parametrize("environment,nodes,rank,hostname,expected", [
    ({}, None, None, "laptop", (1, 0)),
    ({"NNODES": "2", "NODE_RANK": "1"}, None, None, "laptop", (2, 1)),
    ({"AMT_EXPECTED_NODES": "2", "NODE_RANK": "1"}, None, None, "laptop", (2, 1)),
    ({"MA_NUM_HOSTS": "2", "VC_TASK_INDEX": "1"}, None, None, "laptop", (2, 1)),
    ({"MA_NUM_HOSTS": "2", "MA_NODE_RANK": "1"}, None, None, "laptop", (2, 1)),
    ({"MA_NUM_HOSTS": "2", "VC_NODE_RANK": "1"}, None, None, "laptop", (2, 1)),
    ({"AMT_EXPECTED_NODES": "2"}, None, None, "job-worker-1", (2, 1)),
    ({"MA_NUM_HOSTS": "2"}, None, None, "job-worker-1.job.ns.svc", (2, 1)),
    ({}, 2, 1, "laptop", (2, 1)),
    ({"NNODES": "2", "NODE_RANK": "1"}, 2, 1, "laptop", (2, 1)),
])
def test_quadmix_resolves_all_supported_node_identities(
        tmp_path, monkeypatch, node_environment, environment, nodes, rank, hostname, expected):
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("socket.gethostname", lambda: hostname)
    args = SimpleNamespace(distributed_nodes=nodes, node_rank=rank,
                           coordination_uri=str(tmp_path), coordination_timeout=1)
    monkeypatch.setattr(entrypoint, "build_parser", lambda: SimpleNamespace(parse_args=lambda: args))
    # Mixing coordinates through storage, so resolving identity must not need DNS.
    with patch("socket.gethostbyname", side_effect=AssertionError("unexpected DNS lookup")), \
            patch.object(entrypoint, "run_pipeline", return_value=0) as run:
        assert entrypoint.main() == 0
    if expected[0] == 1:
        run.assert_called_once_with(args)
    else:
        coordinator = run.call_args.args[1]
        assert (coordinator.num_nodes, coordinator.node_rank) == expected


@pytest.mark.parametrize("environment,nodes,rank,error", [
    ({"NNODES": "2", "MA_NUM_HOSTS": "3", "NODE_RANK": "1"}, None, None, "Conflicting"),
    ({"NNODES": "2", "NODE_RANK": "1", "VC_TASK_INDEX": "0"}, None, None, "Conflicting"),
    ({"NNODES": "2", "NODE_RANK": "1"}, 3, None, "Conflicting"),
    ({"NNODES": "2", "NODE_RANK": "1"}, None, 0, "Conflicting"),
    ({"NNODES": "2", "NODE_RANK": "1", "AMT_EXPECTED_NODES": "3"}, None, None, "AMT_EXPECTED_NODES"),
    ({"NNODES": "2", "NODE_RANK": "2"}, None, None, "outside"),
    ({}, 0, None, "Invalid node"),
])
def test_quadmix_rejects_conflicting_or_invalid_node_identity(
        monkeypatch, node_environment, environment, nodes, rank, error):
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    args = SimpleNamespace(distributed_nodes=nodes, node_rank=rank)
    monkeypatch.setattr(entrypoint, "build_parser", lambda: SimpleNamespace(parse_args=lambda: args))
    with patch.object(entrypoint, "run_pipeline") as run, pytest.raises(ValueError, match=error):
        entrypoint.main()
    run.assert_not_called()
