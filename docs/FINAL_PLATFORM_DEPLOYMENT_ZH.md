# QuaDMix 平台化最终部署手册

> 适用仓库：`liujin99/quadmix` 的 `refactor/structure` 分支及本仓库新增的平台适配代码  
> 文档用途：交付平台前端、平台后端、数据平台、集群调度、算法和运维团队共同实施  
> 当前代码根目录：`D:\HW\quadmix-hadoop`  
> 推荐生产运行目录：Linux `/opt/quadmix`

## 0. 先读结论

最终部署必须分为两个平面：

1. **平台控制面**：网页、API、数据检测入口、作业编排、数据库、鉴权和集群 API 适配。它不直接运行 NPU 训练。
2. **集群运行面**：QuaDMix 算法、NanoChat、验证集、模型、数据挂载、NPU/CUDA 运行时。所有重计算在这里运行。

当前仓库已经提供可工作的虚拟平台、REST 契约、数据抽样检测、组件注册和命令编排，但它仍是**集成原型**。正式上线前必须完成本文第 12 节列出的 P0 修改，尤其是：持久化作业、对象存储 URI 解析、预处理阶段、真实集群资源描述、状态回调、鉴权和生产 Web Server。

推荐最终架构：

```text
用户浏览器
    │ HTTPS / OIDC
    ▼
平台 API Gateway
    ├── Dataset Service ──► 对象存储 raw/schema/validation
    └── QuaDMix Orchestrator
            ├── PostgreSQL：job/stage/artifact/audit
            ├── Dataset Inspector：快速门禁
            └── Cluster Adapter ──► Slurm / K8s / Volcano / 厂商 HPC API
                                      │
                                      ▼
                              NPU/GPU Worker Image
                              ├── /opt/quadmix
                              ├── /opt/nanochat
                              ├── /mnt/datasets
                              ├── /mnt/models
                              ├── /mnt/validation
                              └── /mnt/runs/{job_id}
```

## 1. 重构后代码仓完整结构

以下是部署相关的最终逻辑结构。未列出的论文、历史分析和实验脚本仍保留在仓库中，但不属于平台 API 边界。

```text
quadmix/
├── pyproject.toml                         Python 包和 quadmix-platform 命令入口
├── requirements.txt                      QuaDMix CPU/通用依赖
├── README.md                              仓库总说明
│
├── src/
│   ├── quadmix/                           【纯算法包】集群运行面
│   │   ├── core/                          QuaDMix 核心公式、采样、代理模型
│   │   ├── pipeline/                      代理实验、优化、报告和调度
│   │   ├── data/                          Schema、数据适配器、分片元数据
│   │   ├── sampling/                      批采样
│   │   ├── npu/                           CPU/CUDA/NPU 设备封装
│   │   └── utils/                         通用工具
│   │
│   └── quadmix_platform/                  【平台适配层】控制面
│       ├── api.py                         HTTP API 服务
│       ├── cli.py                         serve / run --config 命令
│       ├── service.py                     数据门禁、组件选择、作业编排
│       ├── components.py                  QuadMix/NanoChat/Validator/Executor 适配
│       ├── dataset_inspector.py           CSV/JSONL/TXT/Parquet 抽样检测
│       ├── interfaces.py                  四类稳定插件接口
│       ├── registry.py                    组件注册表
│       └── models.py                      CommandSpec 和 JobRecord
│
├── scripts/
│   ├── runners/
│   │   └── run_essential_web_v1.py        QuaDMix 正式算法入口
│   ├── preprocess/
│   │   └── preprocess_essential_web_v1_sharded.py
│   │                                        Essential-Web 专用预处理入口
│   └── platform/
│       └── run_nanochat_validation.py     自定义 STEM 的 NanoChat 扩展门面
│
├── nanochat_mid_compare/                  【下游训练验证模块】集群运行面
│   ├── run_experiment.sh                  NanoChat + CORE/通用验证
│   ├── run_stem_experiment.sh             NanoChat + STEM 验证
│   ├── prepare_data.py                    NanoChat 训练数据准备
│   └── generate_report.py                 比较实验报告
│
├── configs/
│   ├── schema_essential_web.yaml          Essential-Web Schema
│   └── schema_stem.yaml                   STEM Schema 示例
│
├── platform_demo/                         【演示前端】控制面/CDN
│   ├── index.html
│   ├── app.js
│   └── styles.css
│
├── openapi/
│   └── quadmix-platform.yaml              平台 REST API 唯一机器可读契约
│
├── examples/platform/                     仅开发和联调用，不进生产数据卷
│   ├── sample_dataset.csv
│   ├── sample_schema.yaml
│   └── sample_job.json
│
├── tests/
│   └── test_platform.py                   平台适配层测试
│
└── docs/
    ├── FINAL_PLATFORM_DEPLOYMENT_ZH.md    本文
    ├── PLATFORM_INTEGRATION_ZH.md          API 和扩展接口补充说明
    ├── DATASET_SCHEMA_DESIGN.md            Schema 详细设计
    └── NPU_DEPLOYMENT.md                   原算法 NPU 环境参考
```

