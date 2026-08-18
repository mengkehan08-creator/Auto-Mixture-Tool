# Auto-Mixture-Tool 使用说明

本文档描述如何将原 QuaDMix 仓库重构为一个**可插拔的数据配比工具平台**（Auto-Mixture-Tool）。平台把数据集校验、配比算法、训练/验证方法、集群执行四层解耦，使 QuadMix 成为默认插件，同时支持后续无缝替换为其他算法或验证方法。

对应的可编辑架构图见：`docs/QuadMix-工具化重构模块框架图.pptx`。

---

## 1. 设计目标

把“QuadMix 实验代码仓”重构为：

> **统一数据输入 + 插件化配比算法 + 插件化训练框架 + 插件化评测方法 + 集群调度 + 统一实验管理** 的数据配比实验工具平台。

四个核心契约（Phase 2 已落地，接口定义与进度见 §8.1）：

- **统一数据抽象（Dataset Interface）**：各种原始数据（`text/domain`、`content/category`、`instruction/response/subject` …）统一转换为 `Sample(id, text, domain, metadata)`，算法不再关心原始格式。
- **算法可替换（MixingAlgorithm）**：QuadMix / Random / Manual / 未来的 LongTailMix 都实现 `fit / select / export`，Pipeline 不关心内部。
- **训练可替换（Trainer）**：NanoChat / Qwen / LLaMA / 自研 Trainer 实现同一接口。
- **验证可替换（Evaluator，与 Trainer 解耦）**：STEM / Coding / MMLU / GSM8K / Custom 实现同一接口，可任意组合。

配套约束：

- **先校验，再运行**：数据集必须先通过 schema 校验、统计校验、以及**可替换的数据格式合规校验**，才能进入下游。
- **API 独立可见**：FastAPI 暴露组件列表、数据集校验、任务提交、任务查询，直接对接高性能集群。
- **集群执行双后端**：dev 用 `local`（本地子进程），生产用 `hpc-cluster`（HPC 集群 API）；算法/训练/验证的代码与“在哪台机器运行”彻底分离。

> 完整接口与使用说明（数据/算法/验证/训练/评估接口 + 注册调整）见 [`docs/USAGE.md`](USAGE.md)。

---

## 2. 模块架构

| 层级              | 模块（契约）                                | 职责                                                         |
| --------------- | ------------------------------------- | ---------------------------------------------------------- |
| 1 用户接口层         | **API** / **YAML 配置文件**               | 人类或上游系统提交实验，统一入口，不要求改代码路径                                  |
| 2 实验编排层         | `PipelineManager` / `PlatformService` | 校验 → 选插件 → 编排 → 提交执行（不执行算法本身）                              |
| 3 数据检测与验证层      | `data.validator` + **可替换格式校验**        | 文件/编码/字段/标签/质量/重复 等检查；通用检查与算法专属检查分离                        |
| 4 配置管理层         | `PipelineConfig` + YAML               | dataset / algorithm / training / evaluation / cluster 五类配置 |
| 5 **统一数据抽象层**   | `UnifiedDataset` / `Sample`           | 隔离原始格式与算法实现（见 `core/dataset.py`）                           |
| 6 **数据配比算法插件层** | `MixingAlgorithm`（fit/select/export）  | QuadMix / Random / Manual / 自定义                            |
| 7 **训练与验证插件层**  | `Trainer` + `Evaluator`（二者分离）         | NanoChat(Trainer) + STEM/Coding(Evaluator)                 |
| 8 分布式执行与集群层     | `ExecutorAdapter`                     | `local`（dev 子进程）/ `hpc-cluster`（HPC 集群 API，决定“在哪算”） |
| 9 结果分析与实验管理层    | `ResultAnalyzer`                      | loss、STEM/Coding 分数、消融对比、实验报告                              |

> 第 6/7 层同时保留 `AlgorithmAdapter` / `TrainerAdapter` / `ValidatorAdapter`（它们把组件编译成 `CommandSpec` 交给集群执行），作为**集群执行策略**；`MixingAlgorithm` / `Trainer` / `Evaluator` 是**组件契约**，通过 `core/` 中的桥接类把现有命令式组件接入。

---

## 3. 目录结构

