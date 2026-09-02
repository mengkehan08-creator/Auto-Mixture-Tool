# Hadoop 数据处理与 ModelArts 多节点运行

本文描述当前可执行边界和人工操作。Hadoop 只负责数据处理；ModelArts
负责 QuaDMix 配比、NanoChat 训练、STEM 评测和结果输出。

## 1. 工作流

```text
STEM JSON
  -> Hadoop 外部过滤、标签提取、Parquet 转换与校验
  -> OBS 标准 Parquet
  -> ModelArts 多节点 QuaDMix
  -> sampled_dataset（Parquet）
  -> training_data_adapter_id=none（NanoChat/STEM）
  -> ModelArts 多节点 NanoChat
  -> STEM 评测
  -> 模型、指标、得分和报告写入 OBS
```

Hadoop 的提交 API 尚未确定，所以当前版本不伪造 Hadoop 调用。当前将
`prepared_parquet_57ffce0ca0a2/` 视为 Hadoop 已完成且通过校验的产物。

需要其他训练格式时，可以选择 `external-hadoop-artifact`。它表示先结束
QuaDMix 作业，人工或外部系统执行 Hadoop 转换，再把转换结果作为新的
ModelArts 训练输入。NanoChat/STEM 使用 `none`，不执行 Parquet 到 JSON。

## 2. OBS 目录

当前标准 Parquet：

```text
obs://bucket-pangu-green-guangzhou/s00944147/l00916525/chengchao/prepared_parquet_57ffce0ca0a2/
```

建议运行产物：

```text
obs://bucket-pangu-green-guangzhou/s00944147/l00916525/chengchao/runs/<job-name>/
```

多节点协调目录由提交脚本自动生成：

```text
runs/<job-name>/quadmix/
├── proxy_results/node-0.json
├── proxy_results/node-0._SUCCESS
├── proxy_results/node-1.json
├── proxy_results/node-1._SUCCESS
└── final/
    ├── sampled_dataset/
    ├── optimal_parameters.json
    ├── pipeline_summary.json
    └── _SUCCESS
```

OBS 不是 POSIX 共享盘。节点只能在 `_SUCCESS` 出现后下载完整产物。

## 3. 准备 GPT-NeoX Tokenizer

在能连接 Hugging Face 的机器下载一次：

```bash
python3 -c "from transformers import AutoTokenizer; t=AutoTokenizer.from_pretrained('EleutherAI/gpt-neox-20b'); t.save_pretrained('./gpt-neox-20b-tokenizer')"
```

上传整个目录到 OBS，例如：

```text
obs://bucket-pangu-green-guangzhou/s00944147/l00916525/gpt-neox-tokenizer/
```

目录中至少需要 `tokenizer.json`、`tokenizer_config.json` 和相关配置文件。
ModelArts 运行时强制离线，不会再访问 Hugging Face。

## 4. 检查镜像

镜像使用 Python 3.11，并且必须提供一种 OBS 客户端：

```bash
python3 --version
python3 -c "import moxing; print('moxing available')"
which obsutil
```

程序按 `moxing -> obsutil` 自动选择。两者都没有时任务会立即给出明确错误。

镜像还必须包含与 Ascend/CANN 匹配的 `torch`、`torch-npu`、`transformers`、
`pyarrow`、`lightgbm`、`scikit-learn` 和 NanoChat 依赖。

## 5. 配置提交脚本

保留仓库根目录 `modelarts_training_job.py` 样例的主体函数结构，只修改参数。
两节点测试的关键位置：

```python
url = "training-jobs API地址"
headers = {
    "region": "区域",
    "Authorization": "替换为Authorization",
}

job_data["metadata"]["workspace_id"] = "工作空间ID"
job_data["algorithm"]["engine"]["image_url"] = "镜像地址"
job_data["algorithm"]["engine"]["image_repo_id"] = "镜像仓库ID"
job_data["spec"]["resource"]["node_count"] = 2
job_data["spec"]["resource"]["pool_id"] = "资源池ID"
```

OBS地址修改 `job_data["algorithm"]["inputs"]` 和 `outputs` 中对应项。`main()`
保留样例原有流程，其中的输入覆盖值也必须同步修改；真实Authorization不要提交到Git。
YAML只配置容器内流水线，不能代替提交API所需的Authorization和资源参数。

## 6. 流水线配置

使用 `examples/configs/modelarts_pipeline.yaml`。关键字段：

```yaml
dataset_id: quadmix
dataset_config: {}
training_data_adapter_id: none

algorithm_config:
  num_experiments: 16
  tiny_steps: 15
  num_search: 1000
  seed: 42
  npu_devices: 8
  algorithm_nodes: auto
  tokenizer_path: /home/ma-user/modelarts/inputs/quadmix_tokenizer_dir_4
  proxy_validation_path: /home/ma-user/modelarts/inputs/proxy_validation_dir_5/stem_v2_tokenized.pt

trainer_config:
  npu_devices: 8

comparison_config:
  methods: [quadmix, random, manual]
  manual_ratios:
    数学: 0.60
    物理: 0.15
    化学: 0.125
    生物学: 0.125
```