## 2. 哪些文件部署到哪里

### 2.1 平台前端/CDN

部署以下文件：

```text
platform_demo/index.html
platform_demo/app.js
platform_demo/styles.css
```

生产推荐位置：

```text
/srv/www/quadmix/                 Nginx 静态目录
或
对象存储/CDN /apps/quadmix/
```

生产需要修改 `platform_demo/app.js`：

- 演示版使用相对地址 `/api/v1/...`；如果前后端同域，可保持不变。
- 如果 API 是独立域名，应增加 `API_BASE_URL` 构建变量，例如 `https://platform.example.com/quadmix/api/v1`。
- 不得在 JS 中保存集群 Token、对象存储 Secret 或模型凭证。
- 登录、项目、租户、配额和权限选择应使用平台已有组件，不在此页面重复实现。

### 2.2 平台 API/编排服务

需要部署：

```text
src/quadmix_platform/
openapi/quadmix-platform.yaml
pyproject.toml
```

推荐安装位置：

```text
/opt/quadmix-control/
```

推荐方式有两种：

#### 方式 A：集成进已有平台后端（推荐）

将 `openapi/quadmix-platform.yaml` 导入平台 API 工程，并复用：

- `dataset_inspector.py` 的检测规则；
- `interfaces.py`、`models.py` 的组件/命令模型；
- `components.py` 的 QuaDMix 和 NanoChat 命令生成逻辑；
- `service.py` 的先检测、后提交顺序。

平台已有的鉴权、数据库、队列、对象存储和作业系统继续作为唯一实现。此时不在生产运行 `api.py` 的 `ThreadingHTTPServer`。

#### 方式 B：独立 Orchestrator 微服务

将 `quadmix_platform` 包装为 FastAPI/Flask/Django 服务，部署到 Kubernetes 或平台服务节点。当前 `api.py` 只用于本地演示，生产必须替换为 ASGI/WSGI Server，并接入数据库和鉴权。

### 2.3 集群 Worker 镜像

必须放入镜像：

```text
src/quadmix/
scripts/runners/
scripts/platform/
nanochat_mid_compare/
configs/
pyproject.toml
requirements.txt
```

建议镜像内位置固定为：

```text
/opt/quadmix/                  本仓库
/opt/nanochat/                 实际 NanoChat checkout
```

不要依赖控制面 Windows 路径或某个开发者主目录。所有生成的集群命令都应使用镜像内固定 Linux 路径。

### 2.4 数据、模型、验证集和输出卷

推荐统一挂载：

```text
/mnt/datasets/{dataset_id}/raw/           原始上传数据，只读
/mnt/datasets/{dataset_id}/schema.yaml    数据 Schema，只读
/mnt/datasets/{dataset_id}/prepared/      QuaDMix 标准预处理数据，只读
/mnt/validation/quadmix/                   CAP/STEM/CORE proxy 验证数据，只读
/mnt/validation/nanochat/                  NanoChat benchmark 数据，只读
/mnt/models/nanochat/tokenizer/            tokenizer.pkl 等，只读
/mnt/models/nanochat/base_checkpoints/     基础模型，只读
/mnt/models/nanochat/mid_checkpoints/      中训 checkpoint，可写
/mnt/runs/{job_id}/                        本次运行所有输出，可写
```

对象存储推荐键：

```text
datasets/{tenant}/{dataset_id}/raw/...
datasets/{tenant}/{dataset_id}/schema/schema.yaml
datasets/{tenant}/{dataset_id}/prepared/...
validations/{validator_id}/{version}/...
models/nanochat/{model_id}/...
runs/{tenant}/{project}/{job_id}/quadmix/...
runs/{tenant}/{project}/{job_id}/nanochat/...
```

