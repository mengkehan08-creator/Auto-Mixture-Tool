"""OBS-backed coordination for multi-node proxy experiments.

Each ModelArts node runs a disjoint subset of proxy experiments.  Results are
published as JSON, gathered by node 0, and the final sampled dataset is then
published for the remaining nodes.  OBS is used only as an artifact/barrier
store; it is not treated as a POSIX filesystem.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np

from quadmix.core.types import ParameterSet, ProxyResult, QuaDMixConfig
from quadmix.utils.json_utils import sanitize_for_json


def _join_uri(root: str, *parts: str) -> str:
    return "/".join([root.rstrip("/"), *(part.strip("/") for part in parts)])


class ArtifactStore:
    """Small storage facade supporting OBS through moxing or obsutil."""

    def __init__(self, backend: str = "auto") -> None:
        self.backend = self._detect_backend(backend)

    @staticmethod
    def _detect_backend(requested: str) -> str:
        if requested not in {"auto", "moxing", "obsutil", "local"}:
            raise ValueError("artifact backend must be auto, moxing, obsutil, or local")
        if requested != "auto":
            return requested
        try:
            import moxing  # noqa: F401
            return "moxing"
        except ImportError:
            if shutil.which("obsutil"):
                return "obsutil"
        raise RuntimeError(
            "OBS同步不可用: 镜像中既没有moxing，也找不到obsutil；"
            "请安装其中一个，或设置AMT_OBS_BACKEND"
        )

    def exists(self, uri: str) -> bool:
        if self.backend == "local":
            return Path(uri).exists()
        if self.backend == "moxing":
            import moxing as mox
            return bool(mox.file.exists(uri))
        result = subprocess.run(
            ["obsutil", "stat", uri], check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0

    def upload_file(self, local_path: str | Path, uri: str) -> None:
        local = str(local_path)
        if self.backend == "local":
            target = Path(uri)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(local, target)
            return
        if self.backend == "moxing":
            import moxing as mox
            mox.file.copy(local, uri)
            return
        subprocess.run(["obsutil", "cp", local, uri, "-f"], check=True)

    def download_file(self, uri: str, local_path: str | Path) -> None:
        local = Path(local_path)
        local.parent.mkdir(parents=True, exist_ok=True)
        if self.backend == "local":
            shutil.copy2(uri, local)
            return
        if self.backend == "moxing":
            import moxing as mox
            mox.file.copy(uri, str(local))
            return
        subprocess.run(["obsutil", "cp", uri, str(local), "-f"], check=True)

    def upload_directory(self, local_path: str | Path, uri: str) -> None:
        local = str(local_path)
        if self.backend == "local":
            target = Path(uri)
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(local, target)
            return
        if self.backend == "moxing":
            import moxing as mox
            mox.file.copy_parallel(local, uri)
            return
        subprocess.run(["obsutil", "cp", local, uri, "-r", "-f"], check=True)

    def download_directory(self, uri: str, local_path: str | Path) -> None:
        local = Path(local_path)
        local.mkdir(parents=True, exist_ok=True)
        if self.backend == "local":
            shutil.copytree(uri, local, dirs_exist_ok=True)
            return
        if self.backend == "moxing":
            import moxing as mox
            mox.file.copy_parallel(uri, str(local))
            return
        subprocess.run(["obsutil", "cp", uri, str(local), "-r", "-f"], check=True)

    def write_text(self, uri: str, value: str) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "value.txt"
            path.write_text(value, encoding="utf-8")
            self.upload_file(path, uri)


class DistributedProxyCoordinator:
    """Coordinate QuaDMix proxy experiments and final artifacts through OBS."""

    def __init__(
        self,
        root_uri: str,
        node_rank: int,
        num_nodes: int,
        timeout_seconds: float = 86400,
        backend: str = "auto",
    ) -> None:
        if num_nodes < 2:
            raise ValueError("distributed coordinator requires at least two nodes")
        if node_rank < 0 or node_rank >= num_nodes:
            raise ValueError("node_rank must be within [0, num_nodes)")
        if not root_uri:
            raise ValueError("distributed QuaDMix requires an OBS coordination URI")
        self.root_uri = root_uri.rstrip("/")
        self.node_rank = node_rank
        self.num_nodes = num_nodes
        self.timeout_seconds = timeout_seconds
        self.store = ArtifactStore(backend)

    @property
    def is_primary(self) -> bool:
        return self.node_rank == 0

    def local_indices(self, total: int) -> list[int]:
        return list(range(self.node_rank, total, self.num_nodes))

    def publish_results(
        self,
        results: list[ProxyResult],
        parameter_hash: str,
    ) -> None:
        payload = {
            "node_rank": self.node_rank,
            "parameter_hash": parameter_hash,
            "results": [self._serialize_result(result) for result in results],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / f"node-{self.node_rank}.json"
            path.write_text(
                json.dumps(sanitize_for_json(payload), ensure_ascii=False),
                encoding="utf-8",
            )
            self.store.upload_file(
                path,
                _join_uri(self.root_uri, "proxy_results", path.name),
            )
        self.store.write_text(
            _join_uri(self.root_uri, "proxy_results", f"node-{self.node_rank}._SUCCESS"),
            "ok\n",
        )

    def gather_results(
        self,
        config: QuaDMixConfig,
        expected_count: int,
        parameter_hash: str,
    ) -> list[ProxyResult]:
        if not self.is_primary:
            raise RuntimeError("only node 0 may gather distributed proxy results")
        gathered: list[ProxyResult] = []
        with tempfile.TemporaryDirectory() as temporary:
            for rank in range(self.num_nodes):
                success = _join_uri(self.root_uri, "proxy_results", f"node-{rank}._SUCCESS")
                self._wait(success)
                local = Path(temporary) / f"node-{rank}.json"
                self.store.download_file(
                    _join_uri(self.root_uri, "proxy_results", local.name), local
                )
                payload = json.loads(local.read_text(encoding="utf-8"))
                if payload.get("parameter_hash") != parameter_hash:
                    raise RuntimeError(
                        f"node-{rank}使用了不同的代理参数；请为多节点配置固定seed"
                    )
                gathered.extend(
                    self._deserialize_result(item, config)
                    for item in payload.get("results", [])
                )
        gathered.sort(key=lambda result: int(result.metadata["experiment_id"]))
        ids = [int(result.metadata["experiment_id"]) for result in gathered]
        if ids != list(range(expected_count)):
            raise RuntimeError(
                f"分布式代理结果不完整: expected=0..{expected_count - 1}, got={ids}"
            )
        return gathered

    def publish_final_output(self, output_dir: str | Path) -> None:
        if not self.is_primary:
            raise RuntimeError("only node 0 may publish final QuaDMix output")
        self.store.upload_directory(output_dir, _join_uri(self.root_uri, "final"))
        self.store.write_text(_join_uri(self.root_uri, "final", "_SUCCESS"), "ok\n")

    def wait_and_download_final_output(self, output_dir: str | Path) -> None:
        self._wait(_join_uri(self.root_uri, "final", "_SUCCESS"))
        target = Path(output_dir) / "sampled_dataset"
        self.store.download_directory(
            _join_uri(self.root_uri, "final", "sampled_dataset"), target
        )

    def _wait(self, uri: str) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            if self.store.exists(uri):
                return
            time.sleep(10)
        raise TimeoutError(f"等待分布式阶段完成超时: {uri}")

    @staticmethod
    def _serialize_result(result: ProxyResult) -> dict[str, Any]:
        return {
            "parameters": result.parameters.flatten().tolist(),
            "validation_loss": (
                float(result.validation_loss)
                if np.isfinite(result.validation_loss)
                else None
            ),
            "metadata": result.metadata,
            "per_task_losses": result.per_task_losses,
        }

    @staticmethod
    def _deserialize_result(item: dict[str, Any], config: QuaDMixConfig) -> ProxyResult:
        parameters = ParameterSet.from_flattened(
            np.asarray(item["parameters"], dtype=np.float64),
            config.num_domains,
            config.num_criteria,
        )
        return ProxyResult(
            parameters=parameters,
            validation_loss=(
                float(item["validation_loss"])
                if item.get("validation_loss") is not None
                else float("inf")
            ),
            metadata=dict(item.get("metadata", {})),
            per_task_losses=item.get("per_task_losses"),
        )


def parameter_set_hash(parameters: list[ParameterSet]) -> str:
    import hashlib

    values = np.concatenate([parameter.flatten() for parameter in parameters])
    return hashlib.sha256(values.astype(np.float64).tobytes()).hexdigest()