```
src/
├── auto_mixture_tool/              # 新增：工具化平台层
│   ├── __init__.py                 # 对外门面
│   ├── cli.py                      # 命令行入口
│   ├── api/server.py               # FastAPI 服务
│   ├── pipeline.py                 # PipelineManager 编排器
│   ├── config/pipeline_config.py   # YAML 配置加载 
│   ├── data/validator.py           # 扩展数据集校验（含可替换格式校验）
│   ├── results/analysis.py         # 结果分析器
│   ├── core/                       # ★ 规范契约实现（Phase 1 定义 + Phase 2 抽入真实逻辑）
│   │   ├── dataset.py              # UnifiedDataset / Sample（CSV/JSON/JSONL/Parquet 加载 + JSON 写出）
│   │   ├── mixing.py               # MixingAlgorithm 参照实现(Random) + 命令桥接
│   │   ├── quadmix_algorithm.py    # quadmix-core：抽入真实 src/quadmix 的 QuaDMixPipeline
│   │   ├── training.py             # Trainer 参照实现(NoOp) + 命令桥接
│   │   ├── nanochat_trainer.py     # nanochat-core：抽入真实 nanochat_mid_compare 训练
│   │   ├── evaluation.py           # Evaluator 参照实现(Stub) + 命令桥接
│   │   ├── stem_evaluator.py       # stem-core：抽入真实 STEM 评估
│   │   ├── registry.py             # 统一注册表（按 id 装配组件）
│   │   └── pipeline.py             # CanonicalPipeline 端到端编排（9 层）
│   └── plugins/
│       ├── base.py                 # 四个 Adapter 基类 + 四个核心接口再导出
│       ├── algorithms/             # 算法插件（quadmix / random / manual）
│       ├── trainers/               # 训练插件（nanochat）
│       ├── validators/             # 验证插件（stem / custom）
│       ├── format_validators/      # ★ 可替换的数据格式合规校验插件
│       │   └── quadmix.py          # 默认 QuadMix 格式校验器
│       └── executors/              # 执行器插件目录（local/hpc-cluster 由 quadmix_platform.components 注册）
├── quadmix/                        # 原 QuadMix 算法实现（保持不变，Phase 2 抽入接口）
├── quadmix_platform/               # 原平台抽象层
│   ├── interfaces.py               # ★ 四个核心接口 + 四个 Adapter + FormatValidatorAdapter
│   ├── components.py               # 内置 QuadMix/验证/训练/执行器组件
│   ├── service.py                  # 注册中心
│   └── api.py / cli.py             # 原入口（仍可用）
├── scripts/platform/               # 插件调用的可执行脚本
│   ├── run_random_mixing.py
│   ├── run_manual_ratio.py
│   └── run_nanochat_validation.py
└── examples/configs/
    └── demo_pipeline.yaml          # 完整示例配置
```

---

## 4. 快速开始

### 4.1 安装

在已具备 PyYAML、NumPy、Pandas、PyArrow、LightGBM、PyTorch 的集群环境中：

```bash
cd Auto-Mixture-Tool
pip install -e .
```

本地测试若缺少依赖，可临时把外部 site-packages 加入 `PYTHONPATH`：

```bash
# 示例：复用已有 venv 的 PyYAML
export PYTHONPATH="C:/Users/<user>/.hf-cli/venv/Lib/site-packages:$PYTHONPATH"
```

### 4.2 启动 API 服务

```bash
auto-mixture serve --host 0.0.0.0 --port 8080
```

接口：

| 方法   | 路径                         | 说明                                            |
| ---- | -------------------------- | --------------------------------------------- |
| GET  | `/api/v1/health`           | 健康检查                                          |
| GET  | `/api/v1/components`       | 组件目录                                          |
| POST | `/api/v1/datasets/inspect` | 数据集校验（含可替换格式校验，请求体带 `format_validator_id`）    |
| POST | `/api/v1/jobs`             | 提交任务（请求体带 `format_validator_id`，缺省 `quadmix`） |
| GET  | `/api/v1/jobs/{job_id}`    | 查询任务                                          |

`POST /api/v1/datasets/inspect` 返回 JSON 包含：

- `valid` / `errors` / `warnings`：合并了结构性校验与格式校验的结果；
- `base`：底层 `inspect_dataset` 的结构性校验输出；
- `statistics`：长度 / 重复率 / 质量分 / 域分布等扩展统计；
- `format_check`：格式校验模块自身的详细结果（`details` 含标签缺失数、非预期标签、各质量列空值率等）。

示例提交（默认格式校验 `quadmix`；`examples/platform/sample_job.json` 已含全部字段）：