## 3. 数据资产必须经过的生命周期

正式平台不能把任意上传文件直接传给 QuaDMix。正确流程：

```text
UPLOADED
  │
  ▼
QUICK_INSPECTED       抽样检查 Schema、类型、空文本、domain、quality
  │
  ▼
PREPROCESSING         计算/整理 domain、quality、char_count、分片索引
  │
  ▼
READY                 形成不可变 prepared dataset version
  │
  ▼
QUADMIX_RUNNING       数据选择与代理实验
  │
  ▼
SELECTED              sampled_dataset + optimal_parameters
  │
  ▼
NANOCHAT_RUNNING      可选下游训练
  │
  ▼
VALIDATING            CORE/STEM/自定义验证
  │
  ▼
SUCCEEDED / FAILED
```

当前 `dataset_inspector.py` 只负责 `QUICK_INSPECTED`。当前 `QuadMixAlgorithm` 将 `dataset_uri` 直接作为 `--preprocessed-dir`，所以生产提交前必须保证传入的是 `prepared/` 目录，而不是 `raw/`。

### 3.1 QuaDMix 输入 Schema

最少要求：

| 概念 | 要求 | 例子 |
|---|---|---|
| text | 必需字符串 | `text` |
| domain | 必需，字符串或整数 | `category_name` |
| quality | 至少一列数值 | `stem_relevance` |
| char_count | 可选整数 | `char_count_col` |
| row_in_shard | 可选稳定行号 | `source_record_idx` |

示例：

```yaml
domain_col: category_name
domain_names: [math, chemistry, biology, physics]
quality_cols:
  - stem_relevance
  - knowledge_value
  - name: noise_level
    higher_better: false
text_col: text
char_count_col: char_count
row_in_shard_col: source_record_idx
```

### 3.2 预处理实现选择

#### 已经包含 domain 和 quality 的平台数据

数据服务只需：

1. 按 Schema 校验和类型规范化；
2. 输出分片 Parquet；
3. 生成稳定行号和 `shard_index.json`；
4. 将 prepared URI 登记到 dataset version。

#### 原始 Essential-Web

可在集群阶段调用：

```bash
python /opt/quadmix/scripts/preprocess/preprocess_essential_web_v1_sharded.py \
  --input-dir /mnt/datasets/$DATASET_ID/raw \
  --output-dir /mnt/datasets/$DATASET_ID/prepared \
  --workers 128
```

该脚本带有 Essential-Web 专用列和质量处理逻辑，不应无条件用于其它数据集。其它数据必须实现独立 PreprocessorAdapter，或由平台 ETL 生成标准 prepared 数据。

## 4. 最终组件边界

### 4.1 AlgorithmAdapter

输入：prepared dataset、Schema、输出目录、算法参数。  
输出：`sampled_dataset`、`optimal_parameters.json`、报告和 proxy 实验元数据。

当前实现：`QuadMixAlgorithm`。新增其它算法时只新增 Adapter 和 Worker 入口，不改 NanoChat。

### 4.2 TrainerAdapter

输入：算法输出数据、基础模型、tokenizer、设备和训练参数。  
输出：mid checkpoint、训练日志和数据统计。

当前实现：`NanoChatTrainer` 和 `NoTrainer`。

### 4.3 ValidatorAdapter

输入：模型 checkpoint、benchmark 组、自定义任务或验证数据。  
输出：评估指标和报告。

当前实现：`core` 和 `stem`。验证器与 QuaDMix 的 proxy validation 是两件事：

- `algorithm_config.proxy_validation_set` 控制 QuaDMix 代理模型优化目标；
- `validator_id/validator_config` 控制 NanoChat 下游模型最终验证。

平台 UI 必须把两者分开显示，避免用户误认为是同一个验证集。

### 4.4 ExecutorAdapter

输入：标准化 stages、资源、镜像、挂载、密钥引用。  
输出：集群 job ID 和提交状态。

当前 `HpcClusterExecutor` 只发送 `name + stages`，正式平台要扩展资源和运行环境字段，见第 8 节。

## 5. 控制面 API 部署

API 契约：`openapi/quadmix-platform.yaml`。

