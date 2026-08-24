# 模块切换与扩展指南

本文说明如何通过 YAML 或 API 切换数据集契约、配比算法、训练框架和评测集，以及如何新增对应插件。

## 1. 当前支持范围

| 模块 | 配置字段 | 当前 ID | 实现位置 |
|---|---|---|---|
| 数据集契约与校验 | `dataset_id` | `quadmix` | `plugins/format_validators/quadmix.py` |
| 配比算法 | `algorithm_id` | `quadmix` | `plugins/algorithms/quadmix.py` |
| 训练框架 | `trainer_id` | `nanochat` | `plugins/trainers/nanochat.py` |
| 评测集/评测方法 | `evaluator_id` | `stem` | `plugins/validators/stem.py` |
| 执行后端 | `executor_id` | `local`、`hpc-cluster` | `quadmix_platform/components.py` |

“当前只支持”表示运行时目录只暴露上述 ID。注册表已经按模块拆分，新增实现后无需修改编排流程。

## 2. 标准配置

```yaml
dataset_uri: /home/ma-user/work/STEM_sample_100B_only_数理化生_json
schema_uri: /home/ma-user/work/Auto-Mixture-Tool/configs/schema_stem_sample_json.yaml
dataset_id: quadmix
output_uri: ./result/run_01

algorithm_id: quadmix
trainer_id: nanochat
evaluator_id: stem
executor_id: local

algorithm_config:
  num_experiments: 8
  num_search: 1000
  device_type: npu
  npu_devices: 8
  proxy_validation_set: cap_v1

trainer_config:
  npu_devices: 8
  nanochat_repo: /home/ma-user/nanochat-npu
  model_dir: /home/ma-user/nanochat_model_dir
  base_model_tag: d24

evaluator_config:
  benchmarks: stem
  tasks: [gsm8k, mmlu_stem, arc_easy]

executor_config:
  device_type: npu
  device_count: 8
```

旧字段 `format_validator_id`、`validator_id`、`validator_config` 暂时兼容读取；新配置只应使用 `dataset_id`、`evaluator_id`、`evaluator_config`。

## 3. 切换数据集

修改：

```yaml
dataset_uri: /home/ma-user/work/STEM_sample_100B_only_数理化生_json
schema_uri: /home/ma-user/work/Auto-Mixture-Tool/configs/schema_stem_sample_json.yaml
dataset_id: quadmix
```

当前 `quadmix` 数据集插件执行两件事：

1. 检查全部分片的必需字段、类型、域标签、质量分、空文本、编码和重复文件。
2. 将原始 JSON、JSONL 或 Parquet 目录直接交给 QuadMix，不执行格式转换。

JSON 支持对象数组、单对象，以及 `samples`、`data`、`records`、`examples`、`items` 包裹数组。

切换前建议先调用：

```bash
curl -X POST http://127.0.0.1:8080/api/v1/datasets/inspect \
  -H "Content-Type: application/json" \
  -d '{"dataset_uri":"/home/ma-user/work/STEM_sample_100B_only_数理化生_json","schema_uri":"/home/ma-user/work/Auto-Mixture-Tool/configs/schema_stem_sample_json.yaml","dataset_id":"quadmix"}'
```

只有 `valid=true` 才允许提交任务。

### 新增另一种数据集契约

1. 实现 `FormatValidatorAdapter.validate(request)`；当前约定不在平台内转换数据格式。
2. 在 `PlatformService.__init__` 中注册一次：

```python
self.datasets.register(MyDatasetAdapter())
```

3. YAML 改为 `dataset_id: my-dataset`。
4. 增加合法数据、缺列、错误标签、多分片和格式转换测试。

后续算法和训练器直接接收配置中的原始数据 URI。若新增数据格式，应扩展原生读取适配器，而不是增加全量转换阶段。

## 4. 切换配比算法

当前配置：

```yaml
algorithm_id: quadmix
algorithm_config:
  num_experiments: 8
  num_search: 1000
```

新增算法时：

1. 实现 `AlgorithmAdapter.build(request, workspace) -> list[CommandSpec]`。
2. 把文件放到 `plugins/algorithms/`。
3. 在 `PlatformService.__init__` 注册一次：

```python
self.algorithms.register(MyAlgorithm())
```

4. YAML 使用 `algorithm_id: my-algorithm`。

算法必须从 `request["dataset_uri"]` 读取已标准化的数据，并把训练数据写到 `output_uri` 下。不要在算法插件中重新实现数据校验。

## 5. 切换训练框架

当前配置：

```yaml
trainer_id: nanochat
trainer_config:
  npu_devices: 8
```

新增训练框架时：

1. 实现 `TrainerAdapter.build(request, workspace)`。
2. 从 `request["_evaluator_env"]` 接收评测插件生成的环境变量；不要把某个评测器写死在训练器构造函数中。
3. 在 `PlatformService.__init__` 注册：

```python
self.trainers.register(MyTrainer())
```

4. YAML 使用 `trainer_id: my-trainer`。

同一个训练器 ID 可以与不同评测器组合，不需要创建 `my-trainer-stem`、`my-trainer-custom` 等重复变体。

## 6. 切换 STEM 评测任务或评测集

只调整任务时无需新增插件：

```yaml
evaluator_id: stem
evaluator_config:
  benchmarks: stem
  tasks: [mmlu_stem, arc_challenge]
  validation_data_uri: /data/stem_validation.pt
```

`StemValidator` 会生成 `EVAL_BENCHMARKS`、`STEM_TASKS` 和 `STEM_VALIDATION_DATA`，由 NanoChat 训练阶段消费。

新增非 STEM 评测器时：

1. 实现 `ValidatorAdapter.environment(config) -> dict[str, str]`。
2. 在 `PlatformService.__init__` 注册到 `self.evaluators`。
3. YAML 改 `evaluator_id`，训练器无需复制或修改。

## 7. 查询可切换模块

```bash
curl http://127.0.0.1:8080/api/v1/components
```

返回 `datasets`、`algorithms`、`trainers`、`evaluators`、`executors` 五个目录。未知 ID 会在任务执行前被拒绝。

## 8. 修改后的验证清单

每次增加或切换组件至少执行：

```bash
python -m unittest discover -s tests -v
python tests/test_canonical_pipeline.py
python tests/test_json_dataset.py
python tests/test_quadmix_algorithm.py
python tests/test_nanochat_trainer.py
python tests/test_stem_evaluator.py
python tests/test_p2_e2e.py
```

真实 QuadMix、NanoChat 和 STEM 仍需在安装 PyArrow、Torch、torch-npu 且具备数据与模型的 NPU 环境验证。

本地八卡运行和 HPC API 提交的完整配置、环境变量、资源载荷及状态查询见 `docs/RUN_MODES.md`。
