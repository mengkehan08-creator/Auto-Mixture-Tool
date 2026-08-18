# Auto-Mixture-Tool 接口与使用文档

本文件是**开发环境**下跑通本仓的完整说明，覆盖：数据接口、算法接口、验证接口、训练接口、评估接口，以及如何调整注册以新增/替换插件。

平台有两套并行契约，理解这一点是使用本仓的关键：

| 路径 | 契约 | 入口 | 适合场景 |
|------|------|------|---------|
| **命令委派** | `AlgorithmAdapter` / `TrainerAdapter` / `ValidatorAdapter` / `ExecutorAdapter`（发出 `CommandSpec`） | `PipelineManager` → `PlatformService.create_job` → `ExecutorAdapter.submit` | 完整生产链路；dev 下用 `local` 执行器本地子进程跑 |
| **规范契约（Phase 1/2）** | `MixingAlgorithm` / `Trainer` / `Evaluator`（面向对象，进程内） | `CanonicalPipeline.run` | 纯标准库参照路径离线即可跑通；也是新插件的首选契约 |

两者通过桥接类（`CommandDriven*`）互通：任何 `AlgorithmAdapter` 都能被包成 `MixingAlgorithm`。

---

## 1. 开发环境准备

```bash
git clone <repo> Auto-Mixture-Tool
cd Auto-Mixture-Tool
pip install -e .          # 安装运行时依赖 + 两个 CLI：auto-mixture / quadmix-platform
```

依赖：`PyYAML`（配置/检测）、`numpy`/`pandas`/`pyarrow`（数据/算法）、`fastapi`/`uvicorn`（API）、`lightgbm`/`torch`（QuadMix/NanoChat 真实训练）。

**离线/轻量验证**（无需安装重型依赖）：`CanonicalPipeline` 的参照实现（`Random`+`NoOp`+`Stub`）只用标准库；把外部 PyYAML 加入 `PYTHONPATH` 即可跑：

```bash
export PYTHONPATH="src;C:/Users/<user>/.hf-cli/venv/Lib/site-packages"
python tests/test_canonical_pipeline.py
```

---

## 2. 运行入口（Layer 1）

只支持两种：**YAML 配置文件运行** 与 **HTTP API**。

### 2.1 YAML 配置文件运行（dev 主入口）

```bash
auto-mixture run examples/configs/demo_pipeline.yaml
```

读取 YAML → 校验数据集 → 算法/训练/验证插件生成 `CommandSpec` → 提交给 `executor_id` 指定的执行器 → 返回 `job_id`。dev 下 `executor_id: local`，本地子进程跑各阶段。

### 2.2 HTTP API

```bash
auto-mixture serve --host 0.0.0.0 --port 8080
```

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/v1/health` | 健康检查 |
| GET  | `/api/v1/components` | 组件目录（算法/训练器/验证器/执行器/格式校验器） |
| POST | `/api/v1/datasets/inspect` | 数据集校验（请求体带 `format_validator_id`） |
| POST | `/api/v1/jobs` | 提交任务 |
| GET  | `/api/v1/jobs/{job_id}` | 查询任务 |

---

## 3. 数据接口（Layer 5）

**核心抽象**：`Sample` + `UnifiedDataset`（`quadmix_platform/interfaces.py`）。任何原始格式（CSV/JSON/JSONL/Parquet）经 `load_dataset` 规整成 `UnifiedDataset`，下游算法只看到 `Sample`，不再感知原始列名。

```python
@dataclass
class Sample:
    id: str
    text: str
    domain: str
    metadata: dict[str, Any] = field(default_factory=dict)

class UnifiedDataset(ABC):
    schema: Any = None
    def __iter__(self) -> Iterator[Sample]: ...
    def domains(self) -> list[str]: ...
    @property
    def size(self) -> int: ...
    def subset(self, indices: list[int]) -> "UnifiedDataset": ...