当前接口：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/components` | 返回可切换组件 |
| POST | `/api/v1/datasets/inspect` | 抽样数据检测 |
| POST | `/api/v1/jobs` | 验证并创建流水线作业 |
| GET | `/api/v1/jobs/{job_id}` | 查询演示作业 |

生产 API Gateway 建议暴露：

```text
POST   /api/v1/datasets/{id}/inspect
POST   /api/v1/datasets/{id}/prepare
GET    /api/v1/datasets/{id}/versions/{version}
POST   /api/v1/quadmix/jobs
GET    /api/v1/quadmix/jobs
GET    /api/v1/quadmix/jobs/{id}
POST   /api/v1/quadmix/jobs/{id}/cancel
GET    /api/v1/quadmix/jobs/{id}/stages
GET    /api/v1/quadmix/jobs/{id}/artifacts
POST   /internal/v1/quadmix/jobs/{id}/callback
```

### 5.1 推荐生产请求

不要让浏览器提交服务器本地路径，提交平台资产 ID/URI：

```json
{
  "project_id": "project-1001",
  "dataset_id": "dataset-stem-42",
  "dataset_version": "v3",
  "prepared_uri": "s3://platform/datasets/team-a/dataset-stem-42/v3/prepared/",
  "schema_uri": "s3://platform/datasets/team-a/dataset-stem-42/v3/schema.yaml",
  "output_uri": "s3://platform/runs/team-a/project-1001/${job_id}/",
  "algorithm_id": "quadmix",
  "trainer_id": "nanochat-stem",
  "validator_id": "stem",
  "executor_id": "hpc-cluster",
  "algorithm_config": {
    "num_experiments": 500,
    "num_search": 5000,
    "device_type": "npu",
    "npu_devices": 8,
    "proxy_validation_set": "cap_v1",
    "seed": 42
  },
  "trainer_config": {
    "model_id": "nanochat-d28",
    "npu_devices": 8,
    "target_param_data_ratio": 0.5
  },
  "validator_config": {
    "benchmarks": "stem",
    "tasks": ["gsm8k", "mmlu_stem", "arc_easy", "arc_challenge"],
    "validation_asset_id": "stem-eval-v2"
  }
}
```

API 后端负责把资产 ID 解析成集群挂载路径。前端不能决定 `/mnt/...` 路径。

## 6. 平台数据库表/实体

当前 `service.py` 使用进程内 `dict` 保存作业，重启即丢失。生产至少需要：

### quadmix_job

```text
id, tenant_id, project_id, creator_id
dataset_id, dataset_version, schema_version
algorithm_id, trainer_id, validator_id, executor_id
request_json, status, external_id
image_digest, code_commit, created_at, started_at, finished_at
error_code, error_message
```

### quadmix_stage

```text
id, job_id, sequence, name, status, external_stage_id
command_json, resource_json, started_at, finished_at, exit_code
log_uri, error_message
```

### quadmix_artifact

```text
id, job_id, stage_id, type, uri, checksum, size, metadata_json
```

### dataset_inspection

```text
id, dataset_id, version, schema_uri, status
sample_size, report_json, created_at, inspector_version
```

状态更新必须使用事务或乐观锁。重复提交使用 `Idempotency-Key`，避免网络重试创建两个昂贵训练任务。

## 7. 集群 Worker 镜像

### 7.1 基础镜像

Ascend NPU 应使用平台批准并与节点驱动匹配的 CANN + PyTorch + `torch_npu` 镜像。不要在通用 Python 镜像里临时安装不匹配的 `torch_npu`。

镜像中需要：

```text
Python >= 3.10
numpy, pandas, pyarrow, scipy, scikit-learn, lightgbm
matplotlib, pyyaml, joblib
torch
torch_npu（Ascend）或匹配的 CUDA PyTorch（GPU）
transformers（相关 tokenizer/模型流程需要时）
bash, git（只读版本记录，可选）
```

### 7.2 镜像构建逻辑示例

以下是逻辑示例，基础镜像名和 `torch_npu` 安装必须由集群管理员替换：

```dockerfile
FROM <approved-cann-pytorch-image>

WORKDIR /opt/quadmix
COPY . /opt/quadmix
RUN python -m pip install --no-cache-dir -e /opt/quadmix

COPY <nanochat-checkout> /opt/nanochat