```bash
curl -X POST http://127.0.0.1:8080/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d @examples/platform/sample_job.json
```

### 4.3 通过 YAML 配置文件运行

```bash
auto-mixture run examples/configs/demo_pipeline.yaml
```

流程：

1. 读取 YAML 中的插件选择与参数。
2. 校验数据集。
3. 由算法插件生成 `CommandSpec`。
4. 由训练/验证插件生成下游执行命令。
5. 提交给选定的执行器。
6. 返回 `job_id`。

### 4.6 用规范契约跑端到端（CanonicalPipeline）

除了上面的“命令委派”运行时（`PipelineManager` → `PlatformService` →  
`CommandSpec`），平台还提供基于 Phase 1 规范契约的**面向对象编排器**  
`CanonicalPipeline`（`src/auto_mixture_tool/core/pipeline.py`）。它把  
`MixingAlgorithm`（第 6 层）/ `Trainer`（第 7a 层）/ `Evaluator`（第 7b 层）  
统一编排成一次端到端运行，与具体执行机制（`local` 子进程 / `hpc-cluster` 集群 API）解耦。

**模式一：in-process 参照实现（纯标准库，离线可跑）**

```python
from auto_mixture_tool.core.pipeline import CanonicalPipeline

pipe = CanonicalPipeline.reference(seed=1, fraction=0.75)   # Random + NoOp + Stub
result = pipe.run(
    dataset_uri="./examples/platform/sample_dataset.csv",
    output_dir="./runs/run_01",
    job_id="run_01",
)
print(result["status"])                 # COMPLETED
print(result["stages"]["unify"])        # 数据集统一后的 size / domains
print(result["stages"]["mixing"])       # selected_size + mixed_uri
print(result["metrics"])                # 评估指标
```

`CanonicalPipeline.reference()` 用 `RandomMixingAlgorithm` + `NoOpTrainer` +  
`StubEvaluator` 证明契约闭环，**不需要 NumPy / Pandas**，适合离线验证与单测  
（`tests/test_canonical_pipeline.py`）。

**模式二：command 桥接（对接集群真实执行）**

把现有的 `AlgorithmAdapter` / `TrainerAdapter` / `ValidatorAdapter` 通过  
`CommandDrivenMixingAlgorithm` / `CommandDrivenTrainer` / `CommandDrivenEvaluator`  
桥接到规范契约。`fit/select/export/train` 不再就地执行，而是编译出命令计划  
（`mixing_plan.json` / `train_plan.json`），由 `ExecutorAdapter` 在集群侧运行：

```python
from auto_mixture_tool.core.mixing import CommandDrivenMixingAlgorithm
from auto_mixture_tool.core.training import CommandDrivenTrainer
from auto_mixture_tool.core.evaluation import CommandDrivenEvaluator

pipe = CanonicalPipeline(
    algorithm=CommandDrivenMixingAlgorithm(quadmix_adapter, workspace="./ws"),
    trainer=CommandDrivenTrainer(nanochat_adapter, workspace="./ws"),
    evaluator=CommandDrivenEvaluator(stem_validator, config={}),
    mode="command",
)
result = pipe.run(dataset_uri="./data/in.csv", output_dir="./runs/cmd")
# result["stages"]["mixing"]["mixed_uri"] 指向序列化命令计划，供执行器消费
```

两种模式共用同一套编排代码，区别只在组件实现——这正是“可插拔平台”的核心。

**模式三：Phase 2 真实子类（抽入 QuadMix / NanoChat / STEM）**

`CanonicalPipeline` 直接装配 Phase 2 抽出的真实实现；算法在进程内真实选子集，  
训练/评估启动器以 `dry_run=True` 离线验证命令、去掉则真跑集群任务：

```python
from auto_mixture_tool.core import (
    CanonicalPipeline, ManualRatioMixingAlgorithm,
    NanoChatTrainer, STEMEvaluator,
)

pipe = CanonicalPipeline(
    algorithm=ManualRatioMixingAlgorithm(            # 进程内真实选子集
        domain_ratios={"web": 0.5, "science": 0.25, "code": 0.25}, seed=7),
    trainer=NanoChatTrainer(dry_run=True, base_model_tag="d28"),   # 真实训练启动器
    evaluator=STEMEvaluator(tasks=["algebra"], dry_run=True),      # 真实评估启动器
    mode="inprocess",
)
result = pipe.run(dataset_uri="./data/in.csv", output_dir="./runs/p2")
# result["components"] -> {algorithm: manual-core, trainer: nanochat-core, evaluator: stem-core}
```