```

### 3.1 读取数据集

`auto_mixture_tool.core.dataset.load_dataset(path, schema=None)` 按后缀分发：

| 后缀 | 实现 | 依赖 |
|------|------|------|
| `.csv` | `CsvJsonlDataset._read_csv` | 标准库 |
| `.json` | `CsvJsonlDataset._read_json_array` | 标准库 |
| `.jsonl` | `CsvJsonlDataset._read_jsonl` | 标准库 |
| `.parquet` | `_ParquetDataset` | `pyarrow`（集群） |

`.json` 支持三种形态：纯对象数组 `[{"text":..,"domain":..}, ...]`、被包裹的数组（键为 `samples`/`data`/`records`/`examples`/`items`）、单个对象（视为一行）。

```python
from auto_mixture_tool.core import load_dataset

ds = load_dataset("data/corpus.json")   # 或 .csv / .jsonl / .parquet
print(ds.size, ds.domains())            # 8, ["web","science","code"]
for s in ds:
    print(s.id, s.domain, s.text[:40])
```

`schema` 参数可指定列名映射（`text_col`/`domain_col`），缺省取 `text`/`domain`。

### 3.2 写出数据集（Layer 6 export / Layer 8 产物）

`auto_mixture_tool.core.dataset.write_samples(samples, uri, fmt="json")`：

- `fmt="json"`（默认）：写出 JSON 数组，符合"输出数据集为 JSON"的约定。
- `fmt="jsonl"`：行分隔 JSON。

```python
from auto_mixture_tool.core import write_samples
write_samples(selected, "out/mixed.json", fmt="json")
```

---

## 4. 算法接口（Layer 6）

### 4.1 规范契约 `MixingAlgorithm`（首选）

```python
class MixingAlgorithm(ABC):
    id: str
    display_name: str
    def fit(self, dataset: UnifiedDataset) -> None: ...           # 学参数
    def select(self, dataset: UnifiedDataset) -> UnifiedDataset: ...  # 选子集
    def export(self, output_dir: str | Path) -> str: ...          # 物化 + 返回 URI
```

内置实现（`src/auto_mixture_tool/core/`）：

| id | 类 | 说明 | 离线可跑 |
|----|----|------|---------|
| `random-core` | `RandomMixingAlgorithm` | 均匀随机采样参照 | ✅ 纯标准库 |
| `manual-core` | `ManualRatioMixingAlgorithm` | 按固定 `domain_ratios` 选子集 | ✅ 纯标准库 |
| `quadmix-core` | `QuadMixMixingAlgorithm` | 抽入真实 `src/quadmix` 的 `QuaDMixPipeline`（precomputed 模式） | 惰性导入，离线只验契约 |

`export(output_dir, fmt="json")` 默认输出 JSON 数组（`*_mixed.json`），可传 `fmt="jsonl"`。

### 4.2 命令式 `AlgorithmAdapter`（旧链路）

```python
class AlgorithmAdapter(ABC):
    id: str; display_name: str
    def build(self, request: dict, workspace: Path) -> list[CommandSpec]: ...
```

`build` 不直接选数据，而是发出 `CommandSpec(executable, args, env, cwd)`，由执行器在集群/dev 本地真正运行。内置：`quadmix` / `random` / `manual`（`src/auto_mixture_tool/plugins/algorithms/`）。

### 4.3 新增一个算法（规范契约）

1) 写子类：

```python
# src/auto_mixture_tool/core/longtail_mixing.py
from quadmix_platform.interfaces import MixingAlgorithm, UnifiedDataset

class LongTailMixingAlgorithm(MixingAlgorithm):
    id = "longtail-core"
    display_name = "Long-tail mixing"
    def __init__(self, alpha: float = 0.7):
        self.alpha = alpha; self._selected = None
    def fit(self, dataset): ...          # 学长尾权重
    def select(self, dataset): ...       # 返回 UnifiedDataset 子集
    def export(self, output_dir, fmt="json"): ...
        return write_samples(list(self._selected), str(Path(output_dir)/"longtail_mixed.json"), fmt=fmt)