ENV PYTHONPATH=/opt/quadmix/src:/opt/nanochat
ENV NANOCHAT_REPO=/opt/nanochat
ENTRYPOINT ["/bin/bash", "-lc"]
```

生产构建应：

- 使用 lock 文件/内部 PyPI 固定所有依赖；
- 将 Git commit、构建时间和依赖清单写入 OCI label；
- 扫描镜像漏洞；
- 使用 digest 而不是 `latest`；
- 不把模型、数据或 Token 打入镜像。

## 8. 集群提交接口需要改成什么样

当前提交体只有：

```json
{"name": "job-id", "stages": [{"executable": "python", "args": [], "env": {}, "cwd": "/opt/quadmix"}]}
```

生产至少增加：

```json
{
  "name": "quadmix-job-id",
  "projectId": "project-1001",
  "image": "registry.internal/ai/quadmix@sha256:...",
  "queue": "npu-training",
  "priority": "normal",
  "callbackUrl": "https://platform.internal/internal/v1/quadmix/jobs/job-id/callback",
  "stages": [
    {
      "name": "quadmix-selection",
      "dependsOn": [],
      "command": ["python", "/opt/quadmix/scripts/runners/run_essential_web_v1.py", "..."],
      "resources": {"cpu": 192, "memoryGiB": 1200, "npu": 8},
      "mounts": [
        {"asset": "dataset-stem-42:v3", "path": "/mnt/datasets/input", "readOnly": true},
        {"asset": "quadmix-validation:cap-v1", "path": "/mnt/validation/quadmix", "readOnly": true},
        {"asset": "run:job-id", "path": "/mnt/runs/job-id", "readOnly": false}
      ],
      "env": [{"name": "HF_TOKEN", "secretRef": "hf-read-token"}]
    },
    {
      "name": "nanochat-train-evaluate",
      "dependsOn": ["quadmix-selection"],
      "command": ["bash", "/opt/quadmix/nanochat_mid_compare/run_stem_experiment.sh"],
      "resources": {"cpu": 192, "memoryGiB": 1000, "npu": 8},
      "mounts": [
        {"asset": "run:job-id", "path": "/mnt/runs/job-id", "readOnly": false},
        {"asset": "model:nanochat-d28", "path": "/mnt/models/nanochat", "readOnly": true}
      ]
    }
  ]
}
```

集群 API 推荐返回：

```json
{
  "id": "cluster-job-8842",
  "status": "SUBMITTED",
  "stages": [
    {"name": "quadmix-selection", "id": "stage-1"},
    {"name": "nanochat-train-evaluate", "id": "stage-2"}
  ]
}
```

若平台只支持单任务，不支持 DAG，则由 Orchestrator 在 stage 1 成功回调后提交 stage 2。不要在 API 进程里同步等待 NPU 作业。

## 9. QuaDMix 集群阶段

推荐命令：

```bash
python /opt/quadmix/scripts/runners/run_essential_web_v1.py \
  --schema /mnt/datasets/input/schema.yaml \
  --preprocessed-dir /mnt/datasets/input/prepared \
  --output /mnt/runs/$JOB_ID/quadmix \
  --num-experiments 500 \
  --num-search 5000 \
  --device-type npu \
  --npu-devices 8 \
  --val-set cap_v1 \
  --seed 42