也可直接用规范契约注册表按 id 装配（见 `src/auto_mixture_tool/core/registry.py`）：

```python
from auto_mixture_tool.core import CanonicalPipeline, get_algorithm, get_trainer, get_evaluator

pipe = CanonicalPipeline(
    algorithm=get_algorithm("quadmix-core"),         # 抽入 src/quadmix 的真实实现
    trainer=get_trainer("nanochat-core"),
    evaluator=get_evaluator("stem-core"),
)
```

> 注：`quadmix-core` 的 `fit` 需要数据带质量分（`quality_cols`）且注入 `proxy_runner`  
> （训练 1M 参数代理模型）；`nanochat-core` / `stem-core` 真跑需 nanochat + NPU。  
> 离线环境这三者的重型依赖缺失，仅验证契约与 `dry_run` 命令；完整执行见 §8.1 状态列。

---

## 5. 配置说明

一个完整配置包含四个插件选择 + 四个插件参数区：

```yaml
dataset_uri: ./temp/preprocessed
schema_uri: ./configs/schema_essential_web.yaml
output_uri: ./result/demo_run

algorithm_id: quadmix      # 可选：quadmix / random / manual
trainer_id: nanochat-stem  # 可选：none / nanochat-core / nanochat-stem / nanochat-custom
validator_id: stem         # 可选：core / stem / custom
executor_id: local          # dev：本地子进程；生产改 hpc-cluster（需配 endpoint）
format_validator_id: quadmix  # 可选：quadmix（可替换的数据格式校验模块）

algorithm_config:
  num_experiments: 8
  num_search: 1000
  device_type: cpu
  npu_devices: 1
  proxy_validation_set: cap_v1

trainer_config:
  npu_devices: 8
  target_param_data_ratio: 0.5
  nanochat_repo: /opt/nanochat
  model_dir: /models/nanochat
  base_model_tag: d24

validator_config:
  benchmarks: stem
  tasks:
    - gsm8k
    - mmlu_stem
    - arc_easy

executor_config: {}
```

---

## 6. 插件系统

### 6.1 注册入口（唯一）

> **所有插件只在 `src/quadmix_platform/service.py` 的 `PlatformService.__init__` 中注册一次**，这就是运行时真正生效的注册入口（API / YAML / `PipelineManager` 全部走 `PlatformService`）。不要在其他地方再维护一份注册表。

四个注册表对象分别为：`self.algorithms` / `self.validators` / `self.trainers` / `self.executors`（均为 `ComponentRegistry`）。新增任意插件只需两步：写文件 → 在 `PlatformService.__init__` 里 `import` 并 `.register(...)`。

### 6.2 新增算法插件

1. 在 `src/auto_mixture_tool/plugins/algorithms/` 新建文件。
2. 继承 `AlgorithmAdapter`，实现 `build(request, workspace) -> list[CommandSpec]`：

```python
from auto_mixture_tool.plugins.base import AlgorithmAdapter, CommandSpec

class MyAlgorithm(AlgorithmAdapter):
    id = "my-algo"                      # 选插件时使用的唯一 id
    display_name = "My Algorithm"

    def build(self, request, workspace):
        config = request.get("algorithm_config", {})
        return [CommandSpec(
            name="my-stage",
            executable="python",
            args=[str(workspace / "scripts" / "my_algo.py"), ...],
            cwd=str(workspace),
            env={"KEY": str(config.get("key", "default"))},
        )]
```

1. 在 `src/quadmix_platform/service.py` 的 `PlatformService.__init__` 中注册：

```python
from auto_mixture_tool.plugins.algorithms.my_algo import MyAlgorithm
...
self.algorithms.register(MyAlgorithm())   # 加在已有算法注册之后即可
```

### 6.3 新增训练器插件

`TrainerAdapter` 接口只要求实现 `build(request, workspace) -> list[CommandSpec]`。  
若训练器依赖某个验证方法，请在**构造时注入**对应的 `ValidatorAdapter`，并在 `build` 内调用  
`self.validator.environment(request["validator_config"])` 生成环境变量（参考内置 `NanoChatTrainer`）：

