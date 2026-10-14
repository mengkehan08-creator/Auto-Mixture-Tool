"""OBS-backed coordination for multi-node proxy experiments.

Each ModelArts node runs a disjoint subset of proxy experiments.  Results are
published as JSON, gathered by node 0, and the final sampled dataset is then
published for the remaining nodes.  OBS is used only as an artifact/barrier
store; it is not treated as a POSIX filesystem.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import shutil
import subprocess
import tempfile
import time
import warnings
from contextlib import contextmanager
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
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
                pending = Path(temporary.name)
            try:
                shutil.copy2(local, pending)
                os.replace(pending, target)
            finally:
                pending.unlink(missing_ok=True)
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
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("coordination timeout must be finite and positive")
        self.root_uri = root_uri.rstrip("/")
        self.node_rank = node_rank
        self.num_nodes = num_nodes
        self.timeout_seconds = timeout_seconds
        self.store = ArtifactStore(backend)
        self.run_hash: str | None = None

    @property
    def is_primary(self) -> bool:
        return self.node_rank == 0

    def local_indices(self, total: int) -> list[int]:
        return list(range(self.node_rank, total, self.num_nodes))

    def verify_run(self, manifest: dict[str, Any]) -> None:
        """Agree on inputs and budgets before any node starts training."""
        manifest = {**manifest, "job_id": os.environ.get("AMT_RUN_ID") or os.environ.get("MA_VJ_NAME")}
        value = json.dumps(manifest, ensure_ascii=False, sort_keys=True, allow_nan=False)
        manifest = json.loads(value)
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        node_uri = _join_uri(self.root_uri, "manifests", f"node-{self.node_rank}.json")
        used = [node_uri,
                _join_uri(self.root_uri, "proxy_results", f"node-{self.node_rank}.json"),
                _join_uri(self.root_uri, "failures", f"node-{self.node_rank}.json"),
                _join_uri(self.root_uri, "manifests", "_SUCCESS"),
                _join_uri(self.root_uri, "final", "_SUCCESS")]
        if any(self.store.exists(uri) for uri in used):
            raise RuntimeError("协调目录已被使用；请为新作业使用唯一的 coordination URI")
        self.store.write_text(node_uri, json.dumps({
            "node_rank": self.node_rank, "num_nodes": self.num_nodes, "manifest": manifest,
        }, ensure_ascii=False, allow_nan=False))
        self.store.write_text(node_uri + "._READY", "ok\n")
        deadline = time.monotonic() + self.timeout_seconds
        if self.is_primary:
            with tempfile.TemporaryDirectory() as temporary:
                for rank in range(self.num_nodes):
                    uri = _join_uri(self.root_uri, "manifests", f"node-{rank}.json")
                    self._wait(uri + "._READY", deadline)
                    local = Path(temporary) / f"node-{rank}.json"
                    self.store.download_file(uri, local)
                    payload = json.loads(local.read_text(encoding="utf-8"))
                    if (not isinstance(payload, dict) or payload.get("node_rank") != rank
                            or payload.get("num_nodes") != self.num_nodes):
                        raise RuntimeError(f"node-{rank}的运行清单节点身份或节点数不匹配")
                    actual = payload.get("manifest", {})
                    if not isinstance(actual, dict):
                        raise RuntimeError(f"node-{rank}的运行清单无效")
                    if actual != manifest:
                        changed = sorted(key for key in manifest.keys() | actual.keys()
                                         if manifest.get(key) != actual.get(key))
                        raise RuntimeError(f"node-{rank}运行配置不一致: {changed}")
            self.store.write_text(_join_uri(self.root_uri, "run_manifest.json"), value)
            self.store.write_text(_join_uri(self.root_uri, "manifests", "_SUCCESS"), digest)
        else:
            self._wait(_join_uri(self.root_uri, "manifests", "_SUCCESS"), deadline)
            with tempfile.TemporaryDirectory() as temporary:
                local = Path(temporary) / "digest.txt"
                self.store.download_file(_join_uri(self.root_uri, "manifests", "_SUCCESS"), local)
                if local.read_text(encoding="utf-8") != digest:
                    raise RuntimeError("主节点确认了不同的运行配置")
        self.run_hash = digest

    @contextmanager
    def failure_guard(self):
        try:
            yield
        except BaseException as exc:
            try:
                self.publish_failure(exc)
            except Exception as publication_error:
                warnings.warn(f"无法发布节点失败状态: {publication_error}", RuntimeWarning)
            raise

    def publish_failure(self, error: BaseException) -> None:
        payload = {"node_rank": self.node_rank, "error_type": type(error).__name__,
                   "message": str(error)[:4000]}
        self.store.write_text(
            _join_uri(self.root_uri, "failures", f"node-{self.node_rank}.json"),
            json.dumps(payload, ensure_ascii=False),
        )

    def publish_results(
        self,
        results: list[ProxyResult],
        parameter_hash: str,
        artifacts_dir: str | Path | None = None,
    ) -> None:
        for result in results:
            self._validate_result(result)
            experiment_id = result.metadata["experiment_id"]
            if experiment_id % self.num_nodes != self.node_rank:
                raise RuntimeError(f"实验 {experiment_id} 不属于 node-{self.node_rank}")
            result.metadata["modelarts_node_rank"] = self.node_rank
            result.metadata["run_hash"] = self.run_hash
            if artifacts_dir is not None:
                source = Path(artifacts_dir) / f"exp_{experiment_id:04d}"
                for name in ("meta.json", "model.pt", "selected_indices.npy"):
                    if not (source / name).is_file():
                        raise FileNotFoundError(f"实验 {experiment_id} 缺少训练产物: {source / name}")
                uri = _join_uri(self.root_uri, "proxy_experiments", source.name)
                result.metadata["artifact_uri"] = uri
                (source / "meta.json").write_text(
                    json.dumps(sanitize_for_json(result.metadata), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                self.store.upload_directory(source, uri)
        payload = {
            "node_rank": self.node_rank,
            "num_nodes": self.num_nodes,
            "parameter_hash": parameter_hash,
            "run_hash": self.run_hash,
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
        deadline = time.monotonic() + self.timeout_seconds
        with tempfile.TemporaryDirectory() as temporary:
            for rank in range(self.num_nodes):
                success = _join_uri(self.root_uri, "proxy_results", f"node-{rank}._SUCCESS")
                self._wait(success, deadline)
                local = Path(temporary) / f"node-{rank}.json"
                self.store.download_file(
                    _join_uri(self.root_uri, "proxy_results", local.name), local
                )
                payload = json.loads(local.read_text(encoding="utf-8"))
                if payload.get("node_rank") != rank or payload.get("num_nodes") != self.num_nodes:
                    raise RuntimeError(f"node-{rank}的代理结果节点身份或节点数不匹配")
                if payload.get("parameter_hash") != parameter_hash:
                    raise RuntimeError(
                        f"node-{rank}使用了不同的代理参数；请为多节点配置固定seed"
                    )
                if payload.get("run_hash") != self.run_hash:
                    raise RuntimeError(f"node-{rank}的运行配置摘要不匹配")
                node_results = [
                    self._deserialize_result(item, config)
                    for item in payload.get("results", [])
                ]
                ids = [result.metadata.get("experiment_id") for result in node_results]
                if (any(type(index) is not int for index in ids)
                        or sorted(ids) != list(range(rank, expected_count, self.num_nodes))):
                    raise RuntimeError(f"node-{rank}的代理实验编号不完整或归属错误: {ids}")
                for result in node_results:
                    self._validate_result(result)
                    if result.metadata.get("modelarts_node_rank") != rank:
                        raise RuntimeError(f"代理实验 {result.metadata['experiment_id']} 的节点身份不匹配")
                    if result.metadata.get("run_hash") != self.run_hash:
                        raise RuntimeError(f"代理实验 {result.metadata['experiment_id']} 的运行配置摘要不匹配")
                gathered.extend(node_results)
        gathered.sort(key=lambda result: int(result.metadata["experiment_id"]))
        ids = [int(result.metadata["experiment_id"]) for result in gathered]
        if ids != list(range(expected_count)):
            raise RuntimeError(
                f"分布式代理结果不完整: expected=0..{expected_count - 1}, got={ids}"
            )
        if parameter_set_hash([result.parameters for result in gathered]) != parameter_hash:
            raise RuntimeError("代理结果中的实际参数与全局实验参数不匹配")
        task_sets = [None if result.per_task_losses is None else set(result.per_task_losses)
                     for result in gathered]
        if task_sets and any(tasks != task_sets[0] for tasks in task_sets[1:]):
            raise RuntimeError("分布式代理实验使用了不同的评估任务，无法统一汇总")
        self.store.write_text(_join_uri(self.root_uri, "proxy_results", "all.json"),
                              json.dumps(sanitize_for_json({
                                  "run_hash": self.run_hash,
                                  "results": [self._serialize_result(result) for result in gathered],
                              }), ensure_ascii=False, indent=2))
        return gathered

    def publish_final_output(self, output_dir: str | Path) -> None:
        if not self.is_primary:
            raise RuntimeError("only node 0 may publish final QuaDMix output")
        for source in Path(output_dir).iterdir():
            # All nodes' checkpoints have already been published by experiment ID.
            if source.name == "proxy_experiments":
                continue
            target = _join_uri(self.root_uri, "final", source.name)
            if source.is_dir():
                self.store.upload_directory(source, target)
            else:
                self.store.upload_file(source, target)
        self.store.write_text(_join_uri(self.root_uri, "final", "_SUCCESS"), "ok\n")

    def wait_and_download_final_output(self, output_dir: str | Path) -> None:
        self._wait(_join_uri(self.root_uri, "final", "_SUCCESS"))
        target = Path(output_dir) / "sampled_dataset"
        self.store.download_directory(
            _join_uri(self.root_uri, "final", "sampled_dataset"), target
        )

    def _wait(self, uri: str, deadline: float | None = None) -> None:
        if deadline is None:
            deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            for rank in range(self.num_nodes):
                failure = _join_uri(self.root_uri, "failures", f"node-{rank}.json")
                if self.store.exists(failure):
                    with tempfile.TemporaryDirectory() as temporary:
                        local = Path(temporary) / "failure.json"
                        self.store.download_file(failure, local)
                        error = json.loads(local.read_text(encoding="utf-8"))
                    raise RuntimeError(f"分布式节点 node-{rank} 失败: {error.get('message', '')}")
            if self.store.exists(uri):
                return
            interval = 0.05 if self.store.backend == "local" else 10
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
        raise TimeoutError(f"等待分布式阶段完成超时: {uri}")

    @staticmethod
    def _validate_result(result: ProxyResult) -> None:
        experiment_id = result.metadata.get("experiment_id")
        if type(experiment_id) is not int or experiment_id < 0:
            raise RuntimeError(f"代理实验编号无效: {experiment_id}")
        if result.metadata.get("error"):
            raise RuntimeError(f"代理实验 {experiment_id} 执行失败: {result.metadata['error']}")
        losses = [result.validation_loss]
        if result.per_task_losses is not None:
            if not isinstance(result.per_task_losses, dict) or not result.per_task_losses:
                raise RuntimeError(f"代理实验 {experiment_id} 的评估任务无效")
            losses.extend(result.per_task_losses.values())
        losses.extend(result.metadata[key] for key in ("train_loss", "val_loss")
                      if key in result.metadata)
        try:
            valid = all(math.isfinite(float(loss)) for loss in losses)
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid or not np.isfinite(result.parameters.flatten()).all():
            raise RuntimeError(f"代理实验 {experiment_id} 包含无效指标或参数")
        if "val_loss" in result.metadata and float(result.metadata["val_loss"]) != float(result.validation_loss):
            raise RuntimeError(f"代理实验 {experiment_id} 的评估指标与训练记录不匹配")

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
    values = np.concatenate([parameter.flatten() for parameter in parameters])
    return hashlib.sha256(values.astype(np.float64).tobytes()).hexdigest()