```

注意：当前 `components.py` 尚未把 `seed`、`val_path`、`target_tokens`、batch 和训练步数等全部透传。生产需要建立允许列表并显式映射，禁止将任意用户参数直接拼接成 shell。

QuaDMix 输出：

```text
/mnt/runs/{job_id}/quadmix/
├── optimal_parameters.json
├── pipeline_summary.json
├── sampled_dataset/ 或 sampled_dataset.parquet
├── quadmix_report.md
├── figures...
└── proxy_experiments/
```

这些路径应在 stage 完成时登记为 artifact，而不是由前端猜测路径。

## 10. NanoChat 训练与验证阶段

运行前必须具备：

```text
/opt/nanochat/
/mnt/models/nanochat/tokenizer/tokenizer.pkl
/mnt/models/nanochat/base_checkpoints/{BASE_MODEL_TAG}/
/mnt/runs/{job_id}/quadmix/sampled_dataset
```

环境变量建议：

```bash
export QUADMIX_SAMPLED_DATA=/mnt/runs/$JOB_ID/quadmix/sampled_dataset
export PREPROCESSED_DATA_DIR=/mnt/datasets/input/prepared
export NANOCHAT_REPO=/opt/nanochat
export NANOCHAT_MODEL_DIR=/mnt/models/nanochat
export BASE_MODEL_TAG=d28
export RESULT_DIR=/mnt/runs/$JOB_ID/nanochat
export MID_CHECKPOINTS_OUTPUT_DIR=/mnt/runs/$JOB_ID/checkpoints
export NUM_NPU=8
export TARGET_PARAM_DATA_RATIO=0.5
export EVAL_BENCHMARKS=stem
```

### 10.1 原生 CORE/STEM 组

```bash
bash /opt/quadmix/nanochat_mid_compare/run_experiment.sh
# 或
bash /opt/quadmix/nanochat_mid_compare/run_stem_experiment.sh
```

### 10.2 自定义 STEM

平台传入：

```bash
export STEM_TASKS=gsm8k,mmlu_stem,arc_easy
export STEM_VALIDATION_DATA=/mnt/validation/custom/my_stem_eval.pt
```

然后调用：

```bash
python /opt/quadmix/scripts/platform/run_nanochat_validation.py \
  --experiment-script /opt/quadmix/nanochat_mid_compare/run_stem_experiment.sh
```

实际 `/opt/nanochat` 必须实现：

```python
# /opt/nanochat/scripts/platform_validation.py
def run_validation(config: dict) -> dict:
    # 1. 读取 config["tasks"] 和 config["validation_data_uri"]
    # 2. 完成训练/评估或调用 NanoChat 正式入口
    # 3. 将指标/报告写到 RESULT_DIR
    # 4. 返回可 JSON 序列化的摘要
    ...
```

如果没有这个扩展，适配器会明确失败，避免用户选择的自定义验证被静默忽略。

## 11. 配置和密钥放在哪里

### 11.1 普通配置

放在平台 Config Center、Kubernetes ConfigMap 或服务环境变量：

```text
QUADMIX_RUNTIME_ROOT=/opt/quadmix
NANOCHAT_RUNTIME_ROOT=/opt/nanochat
QUADMIX_WORKER_IMAGE=registry/...@sha256:...
QUADMIX_CLUSTER_ENDPOINT=https://cluster.internal/v1/jobs
QUADMIX_DEFAULT_QUEUE=npu-training
QUADMIX_CALLBACK_BASE=https://platform.internal/internal/v1/quadmix
QUADMIX_DATA_MOUNT_ROOT=/mnt/datasets
QUADMIX_MODEL_MOUNT_ROOT=/mnt/models
QUADMIX_RUN_MOUNT_ROOT=/mnt/runs
```

当前代码只直接支持请求中的 `executor_config.endpoint` 和 `token_env`。生产应改为服务端配置 endpoint，禁止普通用户在请求中指定任意 URL，以防 SSRF。

### 11.2 Secret

放在 Secret Manager/Kubernetes Secret/Vault：

```text
QUADMIX_CLUSTER_TOKEN
OBJECT_STORAGE_ACCESS_KEY / secretRef
HF_TOKEN
数据库凭据
镜像仓库拉取凭据
```

不得放在：

- `platform_demo/app.js`；
- `sample_job.json`；
- Git 仓库；
- API 请求日志；
- `CommandSpec.env` 明文；
- 训练输出目录。

## 12. 上生产前必须修改的文件

### P0：不完成就不能生产上线

| 文件/模块 | 必须修改 | 原因 |
|---|---|---|
| `src/quadmix_platform/api.py` | 替换为平台框架或 FastAPI；加入 OIDC/JWT、RBAC、request ID、审计、CORS、限流 | 当前 `http.server` 仅用于演示 |
| `src/quadmix_platform/service.py` | 用数据库 Repository 和异步队列替代内存 `jobs`；加入幂等、状态机、取消和回调 | 服务重启会丢失作业 |
| `src/quadmix_platform/dataset_inspector.py` | 增加 DatasetAssetResolver；只允许授权对象 URI；全量检测作为异步任务 | 当前直接读取本地路径 |
| `src/quadmix_platform/components.py` | 分离 control workspace 与 cluster runtime root；加入 image/resources/mounts/dependsOn；endpoint 改服务端配置 | 当前命令可能包含控制机路径，提交体过简 |
| `interfaces.py` / `models.py` | 扩展 StageSpec：镜像、资源、挂载、secretRef、依赖、重试、超时 | 集群无法据此分配真实资源 |
| 数据流水线 | 新增 PreprocessorAdapter/prepare stage 或接入平台 ETL | 抽样通过不代表已形成 QuaDMix prepared 数据 |
| 集群回调 | 新增内部 callback API，校验签名并更新 job/stage | 当前不能跟踪真实运行状态 |
| NanoChat checkout | 实现 `scripts.platform_validation.run_validation`，或取消 UI 中的自定义 STEM 选项 | 当前外部 NanoChat 实现不在本仓库 |
| 依赖构建 | 固定 torch/torch_npu/CANN/LightGBM 等版本并生成 lock/SBOM | 当前范围依赖不可保证复现 |

### P1：首个正式版本应完成

| 文件/模块 | 修改 |
|---|---|
| `platform_demo/app.js` | 接入平台登录、项目、dataset picker、model picker、真实 job 页面 |
| OpenAPI | 增加分页、取消、回调、artifact、错误码、幂等 Header |
| `components.py` | 显式支持 seed、val_path、target_tokens、训练 batch/steps 等参数允许列表 |
| 监控 | API 指标、队列时延、stage 时长、NPU 利用率、失败原因、成本指标 |
| Artifact | checksum、保留周期、访问权限、签名下载 URL |
| Schema 管理 | Schema 版本化、兼容性检查和数据血缘 |

### 不应该修改的区域

除算法需求本身发生变化，不要为了适配某个平台修改：

```text
src/quadmix/core/
src/quadmix/pipeline/optimizer.py
src/quadmix/core/quality_*.py
```

平台差异全部收敛在 Adapter、Executor、Asset Resolver 和部署配置中。

## 13. 推荐实施顺序

### 阶段 1：代码固化

```bash
git status
git add <本次平台化文件>
git commit -m "feat: add decoupled quadmix platform integration"
git tag quadmix-platform-v0.1.0
```

记录 commit 和镜像 digest。不要直接从未提交的开发目录构建生产镜像。

### 阶段 2：开发环境

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
quadmix-platform --workspace /path/to/quadmix serve --host 127.0.0.1 --port 8080
```