```

2) 注册（见 §8.1）。

---

## 5. 验证接口（Layer 3/4）

数据集必须先过两道闸门才进入下游：

1. **结构性/统计校验**：`quadmix_platform.dataset_inspector.inspect_dataset(dataset_uri, schema_uri, sample_size)` —— 列存在、类型、空文本、域分布、长度/重复率/质量分。
2. **可替换的格式合规校验**：`FormatValidatorAdapter` —— 判断"是否符合某套格式标准"。

### 5.1 契约

```python
class FormatValidatorAdapter(ABC):
    id: str; display_name: str
    def validate(self, request: dict) -> dict:  # request 含 dataset_uri/schema_uri/sample_size
        # 返回 {"valid": bool, "errors": [...], "warnings": [...], "details": {...}}
```

入口：`auto_mixture_tool.data.validator.validate_dataset(dataset_path, schema_path, sample_size=1000, format_validator_id="quadmix")`，返回合并了 `base`/`statistics`/`format_check` 的结果。

### 5.2 内置实现

| id | 类 | 检查项 |
|----|----|------|
| `quadmix` | `QuadMixFormatValidator` | 必填列存在、域标签非空且属于声明集合、质量列数值且非全空、文本非空、列类型/重复文件/编码 |

### 5.3 新增一个格式校验器

```python
# src/auto_mixture_tool/plugins/format_validators/my_format.py
from auto_mixture_tool.plugins.base import FormatValidatorAdapter

class MyFormatValidator(FormatValidatorAdapter):
    id = "my-format"
    display_name = "My dataset format"
    def validate(self, request):
        # ... 自定义检查 ...
        return {"valid": True, "errors": [], "warnings": [], "details": {}}
```

注册见 §8.1。使用：YAML 里 `format_validator_id: my-format`，或 API 请求体加 `"format_validator_id": "my-format"`。

---

## 6. 训练接口（Layer 7a）

### 6.1 规范契约 `Trainer`

```python
class Trainer(ABC):
    id: str; display_name: str
    def train(self, dataset: UnifiedDataset, output_dir: str | Path) -> dict[str, Any]: ...
    # 返回 checkpoint 信息，如 {"checkpoint_uri": ..., "log_uri": ...}
```

内置（`src/auto_mixture_tool/core/`）：

| id | 类 | 说明 | 离线 |
|----|----|------|------|
| `none-core` | `NoOpTrainer` | 跳过训练（参照） | ✅ |
| `nanochat-core` | `NanoChatTrainer` | 抽入 `nanochat_mid_compare` 训练脚本；`dry_run=True` 只生成命令计划不真跑 | `dry_run` 可验 |

### 6.2 命令式 `TrainerAdapter`

```python
class TrainerAdapter(ABC):
    def build(self, request: dict, workspace: Path) -> list[CommandSpec]: ...
```

内置：`none` / `nanochat` / `nanochat-stem` / `nanochat-custom`（`src/quadmix_platform/components.py` 与 `plugins/trainers/`）。

### 6.3 新增训练器

```python
# src/auto_mixture_tool/core/qwen_trainer.py
from quadmix_platform.interfaces import Trainer, UnifiedDataset

class QwenTrainer(Trainer):
    id = "qwen-core"; display_name = "Qwen trainer"
    def __init__(self, dry_run: bool = True): self.dry_run = dry_run
    def train(self, dataset, output_dir):
        if self.dry_run:
            return {"status": "planned", "train_plan": ...}
        # ... 真实训练 ...
        return {"checkpoint_uri": str(Path(output_dir)/"ckpt")}
```

注册见 §8.1。

---

## 7. 评估接口（Layer 7b）

与 `Trainer` **分离** —— 换评估方法不影响训练器。

```python
class Evaluator(ABC):
    id: str; display_name: str
    def evaluate(self, checkpoint: dict, dataset: UnifiedDataset | None = None) -> dict[str, float]: ...
    # 返回 {metric_name: score}
