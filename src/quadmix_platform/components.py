from __future__ import annotations

import json
import os
import subprocess
import urllib.request
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
        for stage in job.stages:
            env = dict(os.environ)
            env.update({str(k): str(v) for k, v in stage.env.items()})
            cmd = [stage.executable, *stage.args]
            try:
                completed = subprocess.run(
                    cmd,
                    env=env,
                    cwd=stage.cwd,
                    check=False,
                )
            except FileNotFoundError as exc:
                return "FAILED", external_id, f"stage '{stage.name}' executable not found: {exc}"
            if completed.returncode != 0:
                return (
                    "FAILED",
                    external_id,
                    f"stage '{stage.name}' exited with code {completed.returncode}",
                )
        return "SUCCEEDED", external_id, "All stages completed locally."


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
        if not endpoint:
            raise ValueError("executor_config.endpoint is required for hpc-cluster")
        if urlparse(str(endpoint)).scheme not in {"http", "https"}:
            raise ValueError("hpc-cluster endpoint must use http or https")
        payload = json.dumps({
            "name": job.id,
            "components": {
                key: job.request.get(key)
                for key in ("dataset_id", "algorithm_id", "trainer_id", "evaluator_id")
            },
            "stages": [stage.to_dict() for stage in job.stages],
        }).encode()
        headers = {"Content-Type": "application/json"}
        token = os.environ.get(config.get("token_env", self.token_env))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.load(response)
        if not isinstance(value, dict):
            raise ValueError("hpc-cluster response must be a JSON object")
        return str(value.get("status", "SUBMITTED")), str(value.get("id", "")), "Submitted to HPC cluster API."
