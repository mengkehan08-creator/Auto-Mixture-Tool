from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from typing import Any
from urllib.parse import urlparse
from .interfaces import ExecutorAdapter
from .models import JobRecord


class LocalExecutor(ExecutorAdapter):
    """Development executor: run each ``CommandSpec`` stage as a local subprocess.

    Intended for the dev environment (``pip install -e .`` + deps installed): it
    walks ``job.stages`` in order and invokes ``[executable, *args]`` with the
    stage's ``env`` (overlaid on the current environment) and ``cwd``. The first
    failing stage short-circuits the job. Returns ``(status, external_id, msg)``
    where ``external_id`` is a stable local job identifier.
    """

    id = "local"
    display_name = "Local subprocess (dev)"

    def submit(self, job: JobRecord) -> tuple[str, str, str]:
        external_id = f"local:{job.id}"
        runtime_env = self._runtime_env(job)
        timeout = self._timeout(job.request.get("executor_config", {}))
        for stage in job.stages:
            env = dict(os.environ)
            env.update(runtime_env)
            env.update({str(k): str(v) for k, v in stage.env.items()})
            cmd = [stage.executable, *stage.args]
            try:
                completed = subprocess.run(
                    cmd,
                    env=env,
                    cwd=stage.cwd,
                    check=False,
                    timeout=timeout,
                )
            except FileNotFoundError as exc:
                return "FAILED", external_id, f"stage '{stage.name}' executable not found: {exc}"
            except subprocess.TimeoutExpired:
                return "FAILED", external_id, f"stage '{stage.name}' exceeded timeout_seconds"
            if completed.returncode != 0:
                return (
                    "FAILED",
                    external_id,
                    f"stage '{stage.name}' exited with code {completed.returncode}",
                )
        return "SUCCEEDED", external_id, "All stages completed locally."

    @staticmethod
    def _timeout(config: dict[str, Any]) -> float | None:
        value = config.get("timeout_seconds")
        if value is None:
            return None
        timeout = float(value)
        if timeout <= 0:
            raise ValueError("local executor timeout_seconds must be positive")
        return timeout

    @staticmethod
    def _runtime_env(job: JobRecord) -> dict[str, str]:
        config = job.request.get("executor_config", {})
        device_type = str(
            config.get("device_type")
            or job.request.get("algorithm_config", {}).get("device_type", "cpu")
        ).lower()
        if device_type not in {"cpu", "cuda", "npu"}:
            raise ValueError("local executor device_type must be one of: cpu, cuda, npu")

        configured_count = config.get("device_count")
        algorithm_count = job.request.get("algorithm_config", {}).get("npu_devices")
        trainer_count = job.request.get("trainer_config", {}).get("npu_devices")
        counts = [int(value) for value in (configured_count, algorithm_count, trainer_count) if value is not None]
        if any(value <= 0 for value in counts):
            raise ValueError("local executor device counts must be positive")
        if len(set(counts)) > 1:
            raise ValueError(
                "local device_count, algorithm_config.npu_devices and "
                "trainer_config.npu_devices must match"
            )
        if not counts or device_type == "cpu":
            return {"AMT_DEVICE_TYPE": device_type}

        device_count = counts[0]
        node_count = int(os.environ.get("MA_NUM_HOSTS", "1"))
        if node_count <= 0:
            raise ValueError("MA_NUM_HOSTS must be positive")
        visible = ",".join(str(index) for index in range(device_count))
        env = {
            "AMT_DEVICE_TYPE": device_type,
            "AMT_DEVICE_COUNT": str(device_count),
        }
        if device_type == "npu":
            env.update({
                "NUM_NPU": str(device_count),
                # ModelArts injects the global rank size for multi-node jobs.
                # Keep it instead of incorrectly reducing 2x8 back to 8.
                "RANK_SIZE": os.environ.get(
                    "RANK_SIZE", str(device_count * node_count)
                ),
                "ASCEND_VISIBLE_DEVICES": visible,
            })
        else:
            env["CUDA_VISIBLE_DEVICES"] = visible
        return env