```

内置（`src/auto_mixture_tool/core/`）：

| id | 类 | 说明 | 离线 |
|----|----|------|------|
| `stub-core` | `StubEvaluator` | 返回空指标（参照） | ✅ |
| `stem-core` | `STEMEvaluator` | 抽入 `scripts/platform/run_nanochat_validation.py` 的 STEM 评估，解析 JSON 指标；`dry_run=True` 只生成命令 | `dry_run` 可验 |

新增评估器同理：子类化 `Evaluator`，注册到 `build_canonical_registry()` 的 `evaluators`。

---

## 8. 注册调整

本仓有**两套注册表**，分别对应两套契约。**只在对应注册表里注册一次**，不要在别处维护副本。

### 8.1 命令式适配器注册（`PlatformService`）

入口：`src/quadmix_platform/service.py` 的 `PlatformService.__init__`。运行时真正生效，CLI / API / `PipelineManager` 全走这里。

```python
# src/quadmix_platform/service.py
from auto_mixture_tool.plugins.algorithms.longtail import LongTailAlgorithm   # 命令式
from auto_mixture_tool.plugins.format_validators.my_format import MyFormatValidator
from .components import LocalExecutor, HpcClusterExecutor

class PlatformService:
    def __init__(self, workspace=None):
        ...
        self.algorithms.register(LongTailAlgorithm())              # 新算法
        self.format_validators.register(MyFormatValidator())       # 新格式校验器
        # 执行器：local（dev）+ hpc-cluster（prod），按需保留
        self.executors.register(LocalExecutor())
        self.executors.register(HpcClusterExecutor())
```

`ComponentRegistry` 的 API：

```python
reg = ComponentRegistry()
reg.register(component)              # component 需有 id / display_name
reg.get("component-id")              # 按取实例
reg.catalog()                        # -> [{"id":..,"display_name":..}, ...]
```

### 8.2 规范契约注册（`build_canonical_registry`）

入口：`src/auto_mixture_tool/core/registry.py`。惰性建表，重型实现按需导入。`CanonicalPipeline.from_config(algorithm_id=..., trainer_id=..., evaluator_id=...)` 按 id 从这里取。

```python
# src/auto_mixture_tool/core/registry.py
def build_canonical_registry() -> dict[str, ComponentRegistry]:
    from auto_mixture_tool.core.longtail_mixing import LongTailMixingAlgorithm
    from auto_mixture_tool.core.qwen_trainer import QwenTrainer
    ...
    algorithms.register(LongTailMixingAlgorithm())
    trainers.register(QwenTrainer(dry_run=True))
    ...
    return {"algorithms": algorithms, "trainers": trainers, "evaluators": evaluators}

def get_algorithm(component_id: str) -> MixingAlgorithm: ...
def get_trainer(component_id: str) -> Trainer: ...
def get_evaluator(component_id: str) -> Evaluator: ...
```

### 8.3 新增插件的完整步骤（清单）

1. 实现子类（规范契约放 `src/auto_mixture_tool/core/`，命令式放 `src/auto_mixture_tool/plugins/<family>/`）。
2. 在对应注册表注册一次：
   - 规范契约 → `core/registry.py` 的 `build_canonical_registry()`；
   - 命令式 → `quadmix_platform/service.py` 的 `PlatformService.__init__`。
3. 若需要配置参数，在 `PipelineConfig` / `JobRequest` 的 `*_config` 字段里传（无需改契约）。
4. YAML/API 用 `algorithm_id` / `trainer_id` / `validator_id` / `executor_id` / `format_validator_id` 引用。
5. 离线冒烟测试：参照 `tests/test_manual_mixing.py` 写一个纯标准库的端到端测试。

---

## 9. 执行后端（Layer 8）

| id | 类 | 用途 | 行为 |
|----|----|------|------|
| `local` | `LocalExecutor`（`quadmix_platform/components.py`） | **dev** | 依次 `subprocess.run` 各 `CommandSpec`，首个失败即短路，返回 `SUCCEEDED`/`FAILED` |
| `hpc-cluster` | `HpcClusterExecutor` | **生产** | 把 stages 序列化为 JSON，POST 到 `executor_config.endpoint`，承载令牌从 `token_env`（缺省 `AMT_CLUSTER_TOKEN`）读 |

dev 默认 `executor_id: local`。切生产：YAML 改 `executor_id: hpc-cluster` 并在 `executor_config` 填 `endpoint`。

---

## 10. 端到端示例

### 10.1 规范契约路径（离线即可跑，纯标准库）

```python
from auto_mixture_tool.core import (
    CanonicalPipeline, ManualRatioMixingAlgorithm, NoOpTrainer, StubEvaluator,
)

