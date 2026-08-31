"""Submit the complete Auto-Mixture pipeline as one ModelArts training job.

The script deliberately keeps credentials and infrastructure identifiers out
of source control. Copy ``.env.modelarts.example`` to ``.env.modelarts``, fill
it, then run ``python modelarts_training_job.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


REPOSITORY_DIR = "/home/ma-user/modelarts/user-job-dir/Auto-Mixture-Tool"
PIPELINE_CONFIG = f"{REPOSITORY_DIR}/examples/configs/modelarts_pipeline.yaml"
REMOTE_COMMAND = (
    "/bin/bash -c 'set -euo pipefail; "
    f"cd {REPOSITORY_DIR}; "
    f"export PYTHONPATH={REPOSITORY_DIR}/src:${{PYTHONPATH:-}}; "
    "python3 --version; "
    f"exec python3 -m auto_mixture_tool.cli run {PIPELINE_CONFIG}' modelarts"
)


def load_env_file(path: str | Path) -> None:
    """Load a small KEY=VALUE file without overriding exported variables."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for line_number, raw_line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{env_path}:{line_number}: expected KEY=VALUE")
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip("'\"")
        if not name:
            raise ValueError(f"{env_path}:{line_number}: empty variable name")
        os.environ.setdefault(name, value)


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or value == "replace-me" or value.startswith("replace-with-"):
        raise ValueError(f"environment variable {name} is required")
    return value


def build_job_data(job_name: str | None = None) -> dict[str, Any]:
    """Build the ModelArts v2 training-job request body."""
    name = job_name or f"auto-mixture-{datetime.now():%Y%m%d-%H%M%S}"
    workspace_id = required_env("MODELARTS_WORKSPACE_ID")
    output_obs_url = required_env("MODELARTS_OUTPUT_OBS_URL").rstrip("/")
    job_data: dict[str, Any] = {
        "kind": "job",
        "metadata": {
            "name": name,
            "description": "Auto-Mixture complete pipeline: audit, mix, train and evaluate",
            "workspace_id": workspace_id,
        },
        "algorithm": {
            "engine": {
                "image_url": required_env("MODELARTS_IMAGE_URL"),
                "image_repo_id": required_env("MODELARTS_IMAGE_REPO_ID"),
            },
            "command": REMOTE_COMMAND,
            "parameters": [
                {"name": "pipeline-config", "value": PIPELINE_CONFIG},
                {"name": "device-type", "value": "npu"},
                {"name": "device-count", "value": "8"},
            ],
            "environments": {
                "PYTHONUTF8": "1",
                "PYTHONUNBUFFERED": "1",
                "NUM_NPU": "8",
                "ASCEND_VISIBLE_DEVICES": "0,1,2,3,4,5,6,7",
                "AMT_RUN_ID": name,
                "AMT_RUN_OBS_URI": f"{output_obs_url}/runs/{name}/quadmix",
                "AMT_OBS_BACKEND": os.environ.get("MODELARTS_OBS_BACKEND", "auto"),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
            },
            "code_dir": required_env("MODELARTS_CODE_OBS_URL"),
            "local_code_dir": REPOSITORY_DIR,
            "working_dir": REPOSITORY_DIR,
            "inputs": [
                _obs_input(
                    "data_dir",
                    "/home/ma-user/modelarts/inputs/data_dir_0",
                    required_env("MODELARTS_DATA_OBS_URL"),
                ),
                _obs_input(
                    "nanochat_model_dir",
                    "/home/ma-user/modelarts/inputs/nanochat_model_dir_1",
                    required_env("MODELARTS_NANOCHAT_MODEL_OBS_URL"),
                ),
                _obs_input(
                    "nanochat_npu_dir",
                    "/home/ma-user/modelarts/inputs/nanochat_npu_dir_3",
                    required_env("MODELARTS_NANOCHAT_REPO_OBS_URL"),
                ),
                _obs_input(
                    "quadmix_tokenizer_dir",
                    "/home/ma-user/modelarts/inputs/quadmix_tokenizer_dir_4",
                    required_env("MODELARTS_QUADMIX_TOKENIZER_OBS_URL"),
                ),
                _obs_input(
                    "proxy_validation_dir",
                    "/home/ma-user/modelarts/inputs/proxy_validation_dir_5",
                    required_env("MODELARTS_PROXY_VALIDATION_OBS_URL"),
                ),
            ],
            "outputs": [{
                "name": "train_url",
                "local_dir": "/home/ma-user/modelarts/outputs/output_dir_0",
                "remote": {"obs": {"obs_url": output_obs_url}},
            }],
        },
        "spec": {
            "resource": {
                "flavor_id": required_env("MODELARTS_FLAVOR_ID"),
                "node_count": int(required_env("MODELARTS_NODE_COUNT")),
                "pool_id": required_env("MODELARTS_POOL_ID"),
                "policy": required_env("MODELARTS_RESOURCE_POLICY"),
            },
            "log_export_path": {"obs_url": ""},
        },
    }
    nfs_server = os.environ.get("MODELARTS_NFS_SERVER_PATH", "").strip()
    if nfs_server:
        job_data["spec"]["volumes"] = [{
            "nfs": {
                "nfs_server_path": nfs_server,
                "local_path": os.environ.get("MODELARTS_NFS_LOCAL_PATH", "/mnt/sfsturbo"),
                "read_only": False,
            }
        }]
    return job_data


def _obs_input(name: str, local_dir: str, obs_url: str) -> dict[str, Any]:
    return {
        "name": name,
        "local_dir": local_dir,
        "access_method": "env",
        "remote": {"obs": {"obs_url": obs_url}},
    }


def submit_job(job_data: dict[str, Any], insecure: bool = False) -> dict[str, Any]:
    endpoint = required_env("MODELARTS_ENDPOINT")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "region": required_env("MODELARTS_REGION"),
        "Authorization": required_env("MODELARTS_AUTHORIZATION"),
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(job_data, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    context = ssl._create_unverified_context() if insecure else None
    try:
        with urllib.request.urlopen(request, timeout=60, context=context) as response:
            value = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ModelArts returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"cannot connect to ModelArts: {exc.reason}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("ModelArts response must be a JSON object")
    return value


def response_job(value: dict[str, Any]) -> tuple[str, str]:
    metadata = value.get("metadata")
    if not isinstance(metadata, dict) or not metadata.get("id"):
        raise RuntimeError("ModelArts response does not contain metadata.id")
    return str(metadata["id"]), str(metadata.get("name", ""))


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit the complete Auto-Mixture job to ModelArts")
    parser.add_argument("--env-file", default=".env.modelarts")
    parser.add_argument("--job-name", default=None)
    parser.add_argument("--dry-run", action="store_true", help="validate and print the request without submitting")
    parser.add_argument("--insecure", action="store_true", help="disable TLS certificate verification")
    args = parser.parse_args()

    try:
        load_env_file(args.env_file)
        job_data = build_job_data(args.job_name)
        if args.dry_run:
            print(json.dumps(job_data, ensure_ascii=False, indent=2))
            return
        response = submit_job(job_data, insecure=args.insecure)
        job_id, job_name = response_job(response)
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    region = os.environ["MODELARTS_REGION"]
    print("ModelArts job submitted successfully")
    print(f"job_id: {job_id}")
    print(f"job_name: {job_name}")
    print(f"console: https://console.huaweicloud.com/modelarts/?region={region}#/training/detail/{job_id}")


if __name__ == "__main__":
    main()