class HpcClusterExecutor(ExecutorAdapter):
    """Executor that submits jobs to a High-Performance Computing cluster API.

    Production backend: the platform
    serializes the compiled ``CommandSpec`` stages into JSON and POSTs them to
    the cluster's REST submission endpoint. Use the ``local`` executor for dev.
    """

    id = "hpc-cluster"
    display_name = "HPC cluster API"

    def __init__(self, endpoint: str | None = None, token_env: str = "AMT_CLUSTER_TOKEN") -> None:
        self.endpoint = endpoint
        self.token_env = token_env

    def submit(self, job: JobRecord) -> tuple[str, str, str]:
        config = job.request.get("executor_config", {})
        endpoint = config.get("endpoint") or self.endpoint
        self._validate_endpoint(endpoint, "endpoint")
        payload: dict[str, Any] = {
            "name": job.id,
            "components": {
                key: job.request.get(key)
                for key in ("dataset_id", "algorithm_id", "trainer_id", "evaluator_id")
            },
            "stages": [stage.to_dict() for stage in job.stages],
        }
        for key in ("queue", "image", "resources", "mounts", "working_dir", "labels", "environment"):
            if key in config:
                payload[key] = config[key]
        value = self._request_json(
            str(endpoint),
            method="POST",
            payload=payload,
            headers=self._headers(config),
            timeout=self._timeout(config),
        )
        external_id = str(value.get(str(config.get("job_id_field", "id")), ""))
        if not external_id:
            raise ValueError("hpc-cluster response does not contain a job id")
        status = self._status(value, config, "SUBMITTED")
        return status, external_id, "Submitted to HPC cluster API."

    def refresh(self, job: JobRecord) -> tuple[str, str] | None:
        config = job.request.get("executor_config", {})
        template = config.get("status_endpoint")
        if not template or not job.external_id:
            return None
        endpoint = str(template).replace("{job_id}", job.external_id)
        self._validate_endpoint(endpoint, "status_endpoint")
        value = self._request_json(
            endpoint,
            method="GET",
            headers=self._headers(config),
            timeout=self._timeout(config),
        )
        return self._status(value, config, job.status), "Refreshed from HPC cluster API."

    def _headers(self, config: dict[str, Any]) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        configured = config.get("headers", {})
        header_env = config.get("header_env", {})
        if not isinstance(configured, dict) or not isinstance(header_env, dict):
            raise ValueError("hpc-cluster headers and header_env must be objects")
        headers.update({str(key): str(value) for key, value in configured.items()})
        token = os.environ.get(str(config.get("token_env", self.token_env)))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        for header, variable in header_env.items():
            value = os.environ.get(str(variable))
            if not value:
                raise ValueError(f"environment variable '{variable}' is required for header '{header}'")
            headers[str(header)] = value
        return headers

    @staticmethod
    def _validate_endpoint(endpoint: Any, field: str) -> None:
        if not endpoint:
            raise ValueError(f"executor_config.{field} is required for hpc-cluster")
        if urlparse(str(endpoint)).scheme not in {"http", "https"}:
            raise ValueError(f"hpc-cluster {field} must use http or https")

    @staticmethod
    def _timeout(config: dict[str, Any]) -> float:
        timeout = float(config.get("timeout_seconds", 30))
        if timeout <= 0:
            raise ValueError("hpc-cluster timeout_seconds must be positive")
        return timeout

    @staticmethod
    def _status(value: dict[str, Any], config: dict[str, Any], default: str) -> str:
        field = str(config.get("status_field", "status"))
        raw_status = str(value.get(field, default))
        mapping = config.get("status_map", {})
        if not isinstance(mapping, dict):
            raise ValueError("hpc-cluster status_map must be an object")
        return str(mapping.get(raw_status, raw_status)).upper()

    @staticmethod
    def _request_json(
        endpoint: str,
        method: str,
        headers: dict[str, str],
        timeout: float,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(endpoint, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.load(response)
        if not isinstance(value, dict):
            raise ValueError("hpc-cluster response must be a JSON object")
        return value
