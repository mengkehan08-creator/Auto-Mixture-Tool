# Auto-Mixture-Tool 架构说明

Auto-Mixture-Tool 将当前 QuaDMix、NanoChat 和 STEM 实验链路整理为可按 ID 装配的平台：

```text
API / YAML
  -> 数据过滤、Parquet 标准化与转换后校验
  -> 数据配比算法
  -> 训练框架
  -> 评测集/评测方法
  -> 本地或 HPC 执行
  -> 任务与结果记录
```

实际使用见 [USAGE.md](USAGE.md)，增加或切换模块见 [SWITCHING_COMPONENTS.md](SWITCHING_COMPONENTS.md)。

## 1. 设计原则

- 一个用户入口：`auto-mixture serve` 或 `auto-mixture run <yaml>`。
- 一个运行时注册中心：`PlatformService.__init__`。
- 每类组件一个 ID，不为组件组合复制 ID。
- 数据先通过完整校验，再生成命令计划。
- 算法和训练器使用数据插件验证后的原始 URI。
- `quadmix-platform` 仅是兼容 CLI，不维护第二套 API 或任务状态。

## 2. 九层结构

| 层 | 实现 | 当前状态 |
|---|---|---|
| 1 用户接口 | FastAPI、YAML CLI | 单一实现 |
| 2 编排 | `PipelineManager`、`PlatformService` | 统一注册和装配 |
| 3 数据检查 | `validate_dataset`、数据插件 | 全分片检查 |
| 4 配置 | `PipelineConfig` | 统一 `*_id` / `*_config` |
| 5 统一数据读取 | `dataset_id=stem-json-parquet` / `quadmix` | STEM JSON 转换或标准数据原生读取 |
| 6 配比算法 | `algorithm_id=quadmix` | 可扩展 Adapter |
| 7 训练 | `trainer_id=nanochat` | 与评测器解耦 |
| 7b 评测 | `evaluator_id=stem` | 可切任务和验证数据 |
| 8 执行 | `local`、`hpc-cluster` | 开发/生产后端 |
| 9 记录 | JSON JobRecord、算法结果 | 本地任务可跨进程读取 |

## 3. 组件装配

```python
class PlatformService:
    def __init__(self, workspace=None):
        self.datasets.register(QuadMixFormatValidator())
        self.algorithms.register(QuadMixAlgorithm())
        self.trainers.register(NanoChatTrainer())
        self.evaluators.register(StemValidator())
        self.executors.register(LocalExecutor())
        self.executors.register(HpcClusterExecutor())
```

当前注册数量少是有意设计：只公布已经接入主链路的实现。以后新增插件时在对应注册表增加一次，不复制其他模块。

## 4. 数据生命周期

1. `dataset_id` 选择数据契约。
2. 基础检查和数据插件共同验证 schema、类型、标签、质量、文本和分片。
3. STEM JSON 经质量门禁过滤、字段扁平化和 Parquet 二次校验后进入 QuaDMix；标准数据可直接读取。
4. 可选 `record_adapter` 将嵌套源字段映射到统一域/质量字段，并按 Schema 中的过滤规则拒绝不合格记录。
5. QuadMix 流式读取元数据，并按选中记录的物理行号回读文本。
6. 抽样校验返回 `filter_preview`；`full_scan=true` 返回全量兼容性报告；完整过滤统计写入 `pipeline_summary.json`。

这样避免了以前“CSV/JSON 校验通过，但 QuaDMix 把文件当作目录后失败”的问题。

## 5. 训练和评测解耦

`StemValidator.environment(evaluator_config)` 只负责生成评测环境：

- `EVAL_BENCHMARKS`
- `STEM_TASKS`
- `STEM_VALIDATION_DATA`

`PlatformService` 在编排时把环境传给选中的 Trainer。NanoChat 不再持有固定 Validator，也不再创建 `nanochat-stem`、`nanochat-custom` 等重复训练器。

## 6. 任务生命周期

- 任务创建后先写入 `<workspace>/result/.jobs/<job_id>.json`。
- 执行器返回或失败后再次原子更新记录。
- FastAPI 在应用生命周期内复用一个 `PipelineManager`。
- 服务重启后，`GET /api/v1/jobs/{job_id}` 可以从磁盘读取记录。

`local` 当前是同步执行器；`hpc-cluster` 负责提交远端任务。远端状态轮询、日志代理和取消需要与实际 HPC API 契约继续集成。

## 7. 规范契约代码

`auto_mixture_tool/core/` 中的 `UnifiedDataset`、`MixingAlgorithm`、`Trainer`、`Evaluator` 和 `CanonicalPipeline` 保留用于：

- Python 内直接组合组件；
- 纯标准库离线测试；
- 新实现的接口原型验证。

它不是另一套 HTTP/YAML 注册入口。正式运行时组件目录以 `/api/v1/components` 返回值为准。

## 8. 关键目录

```text
src/auto_mixture_tool/
  api/server.py                 单一 FastAPI 服务
  config/pipeline_config.py     YAML 规范化
  data/validator.py             组合数据校验
  plugins/
    format_validators/quadmix.py  数据插件
    algorithms/quadmix.py         配比插件
    trainers/nanochat.py           训练插件
    validators/stem.py             评测插件

src/quadmix_platform/
  interfaces.py                 Adapter 和规范契约
  service.py                    唯一运行时注册与编排中心
  components.py                 local / hpc-cluster 执行器
  dataset_inspector.py          多格式、全分片检查

```

## 9. 已知运行边界

- QuaDMix/NanoChat/STEM 真跑仍依赖 PyArrow、LightGBM、Torch、torch-npu、模型和验证数据。
- HPC 节点必须能访问命令计划中的路径，或由集群网关进行路径映射。
- 当前 100B STEM 数据直接使用 JSON 目录；大文件优先采用 JSONL/NDJSON，以便逐行流式读取。