`algorithm_nodes: auto` 从 ModelArts 的 `MA_NUM_HOSTS` 获取节点数。固定 `seed`
确保每个节点产生完全相同的16组参数，然后按全局实验编号分片。

提交脚本中 `proxy_validation_dir` 输入指向的OBS目录必须包含
`stem_v2_tokenized.pt`。该二进制验证集不在 Git 仓库中，提交脚本会把它挂载到
`proxy_validation_dir_5`，因此不能继续引用仓库内不存在的 `data/` 文件。

两节点分配为：

```text
node-0: 0,2,4,6,8,10,12,14
node-1: 1,3,5,7,9,11,13,15
```

每个节点内部最多使用8张NPU。worker-0 收齐16条结果后执行LightGBM、最优
搜索和最终采样。所有节点拿到最终采样数据后，以2×8=16个进程启动NanoChat。

NanoChat 的 ModelArts 输入目录只用于读取基础模型和 tokenizer，流水线不会在
`/home/ma-user/modelarts/inputs/nanochat_model_dir_1` 中创建或替换
`mid_checkpoints`。每个节点使用下面的临时可写布局：

```text
/tmp/auto-mixture-<job_id>/nanochat_model/
├── base_checkpoints/   # 链接到输入基础模型
├── tokenizer           # 链接到输入 tokenizer
└── mid_checkpoints     # 链接到 ModelArts 输出目录
```

真实的训练 checkpoint 仍写入
`/home/ma-user/modelarts/outputs/output_dir_0/nanochat_checkpoints`。因此，即使输入
模型目录已经存在普通 `mid_checkpoints/` 目录，也不会产生命名冲突。

`tiny_steps: 15` 表示16个代理实验每个都训练15步，不是 NanoChat
最终训练步数。这是多节点联调的临时设置；流程稳定后再根据时间和搜索质量
提高，例如恢复到5000步。

`algorithm_id` 仍然只选择 `quadmix`。`comparison_config.methods` 选择需要训练和
评测的对比方法，可以去掉 `random` 或 `manual`。选择 `manual` 时必须提供
`manual_ratios`，数值按权重归一化。各方法严格串行训练、再串行评测，避免三组
实验同时抢占NPU。

对比产物位于 `trainer_config.result_dir`：

```text
nanochat_results/
├── data/
│   ├── quadmix_data/          # QuaDMix采样子集（Parquet）
│   ├── random_data/           # 随机采样子集（Parquet）
│   ├── manual_ratio_data/     # 人工比例子集（Parquet）
│   └── dataset_stats.json     # 实际领域数量与比例
├── mid_train_*.log
├── eval_*.log
└── experiment_report.md       # 配比、训练指标和评测对比
```

## 7. 提交任务

先检查脚本语法：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
python3 -m py_compile modelarts_training_job.py
```

确认 `node_count` 为2、输入路径和镜像正确后提交：

```bash
python3 modelarts_training_job.py
```

脚本通过 ModelArts training-jobs API 创建任务。远端不再执行旧版
`pip install -e .`，而是设置 `PYTHONPATH=<repo>/src` 后直接运行模块入口。

## 8. 日志验收

QuaDMix 应出现：

```text
[Distributed] node-0/2: experiments=[0, 2, ...]
[Distributed] node-1/2: experiments=[1, 3, ...]
[Distributed] gathered 16 proxy results
```

训练应出现：

```text
--nnodes=2
--nproc_per_node=8
--node_rank=0|1
```

成功产物至少包含：

```text
sampled_dataset/
optimal_parameters.json
pipeline_summary.json
nanochat_checkpoints/
nanochat_results/
```

CLI 在任何阶段失败时返回非零退出码，ModelArts 不应再把内部 `FAILED`
误显示成成功。

## 9. 扩展节点数

当前支持每节点固定8张NPU、节点数灵活变化。简要修改：

```python
job_data["spec"]["resource"]["node_count"] = 目标节点数
```

同时按 `节点数 × 8` 检查或调整 `algorithm_config.num_experiments`，并保持
`algorithm_nodes: auto`。完整的1/2/4/8节点配置表、自动计算字段、日志验收和
扩缩容故障处理见 [SCALING_MODELARTS_NODES.md](SCALING_MODELARTS_NODES.md)。

## 10. 可选 Hadoop 目标格式

NanoChat/STEM保持：

```yaml
training_data_adapter_id: none
```

外部Hadoop已经把配比结果转换为JSON/JSONL后，新的训练作业可配置：

```yaml
training_data_adapter_id: external-hadoop-artifact
training_data_adapter_config:
  target_format: jsonl
  prepared_uri: /home/ma-user/modelarts/inputs/training_json_dir
```

获得真实Hadoop提交和状态API后，再为该接口增加自动提交、轮询、转换报告和
输出校验；不会影响算法、训练器或评测器注册方式。
