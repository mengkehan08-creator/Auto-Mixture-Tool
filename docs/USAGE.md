# Auto-Mixture-Tool 使用文档

Auto-Mixture-Tool 把数据校验、QuadMix 配比、NanoChat 训练、STEM 评测和执行后端组合为一条可配置流水线。

模块切换说明见 [SWITCHING_COMPONENTS.md](SWITCHING_COMPONENTS.md)；当前 STEM JSON 的字段映射、全量审查和过滤规则见 [DATASET_AUDIT.md](DATASET_AUDIT.md)。

## 1. 当前稳定运行路径

```text
YAML / HTTP API
  -> dataset_id=stem-json-parquet：过滤嵌套 STEM JSON，转成扁平 Parquet 并再次校验
  -> algorithm_id=quadmix：生成配比训练数据
  -> trainer_id=nanochat：训练模型
  -> evaluator_id=stem：配置 STEM 任务与验证数据
  -> executor_id=local | hpc-cluster：执行命令计划
```

运行时只有一套注册中心：`quadmix_platform.service.PlatformService`。`quadmix-platform` 命令保留为兼容别名，与 `auto-mixture` 使用同一 CLI 和同一 FastAPI 服务。

`auto_mixture_tool.core.CanonicalPipeline` 保留为面向对象契约和离线参照测试，不再作为另一套用户入口。

## 2. 安装

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
pip install -e .
```

基础依赖由 `pyproject.toml` 安装。真实 NPU 训练还需要在目标环境单独安装与 Ascend 版本匹配的 PyTorch、torch-npu、驱动和 CANN。

## 3. YAML 运行

```bash
auto-mixture run examples/configs/demo_pipeline.yaml
```

主配置字段：

| 字段 | 说明 | 当前值 |
|---|---|---|
| `dataset_uri` | 原始文件或数据目录 | 用户提供 |
| `schema_uri` | 数据列与域定义 | 用户提供 |
| `dataset_id` | 数据过滤、转换与校验插件 | `stem-json-parquet` |
| `algorithm_id` | 配比算法 | `quadmix` |
| `trainer_id` | 训练框架 | `nanochat` |
| `evaluator_id` | 评测集/评测方法 | `stem` |
| `executor_id` | 执行位置 | `local` / `hpc-cluster` |

完整模板见：

- `examples/configs/demo_pipeline.yaml`：本地/NPU 开发机。
- `examples/configs/demo_pipeline_hpc.yaml`：HPC API。

## 4. HTTP API

启动：

```bash
auto-mixture serve --host 0.0.0.0 --port 8080
```

接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/components` | 查询可切换组件 |
| POST | `/api/v1/datasets/inspect` | 校验数据集 |
| POST | `/api/v1/jobs` | 校验、编排并提交任务 |
| GET | `/api/v1/jobs/{job_id}` | 查询任务；进程重启后仍可读取本地任务记录 |

提交示例：

```bash
curl -X POST http://127.0.0.1:8080/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d @examples/platform/sample_job.json
```

任务记录保存在 `<workspace>/result/.jobs/`。本地执行器同步执行阶段；HPC 执行器返回集群提交状态和外部任务 ID。

## 5. 数据过滤、Parquet 转换和校验

当前数据插件接受：

- JSON、JSONL、JSONLines、NDJSON 或 Parquet 文件目录；
- JSON 数组、单对象或常见包裹数组；
- JSONL。

校验覆盖目录中的每个数据分片，不再只检查第一个文件。检查内容包括必需列、列类型、域标签、质量分、空文本、编码和重复分片。

当前 ModelArts 数据集直接配置为：

```yaml
dataset_uri: /home/ma-user/work/STEM_sample_100B_only_数理化生_json
schema_uri: /home/ma-user/work/Auto-Mixture-Tool/configs/schema_stem_sample_json.yaml
```

当前 STEM 配置使用 `dataset_id: stem-json-parquet`。流水线先按源 Schema 的过滤规则处理 JSON，再提取第一个领域为顶层 `domain`，提取五个质量分并写入分片 Parquet。转换完成后使用 `schema_stem_quadmix_parquet.yaml` 二次校验；没有合格记录或字段、类型、领域不符合要求时，以“数据格式不符合算法要求”终止。源 JSON 保持不变。

