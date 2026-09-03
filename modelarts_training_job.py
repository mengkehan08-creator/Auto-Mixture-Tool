"""ModelArts training-job submission sample.

Keep the sample's function structure unchanged. Before running, replace only
the values marked ``REPLACE_ME`` and set ``NODE_COUNT``. Job names are generated
automatically. Never commit a real Authorization value to Git.
"""

import json
from datetime import datetime

import requests


# One-click node switch: use any integer from 2 through 16. Each node has 8 NPUs.
NODE_COUNT = 2
if not 2 <= NODE_COUNT <= 16:
    raise ValueError("NODE_COUNT must be between 2 and 16")
JOB_NAME = f"auto-mixture-{NODE_COUNT}node-{datetime.now():%Y%m%d-%H%M%S}"


def update_parameter(parameters, name, new_value):
    """在 list[dict] 结构里，根据 name 修改 value。"""
    for item in parameters:
        if item.get("name") == name:
            item["value"] = new_value
            return
    parameters.append({"name": name, "value": new_value})


url = "REPLACE_ME_MODELARTS_TRAINING_JOBS_API"
headers = {
    "Content-Type": "application/json",
    "region": "REPLACE_ME_REGION",
    "Authorization": "REPLACE_ME_AUTHORIZATION",
}

job_data = {
    "kind": "job",
    "metadata": {
        # 每次提交使用唯一名称，避免复用旧的OBS节点同步标记。
        "name": JOB_NAME,
        "description": "Auto-Mixture: QuaDMix, NanoChat and STEM evaluation",
        "workspace_id": "REPLACE_ME_WORKSPACE_ID",
    },
    "algorithm": {
        "engine": {
            "engine_id": "",
            "engine_name": "",
            "engine_version": "",
            "image_url": "REPLACE_ME_IMAGE_URL",
            "run_user": "",
            "image_repo_id": "REPLACE_ME_IMAGE_REPO_ID",
            "image_id": "",
        },
        # 末尾的 modelarts 是 bash -c 的 $0，可隔离平台可能附加的命令参数。
        "command": (
            "/bin/bash -c 'set -euo pipefail; "
            "PY311=$(command -v python3.11 || command -v python3 || true); "
            "test -n \"$PY311\" || { echo \"ERROR: Python not found\"; exit 2; }; "
            "$PY311 -c \"import sys; assert sys.version_info[:2] == (3, 11), "
            "f\\\"Python 3.11 required, got {sys.version}\\\"\"; "
            "PY_DEPS=/tmp/auto-mixture-python-packages; "
            "mkdir -p $PY_DEPS /tmp/auto-mixture-python311; "
            "ln -sf $PY311 /tmp/auto-mixture-python311/python; "
            "ln -sf $PY311 /tmp/auto-mixture-python311/python3; "
            "export PATH=/tmp/auto-mixture-python311:$PATH; "
            # LightGBM does not need Dask here. Shadow the image's incompatible
            # optional Dask installation so LightGBM treats it as unavailable.
            ": > $PY_DEPS/dask.py; "
            "export PYTHONPATH=$PY_DEPS:${PYTHONPATH:-}; "
            "if [ ! -d $PY_DEPS/lightgbm ]; then "
            "echo \"Installing LightGBM from offline OBS wheel\"; "
            "$PY311 -m pip install --no-index --no-deps --target $PY_DEPS "
            "/home/ma-user/modelarts/inputs/python_wheels_dir_7/"
            "lightgbm-4.6.0-py3-none-manylinux2014_aarch64.whl; "
            "fi; "
            "export AMT_PYTHON_EXECUTABLE=$PY311; "
            "cd /home/ma-user/modelarts/user-job-dir/Auto-Mixture-Tool; "
            "export PYTHONPATH=/home/ma-user/modelarts/user-job-dir/"
            "Auto-Mixture-Tool/src:$PY_DEPS:${PYTHONPATH:-}; "
            "$PY311 scripts/modelarts_runtime_check.py; "
            "exec $PY311 -m auto_mixture_tool.cli run "
            "/home/ma-user/modelarts/user-job-dir/Auto-Mixture-Tool/"
            "examples/configs/modelarts_pipeline.yaml' modelarts\n"
        ),
        "parameters": [],
        "environments": {
            "MOX_OBS_SIGNATURE": "obs",
            "PYTHONUTF8": "1",
            "PYTHONUNBUFFERED": "1",
            "NUM_NPU": "8",
            "ASCEND_VISIBLE_DEVICES": "0,1,2,3,4,5,6,7",
            "AMT_RUN_ID": JOB_NAME,
            "AMT_RUN_OBS_URI": (
                "obs://bucket-pangu-green-guangzhou/s00944147/l00916525/"
                f"chengchao/runs/{JOB_NAME}/quadmix"
            ),
            "AMT_OBS_BACKEND": "auto",
            "AMT_EXPECTED_NODES": str(NODE_COUNT),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        },
        "code_dir": (
            "obs://bucket-pangu-green-guangzhou/s00944147/l00916525/"
            "Auto-Mixture-Tool/"
        ),
        "local_code_dir": "/home/ma-user/modelarts/user-job-dir",
        "working_dir": "/home/ma-user/modelarts/user-job-dir",
        "inputs": [
            {
                "name": "data_dir",
                "local_dir": "/home/ma-user/modelarts/inputs/data_dir_0",
                "access_method": "env",
                "remote": {
                    "obs": {
                        "obs_url": (
                            "obs://bucket-pangu-green-guangzhou/s00944147/"
                            "l00916525/chengchao/prepared_parquet_57ffce0ca0a2/"
                        )
                    }
                },
            },
            {
                "name": "nanochat_model_dir",
                "local_dir": "/home/ma-user/modelarts/inputs/nanochat_model_dir_1",
                "access_method": "env",
                "remote": {
                    "obs": {
                        "obs_url": (
                            "obs://bucket-pangu-green-guangzhou/s00944147/"
                            "l00916525/backup_0810/work/nanochat_model_dir/"
                        )
                    }
                },
            },
            {
                "name": "code_dir",
                "local_dir": "/home/ma-user/modelarts/inputs/code_dir_2",
                "access_method": "env",
                "remote": {
                    "obs": {
                        "obs_url": (
                            "obs://bucket-pangu-green-guangzhou/s00944147/"
                            "l00916525/Auto-Mixture-Tool/"
                        )
                    }
                },
            },
            {
                "name": "nanochat_npu_dir",
                "local_dir": "/home/ma-user/modelarts/inputs/nanochat_npu_dir_3",
                "access_method": "env",
                "remote": {
                    "obs": {
                        "obs_url": (
                            "obs://bucket-pangu-green-guangzhou/s00944147/"
                            "l00916525/backup_0810/work/nanochat-npu/"
                        )
                    }
                },
            },
            {
                "name": "quadmix_tokenizer_dir",
                "local_dir": "/home/ma-user/modelarts/inputs/quadmix_tokenizer_dir_4",
                "access_method": "env",
                "remote": {
                    "obs": {
                        "obs_url": (
                            "obs://bucket-pangu-green-guangzhou/s00944147/"
                            "l00916525/gpt-neox-tokenizer/"
                        )
                    }
                },
            },
            {
                "name": "proxy_validation_dir",
                "local_dir": "/home/ma-user/modelarts/inputs/proxy_validation_dir_5",
                "access_method": "env",
                "remote": {
                    "obs": {"obs_url": "REPLACE_ME_PROXY_VALIDATION_OBS_URL"}
                },
            },
            {
                "name": "eval_bundle_dir",
                "local_dir": "/home/ma-user/modelarts/inputs/eval_bundle_dir_6",
                "access_method": "env",
                "remote": {
                    "obs": {
                        "obs_url": (
                            "obs://bucket-pangu-green-guangzhou/s00944147/"
                            "l00916525/eval_bundle/"
                        )
                    }
                },
            },
            {
                "name": "python_wheels_dir",
                "local_dir": "/home/ma-user/modelarts/inputs/python_wheels_dir_7",
                "access_method": "env",
                "remote": {
                    "obs": {
                        "obs_url": (
                            "obs://bucket-pangu-green-guangzhou/s00944147/"
                            "l00916525/python_wheels/"
                        )
                    }
                },
            },
        ],
        "outputs": [
            {
                "name": "output_dir",
                "local_dir": "/home/ma-user/modelarts/outputs/output_dir_0",
                "remote": {
                    "obs": {
                        "obs_url": (
                            "obs://bucket-pangu-green-guangzhou/s00944147/"
                            "l00916525/chengchao/"
                        )
                    }
                },
            }
        ],
    },
    "spec": {
        "resource": {
            "policy": "regular",
            "flavor_id": "modelarts.pool.visual.8xlarge",
            "pool_id": "REPLACE_ME_POOL_ID",
            "node_count": NODE_COUNT,
        },
        "log_export_path": {},
        "runtime_type": "production",
        "public_network_config": {"public_network_type": ""},
    },
}


