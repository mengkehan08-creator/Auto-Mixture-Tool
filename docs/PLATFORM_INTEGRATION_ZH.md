# QuaDMix 计算平台集成说明

本文描述 `quadmix_platform` 虚拟平台、QuaDMix 数据选择模块、NanoChat 训练验证模块和可切换 STEM 验证配置的边界与 API。平台层不复制 QuaDMix 算法；它把仓库已有入口包装成可替换的作业阶段。

## 1. 已实现的结构

```text
浏览器 platform_demo/
        │ REST /api/v1
        ▼
quadmix_platform.api          HTTP/API 边界
        │
quadmix_platform.service      检测门禁 + 流水线编排
        ├── dataset_inspector 数据文件和 Schema 抽样检测
        ├── AlgorithmAdapter  QuaDMix；以后可注册其它选择算法
        ├── TrainerAdapter    NanoChat；以后可注册其它训练方法
        ├── ValidatorAdapter  CORE / STEM / 自定义 STEM 参数
        └── ExecutorAdapter   hpc-cluster
                                      │
                                      ▼
                              平台高性能集群 API
```

核心文件：

| 路径 | 职责 | 是否应包含平台专有代码 |
|---|---|---|
| `src/quadmix/` | QuaDMix 算法、数据适配和原始流水线 | 否 |
| `nanochat_mid_compare/` | NanoChat 数据准备、训练和评估脚本 | 否；只接受参数/环境变量 |
| `src/quadmix_platform/interfaces.py` | 四类插件接口 | 是，保持稳定 |
| `src/quadmix_platform/components.py` | 仓库模块到平台命令的适配器 | 是 |
| `src/quadmix_platform/dataset_inspector.py` | 上传后数据门禁 | 是 |
| `src/quadmix_platform/service.py` | 组件选择和作业编排 | 是 |
| `src/quadmix_platform/api.py` | 演示 REST API | 是 |
| `platform_demo/` | 纯 HTML/CSS/JS 操作台 | 是 |
| `openapi/quadmix-platform.yaml` | 跨服务 API 契约 | 是 |

### 关键解耦原则

1. 数据上传服务不调用算法，只把对象存储 URI 和 Schema URI 交给检测 API。
2. 数据检测通过后才能创建作业；检测失败返回具体缺列、类型、空文本和领域错误。
3. 算法、训练器、验证器、执行器分别用 ID 选择。新增模块只实现一个接口并注册，不修改 API 契约。
4. `hpc-cluster` 把命令清单序列化为 JSON，提交到高性能集群 API（`executor_config.endpoint`）。
5. Token、密码不进入请求 JSON；只传密钥所在的环境变量名，实际密钥放平台 Secret Manager。

## 2. 本地启动虚拟平台

要求 Python 3.10+。完整算法运行需要安装仓库依赖；API 与 CSV/JSON/JSONL 预检只需要 PyYAML。

```bash
python -m pip install -e .
quadmix-platform serve --host 127.0.0.1 --port 8080
```

打开 `http://127.0.0.1:8080/api/v1/health` 确认服务。默认执行器 `hpc-cluster` 只在配置了 `executor_config.endpoint` 后才真正向集群提交；缺省只校验并渲染命令，不会启动 NPU 训练。

也可直接用 YAML 配置运行：

```bash
quadmix-platform run examples/configs/demo_pipeline.yaml
```

## 3. 数据要求和检测门禁

Schema 沿用 `DatasetSchema`：

```yaml
domain_col: domain
domain_names: [math, physics, biology]
quality_cols:
  - relevance
  - name: noise
    higher_better: false
text_col: text
char_count_col: char_count       # 可为 null，此时算法从 text 计算
row_in_shard_col: null
```

检测支持 Parquet、CSV、JSONL/JSON、TXT。QuaDMix 实际大规模运行推荐分片 Parquet。检测项包括：