转换产物位于 `<output_uri>/prepared_parquet_<job_id>/`，过滤数量、拒绝原因、领域分布、输出列和二次校验结果写入 `<output_uri>/conversion_report_<job_id>.json`。

分片范围通过数字后缀配置，首尾均包含：

```yaml
dataset_config:
  shard_start: 0
  shard_end: 199   # part-00000 到 part-00199，共 200 份；后续改为 1000
```

编号按数值解析，不依赖补零宽度。源数据抽样校验、完整审查和 Parquet 转换使用同一范围。

需要跳过转换、直接读取已经符合算法契约的 JSON/JSONL/Parquet 时，可改用 `dataset_id: quadmix`。

实际 `part-*` 分片没有扩展名，平台会将其识别为逐行 JSON。`schema_stem_sample_json.yaml` 将嵌套质检字段映射为 QuadMix 的域和质量分，并按配置过滤。API 使用 `full_scan: true` 可获得全量过滤统计和算法兼容性报告。

```bash
curl -X POST http://127.0.0.1:8080/api/v1/datasets/inspect \
  -H "Content-Type: application/json" \
  -d '{"dataset_uri":"data.json","schema_uri":"schema.yaml","dataset_id":"stem-json-parquet"}'
```

## 6. 当前组件

| 家族 | ID | 作用 |
|---|---|---|
| dataset | `stem-json-parquet` | STEM JSON 过滤、字段提取、Parquet 转换和二次校验 |
| dataset | `quadmix` | 已标准化数据的原生校验与直接读取 |
| algorithm | `quadmix` | QuaDMix 配比算法 |
| trainer | `nanochat` | NanoChat mid-training |
| evaluator | `stem` | STEM 任务/验证集配置 |
| executor | `local` | 当前机器依次运行各阶段 |
| executor | `hpc-cluster` | POST 命令计划到 HPC API |

增加新组件只需实现对应 Adapter 并在 `PlatformService.__init__` 注册一次。不要复制注册表，也不要为“训练器 × 评测器”组合创建重复训练器 ID。

## 7. STEM 任务或验证集切换

```yaml
evaluator_id: stem
evaluator_config:
  benchmarks: stem
  tasks:
    - gsm8k
    - mmlu_stem
    - arc_easy
  validation_data_uri: /data/stem_validation.pt
```

只修改任务列表或验证数据路径不需要改 NanoChat 训练器。新增另一类评测方法时，新增 evaluator 插件并更改 `evaluator_id`。

## 8. 8 NPU 与 HPC

本地 8 NPU：

```yaml
algorithm_config:
  device_type: npu
  npu_devices: 8
trainer_config:
  npu_devices: 8
executor_id: local
```

HPC：

```yaml
executor_id: hpc-cluster
executor_config:
  endpoint: https://hpc.example.com/api/v1/jobs
  token_env: AMT_CLUSTER_TOKEN
```

集群节点必须能访问 CommandSpec 中的数据、代码、模型和输出路径，或者由集群网关负责路径映射和挂载。

## 9. 测试

```bash
python -m unittest discover -s tests -v
python tests/test_canonical_pipeline.py
python tests/test_json_dataset.py
python tests/test_manual_mixing.py
python tests/test_quadmix_algorithm.py
python tests/test_nanochat_trainer.py
python tests/test_stem_evaluator.py
python tests/test_p2_e2e.py
```

轻量测试不启动真实 NPU 训练。上线前还必须在目标环境完成 QuadMix → NanoChat → STEM 真跑。

## 10. 兼容字段

旧配置字段暂时映射如下：

| 旧字段 | 新字段 |
|---|---|
| `format_validator_id` | `dataset_id` |
| `validator_id` | `evaluator_id` |
| `validator_config` | `evaluator_config` |
| `nanochat-stem` | `trainer_id: nanochat` + `evaluator_id: stem` |

新文件应只使用新字段。运行时目录不再暴露已经移除的 `random`、`manual`、`core`、`custom`、`nanochat-stem`、`nanochat-custom` 命令式组件。