```python
from auto_mixture_tool.plugins.base import CommandSpec, TrainerAdapter, ValidatorAdapter

class MyTrainer(TrainerAdapter):
    id = "my-trainer"
    display_name = "My Trainer"

    def __init__(self, validator: ValidatorAdapter) -> None:
        self.validator = validator          # 与验证方法解耦，可自由组合

    def build(self, request, workspace):
        vconfig = request.get("validator_config", {})
        env = {"SOME_VAR": "1", **self.validator.environment(vconfig)}
        return [CommandSpec(
            name="my-train-evaluate",
            executable="bash",
            args=[str(workspace / "scripts" / "my_train.sh")],
            cwd=str(workspace),
            env=env,
        )]
```

注册（在 `PlatformService.__init__` 中，可复用同一个 validator 组合出多个 trainer id）：

```python
from auto_mixture_tool.plugins.trainers.my_trainer import MyTrainer
from auto_mixture_tool.plugins.validators.stem import StemValidator
...
my_trainer = MyTrainer(StemValidator())
my_trainer.id = "my-trainer-stem"
self.trainers.register(my_trainer)
```

### 6.4 新增验证器插件

`ValidatorAdapter` 接口只要求实现 `environment(config) -> dict[str, str]`。  
注意：**`config` 已经是 payload 中的 `validator_config` 字典本身**，直接在它上面取字段即可（不要再去 `request["validator_config"]`）；返回的字典会作为环境变量交给训练器。

验证方法可切换的关键就在这里：换一个验证器 = 换一组环境变量，训练器代码无需改动。

```python
from auto_mixture_tool.plugins.base import ValidatorAdapter

class MyValidator(ValidatorAdapter):
    id = "my-validator"
    display_name = "My custom eval"

    def environment(self, config):
        return {
            "EVAL_BENCHMARKS": str(config.get("benchmarks", "my-bench")),
            "VALIDATION_DATA_URI": str(config.get("data_uri", "")),
        }
```

注册（在 `PlatformService.__init__` 中）：

```python
from auto_mixture_tool.plugins.validators.my_validator import MyValidator
...
self.validators.register(MyValidator())
```

### 6.5 新增执行器插件

执行器负责把 `JobRecord` 提交到实际运行环境，`submit` 返回 `(status, external_id, message)`：

```python
from auto_mixture_tool.plugins.base import ExecutorAdapter

class MyExecutor(ExecutorAdapter):
    id = "my-executor"
    display_name = "My cluster executor"

    def submit(self, job):
        # job.stages 是 CommandSpec 列表，job.request 含完整配置
        external_id = dispatch_to_cluster(job)
        return "SUBMITTED", external_id, "submitted to my cluster"
```

注册（在 `PlatformService.__init__` 中）：

```python
from auto_mixture_tool.plugins.executors.my_executor import MyExecutor
...
self.executors.register(MyExecutor())
```

### 6.6 数据格式校验插件（可替换）

数据格式校验是一个**独立的、可替换**的插件家族（`FormatValidatorAdapter`），  
专门判断"数据集是否符合某套格式标准"。默认实现 `QuadMixFormatValidator`  
（id=`quadmix`）检查：

- 必需列是否存在：域列、`quality_cols` 各列、文本列、`char_count_col`（若配置）；
- **域标签是否缺失**：样本中有多少行的 `domain` 列为空 / null；
- **是否是指定的标签**：当 schema 声明了 `domain_names` 时，域值必须落在其中，  
  否则报"非预期域标签"；
- 质量列是否数值型、是否整体为空；
- 文本列是否非空。

它与底层的 `inspect_dataset`（结构性检查：列存在 / 类型 / 文本非空）解耦——  
因此"格式标准"本身可以替换而不动其它流程。

校验发生在两个位置：

1. `validate_dataset(...)` / `POST /api/v1/datasets/inspect`（请求体带 `format_validator_id`）：  
   作为独立结果 `format_check` 返回，并合并进 `valid`/`errors`/`warnings`。
2. `create_job` 的提交闸门（gate）：默认用 `format_validator_id`（缺省 `quadmix`）  
   运行格式校验，不通过则拒绝提交。

新增一个格式标准：

```python
from auto_mixture_tool.plugins.base import FormatValidatorAdapter

class MyFormatValidator(FormatValidatorAdapter):
    id = "my-format"
    display_name = "My dataset format"

    def validate(self, request):
        # request 含 dataset_uri / schema_uri / sample_size
        # 返回 {valid, errors, warnings, details}
        return {"valid": True, "errors": [], "warnings": [], "details": {}}
```