def main():
    print("=" * 50)
    print("开始创建训练作业...")
    print("=" * 50)

    # 常见修改：每次任务使用唯一名称；同步目录随名称自动变化。
    job_data["metadata"]["name"] = JOB_NAME
    job_name = job_data["metadata"]["name"]
    job_data["algorithm"]["environments"]["AMT_RUN_ID"] = job_name
    job_data["algorithm"]["environments"]["AMT_RUN_OBS_URI"] = (
        "obs://bucket-pangu-green-guangzhou/s00944147/l00916525/"
        f"chengchao/runs/{job_name}/quadmix"
    )

    # 运行参数：Auto-Mixture运行参数在modelarts_pipeline.yaml中修改。
    # update_parameter(job_data["algorithm"]["parameters"], "name", "value")

    # 环境变量。
    job_data["algorithm"]["environments"]["AMT_OBS_BACKEND"] = "auto"

    # 输入。
    item = next(i for i in job_data["algorithm"]["inputs"] if i["name"] == "data_dir")
    item["remote"]["obs"]["obs_url"] = (
        "obs://bucket-pangu-green-guangzhou/s00944147/l00916525/"
        "chengchao/prepared_parquet_57ffce0ca0a2/"
    )

    item = next(
        i for i in job_data["algorithm"]["inputs"] if i["name"] == "nanochat_model_dir"
    )
    item["remote"]["obs"]["obs_url"] = (
        "obs://bucket-pangu-green-guangzhou/s00944147/l00916525/"
        "backup_0810/work/nanochat_model_dir/"
    )

    item = next(i for i in job_data["algorithm"]["inputs"] if i["name"] == "code_dir")
    item["remote"]["obs"]["obs_url"] = (
        "obs://bucket-pangu-green-guangzhou/s00944147/l00916525/Auto-Mixture-Tool/"
    )

    item = next(
        i for i in job_data["algorithm"]["inputs"] if i["name"] == "nanochat_npu_dir"
    )
    item["remote"]["obs"]["obs_url"] = (
        "obs://bucket-pangu-green-guangzhou/s00944147/l00916525/"
        "backup_0810/work/nanochat-npu/"
    )

    item = next(
        i
        for i in job_data["algorithm"]["inputs"]
        if i["name"] == "quadmix_tokenizer_dir"
    )
    item["remote"]["obs"]["obs_url"] = (
        "obs://bucket-pangu-green-guangzhou/s00944147/l00916525/"
        "gpt-neox-tokenizer/"
    )

    item = next(
        i
        for i in job_data["algorithm"]["inputs"]
        if i["name"] == "proxy_validation_dir"
    )
    item["remote"]["obs"]["obs_url"] = "REPLACE_ME_PROXY_VALIDATION_OBS_URL"

    item = next(
        i
        for i in job_data["algorithm"]["inputs"]
        if i["name"] == "eval_bundle_dir"
    )
    item["remote"]["obs"]["obs_url"] = (
        "obs://bucket-pangu-green-guangzhou/s00944147/l00916525/eval_bundle/"
    )

    item = next(
        i
        for i in job_data["algorithm"]["inputs"]
        if i["name"] == "python_wheels_dir"
    )
    item["remote"]["obs"]["obs_url"] = (
        "obs://bucket-pangu-green-guangzhou/s00944147/l00916525/python_wheels/"
    )

    # 输出。
    item = next(i for i in job_data["algorithm"]["outputs"] if i["name"] == "output_dir")
    item["remote"]["obs"]["obs_url"] = (
        "obs://bucket-pangu-green-guangzhou/s00944147/l00916525/chengchao/"
    )

    resp = requests.post(url, headers=headers, json=job_data, verify=False)
    response = resp.json()
    print("服务端返回：", response)

    if response and "metadata" in response and "id" in response["metadata"]:
        job_id = response["metadata"]["id"]
        job_name = response["metadata"]["name"]

        print("\n" + "=" * 50)
        print("作业提交成功！")
        print(f"作业ID: {job_id}")
        print(f"作业名称: {job_name}")
        print(
            "链接: https://console.huaweicloud.com/modelarts/"
            f"?region={headers['region']}#/training/detail/{job_id}"
        )
        print("执行成功！")
        print("=" * 50)
    else:
        print("作业创建失败：响应数据中未找到作业ID")


if __name__ == "__main__":
    main()