注意 `--workspace` 必须放在 `serve` 前面。

开发验收：

```bash
curl http://127.0.0.1:8080/api/v1/health
curl http://127.0.0.1:8080/api/v1/components
curl -X POST http://127.0.0.1:8080/api/v1/datasets/inspect \
  -H "Content-Type: application/json" \
  -d '{"dataset_uri":"examples/platform/sample_dataset.csv","schema_uri":"examples/platform/sample_schema.yaml"}'
quadmix-platform run examples/configs/demo_pipeline.yaml
```

### 阶段 3：构建和验证 Worker 镜像

在与生产相同型号 NPU 的测试节点验证：

```bash
npu-smi info
python -c "import torch, torch_npu; print(torch.npu.device_count())"
python -c "import quadmix; print(quadmix.__version__)"
test -f /opt/nanochat/scripts/mid_train.py
test -f /mnt/models/nanochat/tokenizer/tokenizer.pkl
```

先运行 1 个小数据/小 step 作业，再运行 8 卡 quick 作业，最后才放开 500/3000 experiments。

### 阶段 4：平台联调

1. 上传示例数据和 Schema；
2. 快速检测失败用例必须被阻断；
3. prepare 生成标准数据资产；
4. mock executor 核对最终 command、mount、resource；
5. 提交真实 cluster test queue；
6. 验证回调、日志、取消、失败重试和 artifact；
7. 验证 CORE 与 STEM 切换；
8. 验证自定义 STEM 缺扩展时明确失败；
9. 验证多租户不能读取他人 dataset/model/run。

### 阶段 5：生产发布

- 前端静态资源发布到平台/CDN；
- Orchestrator 滚动发布；
- 数据库 migration 先执行；
- Worker image 使用 digest 配置；
- 首次只开放测试项目/白名单用户；
- 观察至少一个完整长作业后再扩大配额。

## 14. 生产验收清单

### 功能