pipe = CanonicalPipeline(
    algorithm=ManualRatioMixingAlgorithm(domain_ratios={"web": 0.5, "science": 0.25, "code": 0.25}),
    trainer=NoOpTrainer(),
    evaluator=StubEvaluator(),
    output_format="json",   # 输出 JSON 数组
)
result = pipe.run(
    dataset_uri="data/corpus.json",
    output_dir="out/demo",
    job_id="dev-smoke",
)
print(result["status"], result["stages"]["mixing"]["mixed_uri"])
# COMPLETED out/demo/mixed/manual_mixed.json
```

### 10.2 命令委派路径（dev，需 `pip install -e .`）

YAML（`examples/configs/demo_pipeline.yaml`）：

```yaml
dataset_uri: ./temp/preprocessed
schema_uri: ./configs/schema_essential_web.yaml
algorithm_id: quadmix
trainer_id: nanochat-stem
validator_id: stem
executor_id: local          # dev；生产改 hpc-cluster
format_validator_id: quadmix
algorithm_config: {num_experiments: 8, num_search: 1000}
trainer_config: {npu_devices: 8}
validator_config: {tasks: [gsm8k, mmlu_stem, arc_easy]}
executor_config: {}         # local 留空；hpc-cluster 填 endpoint
```

```bash
auto-mixture run examples/configs/demo_pipeline.yaml
```

### 10.3 经 API 提交（dev）

```bash
auto-mixture serve --port 8080 &
curl -X POST http://127.0.0.1:8080/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d @examples/platform/sample_job.json
```

`sample_job.json` 默认 `executor_id: local`，API 服务在本地子进程跑各阶段。

---

## 11. 测试

| 文件 | 覆盖 | 离线 |
|------|------|------|
| `tests/test_canonical_pipeline.py` | 规范契约端到端（参照 + 命令桥接） | ✅ |
| `tests/test_json_dataset.py` | JSON 输入/输出、JSONL 选项 | ✅ |
| `tests/test_manual_mixing.py` | `manual-core` 真实选子集 + 注册表 | ✅ |
| `tests/test_quadmix_algorithm.py` | `quadmix-core` 惰性导入边界 | ✅ |
| `tests/test_nanochat_trainer.py` | `nanochat-core` dry_run 命令构造 | ✅ |
| `tests/test_stem_evaluator.py` | `stem-core` dry_run 命令构造 | ✅ |
| `tests/test_p2_e2e.py` | Manual+NanoChat(dry_run)+STEM(dry_run) 端到端 | ✅ |
| `tests/test_platform.py` | 命令委派链路（需 numpy/quadmix） | 集群 |

```bash
# 离线跑全部纯标准库测试
PYTHONPATH="src;<pyyaml-site-packages>" python tests/test_canonical_pipeline.py
# ...
```

---

## 12. 常见问题

- **本地跑命令委派链路报缺 numpy**：`run_random_mixing.py` 等脚本依赖 numpy/pandas/quadmix，需先 `pip install -e .`。离线只验规范契约路径。
- **想换算法但不想碰代码**：YAML 改 `algorithm_id` 即可；只有新增算法才需要写子类 + 注册。
- **想让新算法在两种路径都可用**：同时实现 `MixingAlgorithm`（规范）与 `AlgorithmAdapter`（命令式），分别注册到 `core/registry.py` 与 `service.py`。或用 `CommandDrivenMixingAlgorithm` 把命令式适配器包成规范契约。

---

## 13. 8 NPU 开发环境 与 切换到 HPC 集群 API

### 13.1 dev：8 NPU 本地运行

`LocalExecutor`（`executor_id: local`）依次在本地子进程跑各阶段。NPU 配置经两条路径流入脚本：

| 配置项 | 流向 | 作用 |
|--------|------|------|
| `algorithm_config.device_type` / `npu_devices` | QuadMix 的 `--device-type` / `--npu-devices` | proxy 实验训练设备 |
| `trainer_config.npu_devices` | `NUM_NPU` 环境变量 → `run_experiment.sh` | `ASCEND_VISIBLE_DEVICES=0..N-1`、`RANK_SIZE=N` |

`examples/configs/demo_pipeline.yaml` 已按 8 NPU 配好：

```yaml
executor_id: local
algorithm_config: {device_type: npu, npu_devices: 8, ...}
trainer_config:  {npu_devices: 8, ...}
```

运行：

```bash
pip install -e .                          # 含 numpy/pandas/torch/torch_npu 等
auto-mixture run examples/configs/demo_pipeline.yaml
```

`run_experiment.sh` 会自动设置 Ascend 相关环境（`ASCEND_HCCL_PATH`、`ASCEND_VISIBLE_DEVICES`、`RANK_SIZE` 等）。若 `ASCEND_DEVICE_ID`/`LOCAL_RANK` 未设置，脚本默认用 device 0；多卡由 `NUM_NPU=8` 驱动。

> 无 NPU 的纯逻辑验证：把 `device_type` 改回 `cpu`、`npu_devices: 1`，或直接走 §10.1 的 `CanonicalPipeline` 参照路径（纯标准库）。

### 13.2 生产：经 API 提交到 HPC 集群

切到 `executor_id: hpc-cluster` 并配 `endpoint`。完整示例见 `examples/configs/demo_pipeline_hpc.yaml`：

```yaml
executor_id: hpc-cluster
executor_config:
  endpoint: https://hpc-cluster.example.com/api/v1/jobs
  token_env: AMT_CLUSTER_TOKEN        # 可选；承载令牌从该环境变量读取