注册（在 `PlatformService.__init__` 中）：

```python
from auto_mixture_tool.plugins.format_validators.my_format import MyFormatValidator
...
self.format_validators.register(MyFormatValidator())
```

使用：YAML 里 `format_validator_id: my-format`，或 API 请求体加 `"format_validator_id": "my-format"`。

> 参考实现：`plugins/format_validators/quadmix.py`（`QuadMixFormatValidator`）。

### 6.7 实战：新增一个可切换的自定义验证器

以"STEM 验证自定义切换"为例，完整走一遍**修改插件 → 使用新插件**的流程。

**第 1 步 — 写插件** `src/auto_mixture_tool/plugins/validators/my_eval.py`：

```python
from auto_mixture_tool.plugins.base import ValidatorAdapter

class MyEvalValidator(ValidatorAdapter):
    id = "my-eval"
    display_name = "My custom eval (GSM8K + MMLU-STEM)"

    def environment(self, config):
        return {
            "EVAL_BENCHMARKS": str(config.get("benchmarks", "my-eval")),
            "STEM_TASKS": ",".join(config.get("tasks", ["gsm8k", "mmlu_stem"])),
            "VALIDATION_DATA_URI": str(config.get("data_uri", "")),
        }
```

**第 2 步 — 注册** 在 `src/quadmix_platform/service.py` 的 `PlatformService.__init__` 中：

```python
from auto_mixture_tool.plugins.validators.my_eval import MyEvalValidator
...
self.validators.register(MyEvalValidator())
```

**第 3 步 — 通过 YAML 使用**（`examples/configs/demo_pipeline.yaml` 改两行即可）：

```yaml
validator_id: my-eval          # 切换验证方法，无需改训练器代码
validator_config:
  tasks: [gsm8k, mmlu_stem]
  data_uri: /data/my_eval_tokenized.pt
```

**第 4 步 — 运行 / 提交**：

```bash
auto-mixture run examples/configs/demo_pipeline.yaml
# 或经 API
curl -X POST http://127.0.0.1:8080/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"dataset_uri":"./temp/preprocessed","schema_uri":"./configs/schema_essential_web.yaml",
       "algorithm_id":"quadmix","trainer_id":"nanochat-stem","validator_id":"my-eval",
       "executor_id":"hpc-cluster","executor_config":{"endpoint":"https://hpc-cluster.example.com/api/v1/jobs"},
       "validator_config":{"tasks":["gsm8k","mmlu_stem"]}}'
```

训练器（`NanoChatTrainer`）只读取验证器注入的环境变量，因此**换验证方法 = 换 validator，trainer 代码零改动**。

> 参考实现：算法 `plugins/algorithms/random.py`、`plugins/algorithms/manual.py`；  
> 训练器 `plugins/trainers/nanochat.py`；验证器 `plugins/validators/stem.py`、`plugins/validators/custom.py`；  
> 执行器 `quadmix_platform/components.py`（`HpcClusterExecutor`）；格式校验 `plugins/format_validators/quadmix.py`。

---

## 7. 集群集成

第 8 层有两个执行后端：

### 7.1 `local` —— 开发环境（默认）

`LocalExecutor` 依次用 `subprocess.run` 在本地执行每个 `CommandSpec` 阶段，首个失败即短路。无需集群，配合 `pip install -e .` 即可在本机跑通命令委派链路。

```yaml
executor_id: local
executor_config: {}
```

### 7.2 `hpc-cluster` —— 生产

`HpcClusterExecutor` 把 `CommandSpec` 序列化为 JSON，通过 HTTP POST 发送到集群的提交入口：

```yaml
executor_id: hpc-cluster
executor_config:
  endpoint: https://hpc-cluster.example.com/api/v1/jobs   # 必填：集群 API 提交入口
  token_env: AMT_CLUSTER_TOKEN                            # 可选：承载令牌的环境变量名
```

- `endpoint`：集群任务提交 API 的 URL（必填）。
- `token_env`：读取承载令牌的环境变量名（可选；缺省 `AMT_CLUSTER_TOKEN`）。
- 请求体为 `{"name": <job_id>, "stages": [<CommandSpec>...]}`；集群返回 `{"status": ..., "id": ...}`。

> 各接口契约、内置实现 id 表、新增插件与注册步骤的完整说明见 [`docs/USAGE.md`](USAGE.md)。

---

## 8. 结果分析

