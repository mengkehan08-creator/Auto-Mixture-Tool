"""Submit and monitor the two ModelArts jobs that form one experiment."""

from __future__ import annotations

import copy
import json
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


SUCCESS_STATES = {"completed", "succeeded", "success"}
FAILURE_STATES = {"failed", "canceled", "cancelled", "terminated"}


def _clean_obs_uri(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value.startswith("obs://"):
        raise ValueError("OBS paths must start with obs://")
    return value


def _state(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("status", "state", "phase"):
            if isinstance(value.get(key), str):
                return value[key]
            found = _state(value.get(key))
            if found:
                return found
        for key in ("metadata", "spec", "result", "data"):
            found = _state(value.get(key))
            if found:
                return found
    return ""


class ModelArtsClient:
    def __init__(self) -> None:
        from modelarts_training_job import headers, url

        if "REPLACE_ME" in url or any("REPLACE_ME" in str(v) for v in headers.values()):
            raise ValueError(
                "请先在 modelarts_training_job.py 中填写 ModelArts API 地址、区域和 Authorization"
            )
        self.url = url.rstrip("/")
        self.headers = dict(headers)

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = requests.post(
            self.url, headers=self.headers, json=payload, verify=False, timeout=60
        )
        response.raise_for_status()
        return response.json()

    def get(self, job_id: str) -> dict[str, Any]:
        response = requests.get(
            f"{self.url}/{job_id}", headers=self.headers, verify=False, timeout=60
        )
        response.raise_for_status()
        return response.json()


class ModelArtsWorkflowManager:
    def __init__(self, workspace: Path, client: ModelArtsClient | None = None) -> None:
        self.workspace = Path(workspace)
        self.directory = self.workspace / "result" / ".workflows"
        self.client = client
        self.records: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create(self, config: dict[str, Any]) -> dict[str, Any]:
        normalized = self._validate(config)
        # Fail the HTTP request immediately when the server-side ModelArts
        # endpoint or Authorization template has not been configured.
        self._client()
        workflow_id = uuid.uuid4().hex[:12]
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        prefix = normalized.get("experiment_name") or "experiment"
        experiment = f"{prefix}-{stamp}"
        run_root = f"{_clean_obs_uri(normalized['output_root_obs_uri'])}/runs/{experiment}"
        record = {
            "id": workflow_id,
            "name": experiment,
            "status": "QUEUED",
            "progress": 5,
            "stage": "等待提交配比作业",
            "run_root_obs_uri": run_root,
            "outputs": {
                "mixing": f"{run_root}/mixing/",
                "sampled": f"{run_root}/sampled/",
                "training": f"{run_root}/training/",
            },
            "jobs": [
                self._job_record("mixing", normalized["mixing_nodes"], stamp),
                self._job_record("training-evaluation", normalized["training_nodes"], stamp),
            ],
            "config": normalized,
            "message": "",
        }
        self._store(record)
        thread = threading.Thread(target=self._run, args=(workflow_id,), daemon=True)
        thread.start()
        return self.public(record)

    def list(self) -> list[dict[str, Any]]:
        self._load_disk()
        return [self.public(item) for item in sorted(
            self.records.values(), key=lambda item: item["id"], reverse=True
        )]

    def get(self, workflow_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{12}", workflow_id):
            raise ValueError("invalid workflow id")
        self._load_disk()
        if workflow_id not in self.records:
            raise ValueError("workflow not found")
        return self.public(self.records[workflow_id])

    @staticmethod
    def public(record: dict[str, Any]) -> dict[str, Any]:
        value = copy.deepcopy(record)
        value.pop("config", None)
        return value

    @staticmethod
    def _job_record(module: str, nodes: int, stamp: str) -> dict[str, Any]:
        return {
            "module": module,
            "name": f"{module}-{nodes}node-{stamp}",
            "nodes": nodes,
            "status": "WAITING",
            "id": None,
        }

    def _validate(self, config: dict[str, Any]) -> dict[str, Any]:
        value = copy.deepcopy(config)
        experiment_name = str(value.get("experiment_name") or "").strip()
        if experiment_name and not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,47}", experiment_name
        ):
            raise ValueError("experiment_name must use 1-48 letters, digits, _ or -")
        value["experiment_name"] = experiment_name
        for key in ("input_data_obs_uri", "output_root_obs_uri"):
            value[key] = _clean_obs_uri(str(value.get(key, "")))
        for key in ("mixing_nodes", "training_nodes"):
            nodes = int(value.get(key, 0))
            if not 1 <= nodes <= 16:
                raise ValueError(f"{key} must be between 1 and 16")
            value[key] = nodes
        strategies = value.get("strategies")
        if not isinstance(strategies, list) or not strategies:
            raise ValueError("at least one strategy is required")
        kinds = [item.get("type") for item in strategies]
        if "quadmix" not in kinds:
            raise ValueError("the current mixing job requires one quadmix strategy")
        if kinds.count("quadmix") > 1 or kinds.count("random") > 1:
            raise ValueError("only one quadmix and one random strategy are supported")
        for index, strategy in enumerate(strategies):
            if strategy.get("type") not in {"quadmix", "manual", "random"}:
                raise ValueError(f"unsupported strategy at index {index}")
            if strategy.get("type") == "manual":
                ratios = strategy.get("ratios")
                if not isinstance(ratios, dict) or not ratios:
                    raise ValueError("every manual strategy requires domain ratios")
                try:
                    ratios = {str(domain).strip(): float(ratio) for domain, ratio in ratios.items()}
                except (TypeError, ValueError) as exc:
                    raise ValueError("manual strategy ratios must be numeric") from exc
                if any(not domain or ratio <= 0 for domain, ratio in ratios.items()):
                    raise ValueError("manual strategy domains and ratios must be positive")
                strategy["ratios"] = ratios
            if strategy.get("type") == "quadmix":
                for key in ("proxy_experiments", "proxy_steps", "search_count"):
                    number = int(strategy.get(key, {"proxy_experiments": 16, "proxy_steps": 15, "search_count": 1000}[key]))
                    if number <= 0:
                        raise ValueError(f"quadmix {key} must be positive")
                    strategy[key] = number
        training = value.get("training", {})
        if str(training.get("framework", "nanochat")).lower() != "nanochat":
            raise ValueError("the current training adapter supports NanoChat only")
        devices = int(training.get("devices_per_node", 8))
        if not 1 <= devices <= 8:
            raise ValueError("training devices_per_node must be between 1 and 8")
        training["devices_per_node"] = devices
        ratio = float(training.get("target_param_data_ratio", 0.5))
        if ratio <= 0:
            raise ValueError("training target_param_data_ratio must be positive")
        training["target_param_data_ratio"] = ratio
        value["training"] = training
        for key in (
            "code_obs_uri", "nanochat_repo_obs_uri", "nanochat_model_obs_uri",
            "quadmix_tokenizer_obs_uri", "proxy_validation_obs_uri",
            "eval_bundle_obs_uri", "python_wheels_obs_uri",
        ):
            value["resources"][key] = _clean_obs_uri(value["resources"][key])
        return value

    def _client(self) -> ModelArtsClient:
        if self.client is None:
            self.client = ModelArtsClient()
        return self.client

    def _payload(self, record: dict[str, Any], stage: str) -> dict[str, Any]:
        from modelarts_training_job import job_data

        payload = copy.deepcopy(job_data)
        config = copy.deepcopy(record["config"])
        job = record["jobs"][0 if stage == "mixing" else 1]
        payload["metadata"]["name"] = job["name"]
        payload["metadata"]["description"] = f"Auto-Mixture {stage} stage"
        payload["spec"]["resource"]["node_count"] = job["nodes"]
        env = payload["algorithm"]["environments"]
        env["AMT_RUN_ID"] = record["name"]
        env["AMT_EXPECTED_NODES"] = str(job["nodes"])
        env["AMT_WORKFLOW_CONFIG_JSON"] = json.dumps(
            config, ensure_ascii=False, separators=(",", ":")
        )
        env["AMT_RUN_OBS_URI"] = f"{record['run_root_obs_uri']}/mixing/coordination"
        payload["algorithm"]["command"] = self._command(stage)

        resources = config["resources"]
        payload["algorithm"]["code_dir"] = (
            resources.get("code_obs_uri") or payload["algorithm"]["code_dir"]
        )
        mapping = {
            "data_dir": config["input_data_obs_uri"],
            "nanochat_model_dir": resources["nanochat_model_obs_uri"],
            "code_dir": resources.get("code_obs_uri") or payload["algorithm"]["code_dir"],
            "nanochat_npu_dir": resources["nanochat_repo_obs_uri"],
            "quadmix_tokenizer_dir": resources["quadmix_tokenizer_obs_uri"],
            "proxy_validation_dir": resources["proxy_validation_obs_uri"],
            "eval_bundle_dir": resources["eval_bundle_obs_uri"],
            "python_wheels_dir": resources["python_wheels_obs_uri"],
        }
        needed_inputs = (
            {"data_dir", "nanochat_model_dir", "code_dir", "nanochat_npu_dir",
             "quadmix_tokenizer_dir", "proxy_validation_dir", "python_wheels_dir"}
            if stage == "mixing"
            else {"nanochat_model_dir", "code_dir", "nanochat_npu_dir",
                  "eval_bundle_dir", "python_wheels_dir"}
        )
        payload["algorithm"]["inputs"] = [
            item for item in payload["algorithm"]["inputs"]
            if item["name"] in needed_inputs
        ]
        for item in payload["algorithm"]["inputs"]:
            item["remote"]["obs"]["obs_url"] = mapping[item["name"]]
        if stage == "training":
            payload["algorithm"]["inputs"].append({
                "name": "comparison_data_dir",
                "local_dir": "/home/ma-user/modelarts/inputs/comparison_data_dir_8",
                "access_method": "env",
                "remote": {"obs": {"obs_url": f"{record['run_root_obs_uri']}/sampled/"}},
            })
        for index, strategy in enumerate(config["strategies"], start=9):
            obs_uri = str(strategy.get("script_obs_uri") or "").strip()
            if not obs_uri or stage != "mixing":
                continue
            if not obs_uri.lower().endswith(".py"):
                raise ValueError("custom strategy OBS paths must point to a .py file")
            filename = obs_uri.rsplit("/", 1)[-1]
            local_dir = f"/home/ma-user/modelarts/inputs/strategy_dir_{index}"
            local_path = f"{local_dir}/{filename}"
            strategy["local_script_path"] = local_path
            payload["algorithm"]["inputs"].append({
                "name": f"strategy_{index}", "local_dir": local_dir,
                "access_method": "env", "remote": {"obs": {"obs_url": _clean_obs_uri(obs_uri)}},
            })
        env["AMT_WORKFLOW_CONFIG_JSON"] = json.dumps(
            config, ensure_ascii=False, separators=(",", ":")
        )
        payload["algorithm"]["outputs"][0]["remote"]["obs"]["obs_url"] = (
            record["run_root_obs_uri"] + "/"
        )
        return payload

    @staticmethod
    def _command(stage: str) -> str:
        return (
            "/bin/bash -c 'set -euo pipefail; "
            "PY311=$(command -v python3.11 || command -v python3 || true); "
            "test -n \"$PY311\" || { echo \"ERROR: Python not found\"; exit 2; }; "
            "PY_DEPS=/tmp/auto-mixture-python-packages; mkdir -p $PY_DEPS; "
            ": > $PY_DEPS/dask.py; "
            "if [ ! -d $PY_DEPS/lightgbm ]; then $PY311 -m pip install --no-index "
            "--no-deps --target $PY_DEPS /home/ma-user/modelarts/inputs/"
            "python_wheels_dir_7/lightgbm-4.6.0-py3-none-manylinux2014_aarch64.whl; fi; "
            "cd /home/ma-user/modelarts/user-job-dir/Auto-Mixture-Tool; "
            "export PYTHONPATH=$PWD/src:$PY_DEPS:${PYTHONPATH:-}; "
            "export AMT_PYTHON_EXECUTABLE=$PY311; "
            "$PY311 scripts/modelarts_runtime_check.py; "
            f"exec $PY311 -m auto_mixture_tool.modelarts.stage_runner {stage}' modelarts\n"
        )

    def _run(self, workflow_id: str) -> None:
        record = self.records[workflow_id]
        try:
            self._submit_and_wait(record, 0, "mixing", 15, 45)
            record["status"] = "MIXING_SUCCEEDED"
            record["progress"] = 50
            record["stage"] = "配比完成，正在自动提交训练评测作业"
            self._store(record)
            self._submit_and_wait(record, 1, "training", 60, 95)
            record.update(status="SUCCEEDED", progress=100, stage="全部作业完成")
        except Exception as exc:
            record["status"] = "FAILED"
            record["stage"] = "工作流失败"
            record["message"] = str(exc)
        self._store(record)

    def _submit_and_wait(
        self, record: dict[str, Any], index: int, stage: str,
        submitted_progress: int, running_progress: int,
    ) -> None:
        job = record["jobs"][index]
        response = self._client().submit(self._payload(record, stage))
        metadata = response.get("metadata", {})
        job_id = metadata.get("id") or response.get("id")
        if not job_id:
            raise RuntimeError(f"{stage} job response did not contain an id: {response}")
        job.update(id=str(job_id), status="SUBMITTED")
        record.update(status=f"{stage.upper()}_RUNNING", progress=submitted_progress,
                      stage=f"{job['name']} 已提交")
        self._store(record)
        while True:
            time.sleep(float(record["config"].get("poll_interval_seconds", 15)))
            response = self._client().get(str(job_id))
            status = _state(response).strip()
            normalized = status.lower()
            job["status"] = status or "RUNNING"
            record["progress"] = running_progress
            record["stage"] = f"{job['name']}: {job['status']}"
            self._store(record)
            if normalized in SUCCESS_STATES:
                job["status"] = "SUCCEEDED"
                return
            if normalized in FAILURE_STATES:
                raise RuntimeError(f"{job['name']} failed with status {status}")

    def _store(self, record: dict[str, Any]) -> None:
        with self._lock:
            self.records[record["id"]] = record
            self.directory.mkdir(parents=True, exist_ok=True)
            target = self.directory / f"{record['id']}.json"
            temporary = self.directory / f".{record['id']}.tmp"
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(target)

    def _load_disk(self) -> None:
        if not self.directory.exists():
            return
        for path in self.directory.glob("*.json"):
            if path.stem not in self.records:
                self.records[path.stem] = json.loads(path.read_text(encoding="utf-8"))