- 必需列存在；质量列为数值；`char_count` 为整数；
- 抽样文本非空且为字符串；
- domain 非空，配置了 `domain_names` 时不允许未知领域；
- 单领域样本给出警告，因为多样性优化可能失去意义；
- 目录输入时递归选择第一个受支持文件做快速检测。

生产环境建议在快速检测后增加异步全量扫描，输出坏行清单和每个 shard 的统计。这个重任务应作为独立集群 Job，而不是阻塞上传 HTTP 请求。

## 4. REST API

完整机器可读定义见 `openapi/quadmix-platform.yaml`。

### 查看可切换组件

```http
GET /api/v1/components
```

返回 `algorithms / trainers / validators / executors` 四个列表，API 客户端据此动态渲染选项，不写死组件。

### 检测数据集

```http
POST /api/v1/datasets/inspect
Content-Type: application/json

{
  "dataset_uri": "/mounted-data/stem",
  "schema_uri": "/configs/schema_stem.yaml",
  "sample_size": 100
}
```

生产平台应把本地路径替换成 `s3://`、`obs://` 或内部 dataset ID，并在 API 网关之后增加 URI Resolver，将其挂载/下载到作业容器。不要让公网调用者提交任意服务器本地路径。

### 创建流水线作业

```http
POST /api/v1/jobs
Content-Type: application/json

{
  "dataset_uri": "/mounted-data/stem",
  "schema_uri": "/configs/schema_stem.yaml",
  "output_uri": "/outputs/run-20260812",
  "algorithm_id": "quadmix",
  "trainer_id": "nanochat-stem",
  "validator_id": "stem",
  "executor_id": "hpc-cluster",
  "algorithm_config": {
    "num_experiments": 500,
    "num_search": 5000,
    "device_type": "npu",
    "npu_devices": 8,
    "proxy_validation_set": "cap_v1"
  },
  "trainer_config": {
    "npu_devices": 8,
    "nanochat_repo": "/opt/nanochat",
    "model_dir": "/models/nanochat",
    "base_model_tag": "d28"
  },
  "validator_config": {
    "benchmarks": "stem",
    "tasks": ["gsm8k", "mmlu_stem", "arc_easy"],
    "validation_data_uri": "/datasets/custom_stem_eval.pt"
  },
  "executor_config": {
    "endpoint": "https://compute.internal/v1/jobs",
    "token_env": "QUADMIX_CLUSTER_TOKEN"
  }
}
```

返回值包含平台 job ID、集群 external ID、状态和标准化 `stages`。未配置 `endpoint` 时只校验并渲染命令，`SUCCEEDED` 代表命令生成成功，不代表真实训练完成。

### 查询作业

```http
GET /api/v1/jobs/{job_id}
```

演示服务只在内存保存记录。生产环境必须把 job、stage、external ID、状态、创建人和产物 URI 存入平台数据库，并由集群回调或状态轮询更新。

## 5. 集群 API 应接收什么

`hpc-cluster` 向 `executor_config.endpoint` 发出：

```json
{
  "name": "a1b2c3d4e5f6",
  "stages": [
    {
      "name": "quadmix-selection",
      "executable": "python",
      "args": [".../run_essential_web_v1.py", "--schema", "..."],
      "env": {},
      "cwd": "/workspace/quadmix"
    },
    {
      "name": "nanochat-train-evaluate",
      "executable": "bash",
      "args": [".../run_stem_experiment.sh"],
      "env": {"NUM_NPU": "8", "EVAL_BENCHMARKS": "stem", "STEM_TASKS": "gsm8k,mmlu_stem"},
      "cwd": "/workspace/quadmix"
    }
  ]
}
```

集群侧需要把它翻译为 Slurm、Kubernetes Job、Volcano、Ascend 平台任务或供应商 API。推荐返回：

```json
{"id":"cluster-job-8842","status":"SUBMITTED"}
```

阶段必须按顺序执行，第二阶段的 `QUADMIX_SAMPLED_DATA` 指向第一阶段输出。集群镜像内应包含本仓库、NanoChat 仓库、模型挂载和对应 CUDA/NPU 运行时。