```python
from auto_mixture_tool.results.analysis import ResultAnalyzer

analyzer = ResultAnalyzer("./result")
print(analyzer.list_runs())
print(analyzer.compare_runs(["run_a", "run_b"]))
```

功能：

- 列出所有实验运行。
- 对比不同算法/验证配置的关键指标。
- 加载单个运行的 `pipeline_summary.json` 与 `optimal_parameters.json`。

---

## 8.1 核心接口契约（Phase 2 已落地）

重构风险最低的路径：**先定接口，再拔代码**。以下四个接口是所有插件必须实现的契约，定义在 `quadmix_platform/interfaces.py`，参照实现与桥接类在 `src/auto_mixture_tool/core/`。Phase 2 已把 `quadmix/`、`nanochat_mid_compare/` 的真实逻辑抽进具体子类（见 §8.1 进度表与 README 组件表）。

### 统一数据抽象（Layer 5）

```python
@dataclass
class Sample:
    id: str
    text: str
    domain: str
    metadata: dict = field(default_factory=dict)

class UnifiedDataset(ABC):
    schema: Any                       # 映射原始列 -> Sample
    def __iter__(self) -> Iterator[Sample]: ...
    def domains(self) -> list[str]: ...
    @property
    def size(self) -> int: ...
    def subset(self, indices: list[int]) -> "UnifiedDataset": ...
```

`CsvJsonlDataset` 已提供（stdlib，离线可跑），支持 **CSV / JSON / JSONL** 输入（`.json` 可为对象数组，或被 `samples`/`data`/`records`/`examples`/`items` 键包裹的数组；单独一个对象视为单行）；Parquet 在集群 `pyarrow` 环境下可用。`load_dataset(path, schema)` 为工厂入口。

**数据格式约定（输入 JSON / 输出 JSON）**：输入数据集可以是 JSON 数组文件（每行一个样本，含 `text` 与 `domain` 字段）；`MixingAlgorithm.export(output_dir, fmt="json")` 默认把选中的子集物化为 **JSON 数组**（`manual_mixed.json` / `random_mixed.json`），也可传 `fmt="jsonl"` 输出行分隔 JSON。端到端 `CanonicalPipeline(output_format="json")` 把该格式透传给算法导出。

### 配比算法接口（Layer 6）

```python
class MixingAlgorithm(ABC):
    id: str
    display_name: str
    def fit(self, dataset: UnifiedDataset) -> None: ...
    def select(self, dataset: UnifiedDataset) -> UnifiedDataset: ...
    def export(self, output_dir) -> str: ...   # 返回混合数据集 URI
```

`RandomMixingAlgorithm` 为参照实现（已实跑）。`CommandDrivenMixingAlgorithm` 把现有 `QuadMixAlgorithm(AlgorithmAdapter)` 桥接进来，证明 **QuadMix 可作为 `MixingAlgorithm` 被 Pipeline 无差别替换**。

### 训练接口（Layer 7a）

```python
class Trainer(ABC):
    id: str
    display_name: str
    def train(self, dataset: UnifiedDataset, output_dir) -> dict: ...  # 返回 checkpoint 信息
```

`NoOpTrainer` 为参照实现；`CommandDrivenTrainer` 桥接 `NanoChatTrainer`。

### 验证接口（Layer 7b，与 Trainer 分离）

```python
class Evaluator(ABC):
    id: str
    display_name: str
    def evaluate(self, checkpoint: dict, dataset=None) -> dict[str, float]: ...
```

`StubEvaluator` 为参照实现；`CommandDrivenEvaluator` 桥接 `StemValidator`。这样 **NanoChat 与 STEM 之间无硬绑定**：

```
QuadMix   -> NanoChat -> STEM
QuadMix   -> NanoChat -> HumanEval
LongTail  -> Qwen     -> STEM + MMLU + GSM8K
```

### 当前进度与差距（对照 9 层设计）

