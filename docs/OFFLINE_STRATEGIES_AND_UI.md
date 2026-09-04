# 离线训练、采样策略与配置界面说明

## 1. 正式工作流

正式 ModelArts 流程为：Hadoop 已处理 Parquet → 离线资源预检 → QuaDMix 配比 →
QuaDMix/随机/一个或多个人工方案分别生成采样集 → 分别进行 NanoChat 训练 →
离线 STEM 评测 → 输出模型、日志、比例和对比报告。

生产入口不会下载数据、模型或 Python 包。LightGBM 使用 OBS 挂载的离线 wheel；
Tokenizer、代理验证集、基础模型、NanoChat 仓库和评测包也必须作为 ModelArts 输入挂载。

## 2. 启动前必须存在的资源

| 输入 | 容器路径 | 最低要求 |
|---|---|---|
| 标准数据 | `data_dir_0` | 至少一个 `.parquet` |
| NanoChat 模型 | `nanochat_model_dir_1` | `tokenizer/tokenizer.pkl`、`base_checkpoints/<tag>/` |
| NanoChat 代码 | `nanochat_npu_dir_3` | `scripts/base_train.py`、`scripts/base_eval.py` |
| QuaDMix tokenizer | `quadmix_tokenizer_dir_4` | tokenizer 元数据 |
| 代理验证集 | `proxy_validation_dir_5` | `stem_v2_tokenized.pt` |
| 评测资源 | `eval_bundle_dir_6` | CORE 资源及 `eval_stem/` 或 `eval_stem.zip` |
| Python wheels | `python_wheels_dir_7` | AArch64 Python 3.11 LightGBM wheel |

`scripts/offline_resource_check.py` 在 QuaDMix 开始前一次性列出全部缺失项。通过后，
入口启用 Hugging Face、Transformers 和 Datasets 离线模式。仓库中
`scripts/validation_set/`、`scripts/preprocess/download_essential_web.py` 等属于人工
制作资源的工具，可能访问外网，但不会被生产 YAML 调用。

## 3. QuaDMix 一键配置

```yaml
algorithm_config:
  num_experiments: 16       # 代理实验数
  tiny_steps: 15            # 每个代理实验步数
  num_search: 1000          # 搜索点数
  top_k: 10
  search_mode: r2_weighted
  seed: 42
  block_size: 2048
  micro_batch_size: 2
  global_batch_size: 8
  rank_ref_size: 10000
  checkpoint_interval: 1000
  device_type: npu
  npu_devices: 8
  algorithm_nodes: auto
```

实验数和步数越大，信号通常更稳定，但计算时间、NPU 用量和中间结果也会增加；它们
不是最终 NanoChat 的训练步数。

## 4. 用户策略脚本契约

策略脚本是可信内部代码。用户提交一个上传到 OBS 并挂载到 ModelArts 的 `.py` 文件、
YAML 中的容器绝对路径（不是 `obs://` 地址），以及可选的 `config` 对象。

```python
STRATEGY_API_VERSION = "1"

def select(pool, context, config):
    # 返回 pool 中一维、无重复的整数下标。
    # pool: shard_ids/document_ids/estimated_tokens/domain_ids numpy 数组
    # context: method/token_budget/seed/domain_name
    return selected_indices
```

平台检查接口版本、函数、下标范围、重复项及 90% token 预算。样例见
`examples/strategies/random_length_aware.py` 和 `manual_quality_first.py`。

## 5. 随机策略与多个人工方案

```yaml
comparison_config:
  methods: [quadmix, random, manual]
  random_strategy:
    script_path: /home/ma-user/modelarts/inputs/strategy_dir_8/random.py
    config: {bucket_size: 2048}
  manual_plans:
    - id: stem_default
      label: STEM 默认比例
      ratios: {数学: 0.60, 物理: 0.15, 化学: 0.125, 生物学: 0.125}
      strategy: {script_path: "", config: {}}
    - id: quality_first
      label: 质量优先方案
      ratios: {数学: 0.40, 物理: 0.20, 化学: 0.20, 生物学: 0.20}
      strategy:
        script_path: /home/ma-user/modelarts/inputs/strategy_dir_8/manual.py
        config: {descending: true}
```

空路径使用内置策略。每个人工方案独立输出采样集、模型、训练日志和评测日志。第二个及
后续人工方案目前会分别扫描源 Parquet，因此准备时间增加，但训练 token 预算不变。

## 6. 输出

- `data/quadmix_data/`、`data/random_data/`；
- `data/manual_ratio_data/`：第一个人工方案；
- `data/manual_<id>_data/`：后续人工方案；
- `mid_train_*.log`、`eval_*.log`；
- `experiment_report.md/json`；
- `manual_plans_report.md/json`：所有人工方案的比例、策略、模型和 CORE 结果；
- `checkpoint_dir/<model_tag>/`：各方案 checkpoint。

## 7. 展示型 UI

```bash
python -m auto_mixture_tool.cli serve --host 0.0.0.0 --port 8080
```

访问 `http://<主机>:8080/ui`。页面只展示未来交互，不会上传、保存、提交任务或调用
自动评测 API，现有 REST API 不受影响。

## 8. ModelArts 操作

1. 把代码、NanoChat、模型、tokenizer、验证集、完整评测包、wheel 和可选策略上传 OBS。
2. 使用自定义策略时，在 `modelarts_training_job.py` 增加策略目录输入挂载。
3. YAML 的 `script_path` 填挂载后的容器绝对路径。
4. 修改 `NODE_COUNT`、QuaDMix 参数和方案列表。
5. 执行 `python3 modelarts_training_job.py`。
6. 确认日志出现 `Offline resource preflight OK` 后才会进入 QuaDMix。

自动评测 API 当前仅在 UI 展示；接口协议确定前，后端不会发送相关请求。

自定义策略的输入挂载样例（放入 `job_data["algorithm"]["inputs"]`）如下：

```python
{
    "name": "strategy_dir",
    "local_dir": "/home/ma-user/modelarts/inputs/strategy_dir_8",
    "access_method": "env",
    "remote": {"obs": {"obs_url": "obs://bucket/path/strategies/"}},
}
```