```

`HpcClusterExecutor.submit` 把 `{name, stages:[CommandSpec...]}` POST 到 `endpoint`，集群侧再翻译为 Slurm / K8s / Volcano / 厂商任务。返回 `{status, id}`。

两种提交方式：

```bash
# 1) YAML 配置文件运行（从本机直接提交到集群 API）
auto-mixture run examples/configs/demo_pipeline_hpc.yaml

# 2) 先起 API 服务，再由上游系统/前端 POST 任务
auto-mixture serve --host 0.0.0.0 --port 8080 &
curl -X POST http://127.0.0.1:8080/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d @examples/platform/sample_job.json   # 把 executor_id 改 hpc-cluster + executor_config.endpoint
```

### 13.3 dev ↔ 生产 对照

| 项 | dev（8 NPU 本机） | 生产（HPC 集群） |
|----|-------------------|------------------|
| `executor_id` | `local` | `hpc-cluster` |
| `executor_config` | `{}` | `{endpoint, token_env?}` |
| 执行方式 | 本地 `subprocess.run` 各阶段 | POST 到集群 API，集群调度 |
| NPU 配置 | `device_type: npu`、`npu_devices: 8` | 同左（集群侧按其调度分配） |
| 适用 | 调试、小规模验证 | 大规模正式实验 |