- [ ] 数据缺列、错误 dtype、空文本、未知 domain 能阻断提交；
- [ ] raw 数据不能跳过 prepare 直接运行；
- [ ] QuaDMix 和其它算法可独立注册/切换；
- [ ] NanoChat 和 `none` 可切换；
- [ ] CORE、STEM、自定义 STEM 行为与 UI 一致；
- [ ] stage 2 只在 stage 1 成功后运行；
- [ ] 输出报告、参数、sampled dataset、checkpoint 和指标已登记；
- [ ] 作业可以查询、取消，失败信息可定位；
- [ ] API/Orchestrator 重启后作业状态仍存在。

### 安全

- [ ] API 有 OIDC/JWT 和项目 RBAC；
- [ ] dataset/schema/output URI 由服务端解析并校验；
- [ ] 普通用户不能指定任意 cluster endpoint；
- [ ] Secret 只使用 secretRef；
- [ ] 命令采用 argv 数组，不拼接用户 shell；
- [ ] 日志会脱敏；
- [ ] 内部 callback 校验签名或 mTLS；
- [ ] 对象存储按租户隔离。

### 性能与可靠性

- [ ] 大文件上传不经过 Orchestrator；
- [ ] 全量检测和预处理是异步集群任务；
- [ ] API 提交在秒级返回 external job ID；
- [ ] 队列、超时、重试和并发配额明确；
- [ ] 8 卡进程数、batch、内存和共享内存通过压力测试；
- [ ] 训练日志和 checkpoint 不写满系统盘；
- [ ] 对象存储上传失败可恢复且不会标记成功。

### 可复现

- [ ] 保存代码 commit、镜像 digest、Schema checksum、dataset version；
- [ ] 保存模型/checkpoint ID、验证集版本和随机种子；
- [ ] 保存完整参数和依赖版本；
- [ ] 同配置重跑可以找到相同资产版本。

## 15. 回滚策略

控制面与 Worker 镜像必须独立版本化：

```text
API contract version       v1
orchestrator version       0.1.x
worker image digest        sha256:...
algorithm component        quadmix:2.0.0
trainer component          nanochat:<commit>
validator asset            stem-eval:v2
```

回滚控制面时保持数据库向后兼容；正在运行的作业继续使用提交时记录的 Worker digest。不要让新控制面修改已提交 stage 的命令。新作业切回上一稳定 digest 即可回滚算法运行环境。

## 16. 常见问题

### 网页能打开但真实任务不运行

检查 `executor_id` 是否仍是 `mock`。mock 的 `SUCCEEDED` 只表示命令生成成功。

### 数据检测通过但 QuaDMix 失败

快速检测只抽样文件。确认传给 `--preprocessed-dir` 的是 prepared 分片目录，且 `shard_index.json`、Schema 列和所有 shard 一致。

### 集群命令出现 Windows 路径

控制面使用了开发机 workspace。生产命令必须以 `/opt/quadmix` 为 runtime root，在 `components.py` 中分离 control root 与 worker runtime root。

### 自定义 STEM 立即失败

确认 `/opt/nanochat/scripts/platform_validation.py` 存在并实现 `run_validation(config)`；如果只使用 NanoChat 原生 STEM 组，提交时不要填写自定义 tasks/data。

### NPU 不可用或退回 CPU

核对节点 CANN、驱动、PyTorch、`torch_npu` 版本矩阵以及容器设备挂载。生产任务应在启动探针中失败，而不是允许昂贵训练静默退回 CPU。

### 作业查询不到

当前演示状态在内存中。生产必须完成数据库持久化；不能用 `api.py` 的内存服务承载正式作业。

## 17. 最终交付边界

本仓库当前已交付：

- QuaDMix 算法模块和稳定 CLI 入口；
- NanoChat 实验脚本边界；
- 数据 Schema 抽样检测；
- algorithm/trainer/validator/executor 可插拔接口；
- mock 与 REST 集群提交原型；
- 虚拟平台网页；
- OpenAPI、示例和自动化测试；
- 自定义 STEM 的显式扩展契约。

由目标计算平台团队完成：

- 用户、项目、租户和配额；
- 对象存储上传与资产解析；
- 数据全量检测和通用预处理服务；
- 数据库、消息队列和状态机；
- 集群资源、镜像、挂载、回调、日志和取消；
- Secret Manager 和审计；
- NanoChat checkout 与模型资产；
- 生产监控、告警和成本治理。

只有上述 P0 项完成并通过第 14 节验收，才应将虚拟平台从“命令编排原型”标记为“可生产部署的 QuaDMix 平台工具”。