| 层        | 状态        | 说明                                                                                                                                                                                                                              |
| -------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 用户接口   | ✅         | **API**（FastAPI `serve`）+ **YAML 配置文件运行**（`auto-mixture run --config`）                                                                                                                                                          |
| 2 编排层    | ✅         | 命令式 `PipelineManager` / `PlatformService`；规范契约式 `CanonicalPipeline`（第 1/5/6/7a/7b/8/9 层端到端，已离线实跑）                                                                                                                               |
| 3 数据检测验证 | ✅（增强）     | 统计校验 + 可替换格式校验（列类型/标签/编码/重复文件）                                                                                                                                                                                                  |
| 4 配置管理   | ✅         | `PipelineConfig` 五类配置                                                                                                                                                                                                           |
| 5 统一数据抽象 | ✅         | `UnifiedDataset`/`Sample` 契约 + CSV/JSON/JSONL 加载已落地（离线可跑）；导出默认 JSON 数组、可选 JSONL；Parquet 完整接入待集群验证                                                                                                                               |
| 6 配比算法接口 | ✅ Phase 2 | `MixingAlgorithm` 已有 **4 个**实现：`random-core`（参照）、`manual-core`（进程内按比例选子集，离线实跑）、`quadmix-core`（**抽入真实** `src/quadmix` 的 `QuaDMixPipeline`，precomputed 模式 + 注入 `proxy_runner`）、`CommandDrivenMixingAlgorithm`（桥接命令式）              |
| 7 训练/验证  | ✅ Phase 2 | `Trainer` 已有 `none-core`（参照）、`nanochat-core`（**抽入真实** `nanochat_mid_compare` 训练，`dry_run` 可离线验命令）、`CommandDrivenTrainer`；`Evaluator` 已有 `stub-core`（参照）、`stem-core`（**抽入真实** STEM 评估，`dry_run` 可离线验命令）、`CommandDrivenEvaluator` |
| 8 集群执行   | ✅         | `local`（dev 子进程）+ `hpc-cluster`（HPC 集群 API） |
| 9 结果分析   | ✅         | `ResultAnalyzer`                                                                                                                                                                                                                |

**Phase 2 已落地（按用户 9 层规范）**：把 `quadmix/`、`nanochat_mid_compare/` 的**真实逻辑抽进** `MixingAlgorithm` / `Trainer` / `Evaluator` 的具体子类，命令式 `AlgorithmAdapter` 退化为“外部脚本执行策略”之一（桥接类 `CommandDriven*`）。所有真实子类均**惰性导入重型依赖**（numpy/pandas/pyarrow/lightgbm/torch），离线只验契约与命令构造，真跑需集群 `pip install -e .` + 对应运行器。`quadmix_platform` ↔ `auto_mixture_tool` 的循环依赖**已修复**（见 §8.2）。

---

## 8.2 循环依赖：已修复

`quadmix_platform/service.py` 在模块顶层 `import auto_mixture_tool.plugins.*`，而  
`auto_mixture_tool/__init__.py` 又 `import quadmix_platform`，形成循环；且两个包  
的 `__init__` 都在顶层急切导入需要 NumPy / Pandas 的 `service`，导致纯标准库的  
规范契约模块（`quadmix_platform.interfaces` / `.models` / `auto_mixture_tool.core.*`）  
在离线环境根本无法导入、也无法做端到端验证。

**已采用的修复（低风险）**：

- `quadmix_platform/__init__.py`：移除顶层 `from .service import PlatformService`，  
  改用惰性 `__getattr__` 暴露 `PlatformService`，包初始化不再拉起重型 service。
- `auto_mixture_tool/__init__.py`：`PlatformService` / `PipelineManager` /  
  `ResultAnalyzer` / `CanonicalPipeline` 全部改为惰性 `__getattr__` 暴露。
- `auto_mixture_tool/pipeline.py`：`from quadmix_platform.service import PlatformService`  
  从模块顶层移入 `PipelineManager.__init__`，仅在实际构造时导入。

修复后两个包可独立、离线导入，规范契约模块（Phase 1 核心）无需 NumPy / Pandas 即可  
`import` 与单测；`import quadmix_platform` 与 `import auto_mixture_tool` 均不再报  
`ImportError`（仅在实际使用需 NumPy 的插件时才缺依赖）。

---

## 9. 后续上传到 GitHub

当前所有修改都在本地。当需要推送到 `https://github.com/AutoDataMixture/Auto-Mixture-Tool` 时，请明确告知，将执行：

1. 初始化目标仓库或添加远程。
2. 整理提交信息。
3. 推送代码。

---

## 10. 相关文档

- `docs/ARCHITECTURE.md` — 原 QuadMix 内部架构
- `docs/PLATFORM_INTEGRATION_ZH.md` — 平台集成指南
- `openapi/quadmix-platform.yaml` — REST API 契约
- `configs/schema_essential_web.yaml` — 数据集 schema 示例