## 6. 自定义和切换方法

### 新增算法

在 `components.py` 新建 `AlgorithmAdapter`，实现 `build(request, workspace)` 返回一个或多个 `CommandSpec`，然后在 `PlatformService.__init__` 注册。算法输出需通过约定的 `output_uri` 暴露给下一阶段。

### 新增训练器

实现 `TrainerAdapter`。训练器只从请求和上游输出构建命令，不应导入 QuaDMix 内部类。因此可以接入其它训练框架而不改变算法。

### 新增验证器和自定义 STEM

当前 `core` 和 `stem` 通过 `ValidatorAdapter` 产生环境契约：

- `EVAL_BENCHMARKS`：NanoChat 识别的 benchmark 组；
- `STEM_TASKS`：逗号分隔的自定义任务；
- `STEM_VALIDATION_DATA`：自定义验证数据地址。

本仓库的适配器会把这些变量传给 NanoChat 作业。选择自定义任务或数据时，`scripts/platform/run_nanochat_validation.py` 要求 NanoChat checkout 提供 `scripts.platform_validation.run_validation(config)`；缺少扩展会明确失败，绝不会静默忽略用户配置。该函数负责训练/评估并返回可 JSON 序列化结果。实际 NanoChat 分支应在它的评估注册表注册 `tasks`，并在提供 `validation_data_uri` 时优先加载该文件。若只使用 NanoChat 原生 `--eval-benchmarks=stem` 组，不设置自定义任务/数据即可直接运行原脚本。平台不解析 benchmark 细节。

要接入完全不同的验证工具，新增 ValidatorAdapter 并让对应 TrainerAdapter 使用其参数即可，不改 QuaDMix。

## 7. 生产平台中各接口放置位置

| 能力 | 推荐服务/位置 | 原因 |
|---|---|---|
| 浏览器 UI | 平台前端或静态 CDN | 不持有集群密钥 |
| `/components`、`/jobs` | 平台 API 网关后的 Orchestrator | 鉴权、审计、配额统一 |
| 上传文件 | 独立 Upload/Dataset Service → 对象存储 | 大文件不经过编排服务 |
| 快速 Schema 检测 | Dataset Service worker | 上传完成立即反馈 |
| 全量质量扫描 | 集群批处理 Job | 可扩展且不阻塞 HTTP |
| 算法/训练/验证镜像 | 集群镜像仓库 | 版本固定、结果可复现 |
| HPC Cluster Executor | Orchestrator 内部适配层 | 隔离各厂商/Slurm/K8s 差异 |
| API Token | Secret Manager 注入环境变量 | 不落库、不进日志、不进前端 |
| Job 状态 | PostgreSQL 等平台数据库 | 演示内存状态不可用于多实例 |
| 日志 | 集群日志系统，对外返回 URL | 避免 API 服务承载大量日志 |
| 输出数据/模型/报告 | 对象存储 `runs/{job_id}/...` | 跨节点共享和生命周期管理 |

推荐生产接口还应增加：取消作业、分页列表、集群回调、日志签名 URL、幂等键、用户/项目/配额字段。它们属于具体平台能力，因此没有塞入本次最小演示实现。

## 8. 安全与部署注意事项

- 演示服务器默认只监听 `127.0.0.1`，没有鉴权；不要直接暴露公网。
- 生产 API 要做 OIDC/JWT、RBAC、请求大小限制、URI 白名单、审计日志和租户隔离。
- 集群提交必须使用 HTTPS；Token 通过 `QUADMIX_CLUSTER_TOKEN` 等环境变量注入。
- 禁止把用户输入拼成 shell 字符串。本实现用 `executable + args + env` 的结构化命令让集群执行器安全转译。
- 作业镜像、Schema、数据快照、Git commit、模型 checkpoint 和随机种子都应记录到运行元数据。
- QuaDMix 完整训练依赖大内存和 GPU/NPU。本机 API 成功只证明接口和命令编排正确，不等价于完成算法训练。
