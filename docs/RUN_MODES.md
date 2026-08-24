# 两种运行模式

Auto-Mixture-Tool 只提供两个执行后端：本地八卡开发环境使用 `local`，高性能计算平台使用 `hpc-cluster`。数据校验、配比算法、训练器和评测器的选择方式在两种模式下完全相同，只有 `executor_id` 和 `executor_config` 不同。

## 1. 本地八卡开发环境

配置文件使用 `examples/configs/demo_pipeline.yaml`：

```yaml
executor_id: local

algorithm_config:
  device_type: npu
  npu_devices: 8

trainer_config:
  npu_devices: 8

executor_config:
  device_type: npu
  device_count: 8
```

三个卡数必须一致。执行器会向每个本地阶段注入：

```text
AMT_DEVICE_TYPE=npu
AMT_DEVICE_COUNT=8
NUM_NPU=8
RANK_SIZE=8
ASCEND_VISIBLE_DEVICES=0,1,2,3,4,5,6,7
```

运行：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
pip install -e .
auto-mixture run examples/configs/demo_pipeline.yaml
```

`local` 按顺序同步运行数据配比和训练/评测阶段。任一阶段返回非零退出码，任务立即变为 `FAILED`。可用 `executor_config.timeout_seconds` 限制每个阶段的最长时间；默认不限制。

## 2. 通过 API 提交到高性能计算平台

这里存在两层 API：

1. 用户向 Auto-Mixture-Tool 的 `POST /api/v1/jobs` 提交配比任务。
2. `hpc-cluster` 执行器把生成的命令阶段和资源配置 POST 到实际 HPC 平台的 `executor_config.endpoint`。

启动 Auto-Mixture-Tool API：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
export AMT_CLUSTER_TOKEN='<平台令牌>'
auto-mixture serve --host 0.0.0.0 --port 8080
```

HPC 配置示例见 `examples/configs/demo_pipeline_hpc.yaml`：

```yaml
executor_id: hpc-cluster
executor_config:
  endpoint: https://hpc.example.com/api/v1/jobs
  status_endpoint: https://hpc.example.com/api/v1/jobs/{job_id}
  token_env: AMT_CLUSTER_TOKEN
  timeout_seconds: 30
  queue: npu-production
  image: registry.example.com/auto-mixture-tool:latest
  working_dir: /home/ma-user/work/Auto-Mixture-Tool
  resources:
    nodes: 1
    npu: 8
    cpu: 64
    memory_gb: 512
  mounts:
    - source: /home/ma-user/work
      target: /home/ma-user/work
```

也可直接用 YAML 触发一次 HPC 提交：

```bash
auto-mixture run examples/configs/demo_pipeline_hpc.yaml
```

HPC 提交载荷包含 `name`、`components`、`stages`，以及配置中存在的 `queue`、`image`、`resources`、`mounts`、`working_dir`、`labels`、`environment`。平台至少应返回一个 JSON 对象：

```json
{"id": "hpc-job-42", "status": "queued"}
```

如果平台字段名不同，使用 `job_id_field` 和 `status_field`；如果状态值不同，使用 `status_map`：

```yaml
job_id_field: jobId
status_field: state
status_map:
  queued: SUBMITTED
  running: RUNNING
  completed: SUCCEEDED
  failed: FAILED
```

当配置了 `status_endpoint` 后，调用 Auto-Mixture-Tool 的 `GET /api/v1/jobs/{job_id}` 会携带远端任务 ID 查询 HPC API，并更新本地任务记录。令牌只从 `token_env` 指定的环境变量读取，不应写入 YAML。

### 2.1 ModelArts 完整流程任务

ModelArts 使用仓库根目录的独立提交入口：

```bash
cp .env.modelarts.example .env.modelarts
# 编辑 .env.modelarts，填写新的 Authorization、endpoint、资源池、镜像和 OBS 路径
python modelarts_training_job.py --dry-run
python modelarts_training_job.py
```

`.env.modelarts` 已被 Git 忽略。不要把 Authorization 写入 Python、YAML 或提交记录。

该脚本向 ModelArts `training-jobs` API 提交一个训练作业。远端容器依次执行：

```bash
cd /home/ma-user/modelarts/user-job-dir/Auto-Mixture-Tool
python -m pip install -e . --no-deps
auto-mixture run /home/ma-user/modelarts/user-job-dir/Auto-Mixture-Tool/examples/configs/modelarts_pipeline.yaml
```

容器内配置 `examples/configs/modelarts_pipeline.yaml` 使用 `executor_id: local`，在同一个八卡任务内完成数据校验、QuadMix、NanoChat、STEM 和结果写出。不能在这个配置里使用 `hpc-cluster`，否则会在 ModelArts 任务内部再次提交远端任务。

ModelArts 输入挂载约定：

| 输入 | 容器路径 | 环境配置 |
|---|---|---|
| STEM 原始数据 | `/home/ma-user/modelarts/inputs/data-url_0` | `MODELARTS_DATA_OBS_URL` |
| NanoChat 代码 | `/home/ma-user/modelarts/inputs/nanochat-repo_1` | `MODELARTS_NANOCHAT_REPO_OBS_URL` |
| NanoChat 模型目录 | `/home/ma-user/modelarts/inputs/nanochat-model_2` | `MODELARTS_NANOCHAT_MODEL_OBS_URL` |
| 结果输出 | `/home/ma-user/modelarts/outputs/train_url_0` | `MODELARTS_OUTPUT_OBS_URL` |

运行镜像必须预装 Torch、torch-npu、CANN 和项目依赖。远端使用 `pip install -e . --no-deps`，不会在任务启动时临时下载大型依赖。

## 3. 数据路径要求

提交任务前，Auto-Mixture-Tool 会在 API 服务所在机器执行数据集校验。因此 API 服务必须能读取：

```text
/home/ma-user/work/STEM_sample_100B_only_数理化生_json
/home/ma-user/work/Auto-Mixture-Tool/configs/schema_stem_sample_json.yaml
```

HPC 计算节点也必须通过共享文件系统或 `mounts` 使用相同路径。当前版本不会自动把控制机本地路径上传或改写成计算节点路径。

## 4. 选择规则

| 场景 | `executor_id` | 行为 |
|---|---|---|
| 八卡开发机调试和真跑 | `local` | 当前机器同步执行全部阶段 |
| 生产 HPC 平台 | `hpc-cluster` | 生成任务载荷并通过平台 API 提交 |

不要在开发机配置中填写 HPC endpoint，也不要用 `local` 启动生产平台任务。
