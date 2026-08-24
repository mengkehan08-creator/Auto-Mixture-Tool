# Auto-Mixture-Tool — 可插拔的数据配比工具平台

> **⚠️ Disclaimer**: 本仓库是 QuaDMix 论文的个人 clean-room 实现，并非字节官方发布，仅供教育与研究使用。
>
> **Paper**: Fengze Liu, Weidong Zhou, Binbin Liu, et al. (ByteDance, 2025)
> [arXiv:2504.16511v2](https://arxiv.org/abs/2504.16511)

本项目包含**两部分**，自上而下协同工作：

1. **原 QuadMix 算法（`src/quadmix/`）** —— 从大规模无标签语料中为 LLM 预训练挑选高质量、领域均衡的子集。它通过约 3000 次代理实验（每次训练一个 ~1M 参数模型）学习每域采样参数，再用 LightGBM 回归预测最优配比。详见下方「Algorithm Pipeline」与「Custom Datasets」等章节。
2. **工具化可插拔平台层（`src/auto_mixture_tool/` + `src/quadmix_platform/`）** —— 把「数据校验 → 统一格式 → 配比算法 → 训练 → 验证 → 结果分析」整条流程模块化，使**算法 / 训练器 / 验证器 / 执行器均可替换**。这是本仓库相对原 QuadMix 的核心扩展。

> 想直接用平台（不关心内部算法）？跳到 [「工具化平台：快速使用」](#工具化平台快速使用)。
> 平台设计、插件编写、端到端示例的完整说明见 [`docs/AUTO_MIXTURE_TOOL.md`](docs/AUTO_MIXTURE_TOOL.md)；架构图见 [`docs/QuadMix-工具化重构模块框架图-最新.pptx`](docs/QuadMix-工具化重构模块框架图-最新.pptx)。

---

## 工具化平台：快速使用

平台通过一个运行时注册中心按 ID 装配数据集、算法、训练框架、评测集和执行后端。当前正式开放的组件：

| 模块 | 配置字段 | 当前 `id` |
|------|------|------|
| 数据集校验与标准化 | `dataset_id` | `quadmix` |
| 配比算法 | `algorithm_id` | `quadmix` |
| 训练框架 | `trainer_id` | `nanochat` |
| 评测集/评测方法 | `evaluator_id` | `stem` |
| 执行后端 | `executor_id` | `local` / `hpc-cluster` |

安装与两条入口（API + YAML 配置文件运行）：

```bash
pip install -e .                 # auto-mixture；quadmix-platform 是兼容别名

# 1) 用 YAML 配置跑一条完整实验（校验→配比→训练→验证→分析）
auto-mixture run examples/configs/demo_pipeline.yaml

# 2) 启动 HTTP API（组件目录/数据集校验/任务提交/查询）
auto-mixture serve --host 127.0.0.1 --port 8080
```

当前生产数据可直接使用 JSON、JSONL 或 Parquet 文件目录，不执行 Parquet 转换。目录数据会检查全部分片，不再只抽查第一个文件；QuadMix 的元数据加载和按需文本读取已原生支持 JSON。

完整使用说明见 [`docs/USAGE.md`](docs/USAGE.md)；模块切换见 [`docs/SWITCHING_COMPONENTS.md`](docs/SWITCHING_COMPONENTS.md)；当前 STEM JSON 的字段映射、全量审查和过滤规则见 [`docs/DATASET_AUDIT.md`](docs/DATASET_AUDIT.md)。`CanonicalPipeline` 仍保留为 Python 契约与离线参照测试，不是第二套用户入口。

---

## Algorithm Pipeline（原 QuadMix 算法）

```
Raw Shards (parquet) → Preprocess → Metadata (domain labels + quality scores) in memory
  ↓                                    (schema-driven: any domain/quality columns)
Alg.1: Sample θ = (α₁…αₘ, β₁…βₘ)
  ↓
For each θ:
  Eq.1: Merge quality signals with αₘ → ¯q
  Eq.2: Rank ¯q within domain (subsample reference) → ¯r
  Eq.3: S(¯r) = sigmoid(λ(ω-¯r))^η + ε → Bernoulli sample
  Train 1M param proxy model → per-task val_loss (full-sequence)
  (RegMix-style: permutation shuffle, warmup_fraction=4%)
  ↓
Per-task LightGBM: R(θ) → predicted loss per capability cluster
  (Adaptive regime: conservative/moderate/aggressive based on n/p ratio)
  (K-fold CV for R² estimation, R²≤0 tasks filtered)
  ↓
Search: Alg.1 × 5K → R²-weighted z-score → top-K average → θ*
  ↓
Eq.1+Eq.2(θ*.αₘ) → Eq.3(θ*.βₘ) → Sampled Dataset
```

## Project Structure（真实目录）

```
Auto-Mixture-Tool/
├── configs/                       # YAML 数据集 schema 配置
│   ├── schema_essential_web.yaml      # Essential-Web（示例数据集）
│   └── schema_stem.yaml
├── src/
│   ├── quadmix/                   # 原 QuadMix 算法实现（保持独立，可被平台抽入）
│   │   ├── core/                      # 核心算法（Eq.1-3、proxy model、域分类、质量打分）
│   │   ├── pipeline/                  # Pipeline 编排（real_pipeline / optimizer / proxy_runner）
│   │   ├── sampling/                  # Bernoulli 批量采样
│   │   ├── data/                      # DatasetSchema（YAML 列映射）、多格式适配器
│   │   └── npu/                       # DeviceManager（CPU/CUDA/NPU）
│   ├── auto_mixture_tool/         # ★ 工具化平台层（新增）
│   │   ├── cli.py                      # 命令行入口（serve / run <yaml>）
│   │   ├── api/server.py              # FastAPI 服务
│   │   ├── pipeline.py                # PipelineManager 编排器
│   │   ├── config/                    # YAML 配置加载
│   │   ├── data/validator.py          # 数据集校验（含可替换格式校验）
│   │   ├── results/analysis.py        # 结果分析器
│   │   ├── core/                      # ★ 规范契约实现（Phase 1+2）
│   │   │   ├── dataset.py                 # UnifiedDataset / Sample（CSV/JSON/JSONL/Parquet 加载 + JSON 写出）
│   │   │   ├── mixing.py                 # MixingAlgorithm 参照 + 命令桥接
│   │   │   ├── quadmix_algorithm.py       # quadmix-core（抽入真实算法）
│   │   │   ├── training.py                # Trainer 参照 + 命令桥接
│   │   │   ├── nanochat_trainer.py        # nanochat-core（抽入真实训练）
│   │   │   ├── evaluation.py              # Evaluator 参照 + 命令桥接
│   │   │   ├── stem_evaluator.py          # stem-core（抽入真实评估）
│   │   │   ├── registry.py                # 统一注册表（按 id 装配）
│   │   │   └── pipeline.py                # CanonicalPipeline 端到端编排
│   │   └── plugins/                   # 命令式 Adapter 插件（算法/训练/验证/执行/格式校验）
│   └── quadmix_platform/          # 原平台抽象层
│       ├── interfaces.py              # 四个核心接口 + 四个 Adapter + FormatValidatorAdapter
│       ├── components.py              # local / hpc-cluster 执行器
│       ├── service.py                 # 注册中心
│       ├── registry.py                # ComponentRegistry
│       └── api.py / cli.py            # 原入口（仍可用）
├── scripts/
│   ├── runners/                   # 原算法入口（run_essential_web_v1.py 等）
│   ├── platform/                  # 平台插件调用的可执行脚本
│   ├── preprocess/  validation_set/  analysis/   # 预处理 / 验证集 / 分析
│   └── demo_run_quick.sh  demo_run_full.sh  demo_revalidate.sh  demo_reoptimize.sh  resample.sh
├── nanochat_mid_compare/          # 下游中训练对比框架（QuadMix vs Random vs Quality）
├── examples/                      # 平台示例（configs/demo_pipeline.yaml、platform/ 样例数据）
├── openapi/                       # quadmix-platform.yaml（API 契约）
├── docs/                          # 文档与架构图（含 AUTO_MIXTURE_TOOL.md、PPT）
├── data/  result/  temp/          # 验证集（自动下载）/ 结果 / 中间数据
└── tests/                         # 离线单测（含 CanonicalPipeline 端到端）
```

## Quick Start（原算法路径）

### Virtual compute platform

仓库内置 REST API 编排层，用于数据集校验与可切换的算法/训练器/验证器/执行器模块：

```bash
pip install -e .
quadmix-platform serve --host 127.0.0.1 --port 8080
```

打开 `http://127.0.0.1:8080/api/v1/health`。任务由 `executor_id` 指定的后端执行：dev 默认 `local`（本地子进程跑各阶段，需 `pip install -e .`），生产改 `hpc-cluster` 提交到 HPC 集群 API。完整接口与使用说明见
[`docs/USAGE.md`](docs/USAGE.md)，集成指南与 API 契约见
[`docs/PLATFORM_INTEGRATION_ZH.md`](docs/PLATFORM_INTEGRATION_ZH.md) 与
[`openapi/quadmix-platform.yaml`](openapi/quadmix-platform.yaml)。

生产环境文件摆放、控制面/工作节点拆分、所需平台改动、上线步骤与验收清单见
[`docs/FINAL_PLATFORM_DEPLOYMENT_ZH.md`](docs/FINAL_PLATFORM_DEPLOYMENT_ZH.md)。

### Algorithm CLI（原 QuadMix 算法）

```bash
# Install
pip install -e .

# Essential-Web demo (~1.5h, 8x NPU) — 使用示例数据集配置
bash scripts/demo_run_quick.sh

# Large-scale Essential-Web demo (~数h, 8x NPU, 500 shards)
bash scripts/demo_run_full.sh

# Custom dataset — 参考 configs/schema_essential_web.yaml 写自己的 YAML
python scripts/runners/run_essential_web_v1.py \
    --schema configs/schema_essential_web.yaml \
    --preprocessed-dir temp/preprocessed \
    --num-experiments 500 \
    --num-search 5000 \
    --block-size 2048 \
    --val-set cap_v1 \
    --search-mode r2_sigma_weighted \
    --output result/my_run

# Re-evaluate with new validation set (no proxy retraining)
bash scripts/demo_revalidate.sh --result-dir result/xxx --val-set cap_v1

# Re-optimize from existing losses
bash scripts/demo_reoptimize.sh --result-dir result/xxx

# Resample with optimal θ* on expanded data pool
DATA_DIR=/path/to/data PARAMS_FILE=result/xxx/optimal_parameters.json \
  bash scripts/resample.sh
```

> **Note**: 默认验证集（`cap_v1`）首次运行会自动从
> [HuggingFace](https://huggingface.co/datasets/liujin99/quadmix-cap-v1) 下载。
> 其它验证集（`core_bmk_v6`、`openhermes` 等）也可经 `--val-set` 指定。

## Custom Datasets

QuaDMix 通过 YAML schema 配置支持任意数据集。所有数据集（含 Essential-Web）都必须指定 `--schema`。参考 `configs/schema_essential_web.yaml`。

### Your parquet must have:

| Column type | Required | dtype | Example |
|---|---|---|---|
| domain | ✓ | string or int | `category_name` (string) → auto-mapped to int 0..M-1 |
| quality | ✓ (1+ cols) | float | `category_score`, `stem_relevance` |
| text | ✓ | string | `content` |
| char_count | optional | int | `doc_len` (if null → computed from text length) |
| row_in_shard | optional | int | `row_in_shard` (if null → positional indexing) |

### Example: STEM dataset config

```yaml
# configs/schema_stem.yaml — actual config (copy and modify for your dataset)
domain_col: category_name            # string column → auto int mapping via domain_names
domain_names:                        # controls string→int mapping order (数学=0, 化学=1, ...)
  - 数学
  - 化学
  - 生物学
  - 物理

quality_cols:                        # all default to higher_better=true
  - stem_relevance                   #   (pre-processed: higher score = better quality)
  - knowledge_value
  - notation_fidelity
  - rigor_coherence
  - noise_level                      #   (pre-processed: higher score = less noise = better)

quality_names:                       # display names in reports/figures (optional, defaults to col names)
  - stem_relevance
  - knowledge_value
  - notation_fidelity
  - rigor_coherence
  - noise_level

text_col: text                       # document text column
char_count_col: char_count_col       # pre-computed token proxy (null → compute from text)
row_in_shard_col: source_record_idx  # explicit row indexing (null → positional)
```

对于质量列中分数越低代表质量越高的情况，使用 dict 语法：

```yaml
quality_cols:
  - stem_relevance                   # higher_better=true (default)
  - name: noise_level                # override: lower score = better quality
    higher_better: false
```

### Then run:

```bash
python scripts/runners/run_essential_web_v1.py \
    --schema configs/schema_stem.yaml \
    --preprocessed-dir /path/to/stem/shards \
    --output result/stem_run
```

详见 `docs/DATASET_SCHEMA_DESIGN.md`。

## Validation Sets

| 验证集 | 来源 | 特点 | 默认 |
|--------|------|------|------|
| **cap_v1** | 外部训练数据(70%) + benchmark train(30%) | 能力对齐，绕过 C2 假设，5 clusters × 8K = 40K samples | ✓ |
| **stem_v1** | 4 STEM benchmarks (GSM8K/MMLU-22STEM/ARC-Easy/ARC-Challenge) | 与下游直接对应 (arc_easy/arc_challenge/mmlu_stem/gpqa_diamond/gsm8k_cot/math_cot_500)，full-sequence loss，~10.5K samples | |
| core_bmk_v6 | 21 个 CORE benchmark | Benchmark 对齐，per-task loss，~31K samples | |
| openhermes | OpenHermes-2.5-1M | SFT 对话格式，通用质量信号，10K samples | |

## Validation Status

**已验证环境：**

| 配置项 | 规格 |
|-------|------|
| NPU | 8x Ascend 910B3, 64GB VRAM each |
| 内存 | 1500 GB |
| CPU | ARM 192 vCPUs |
| 验证脚本 | `demo_run_quick.sh` (8 experiments) / `demo_run_full.sh` (500 experiments) |
| 验证结果 | ✓ RegMix 风格训练 + CAP v1 验证集 + per-task LightGBM |

验证日志：
- 并行 tokenize (多 worker + 多线程) 正常执行
- 动态任务队列调度正常（8 NPU 并行）
- Per-task val_loss 计算正常（5 capability clusters）
- Permutation shuffle 训练循环正常（无放回 epoch 遍历）
- Per-task LightGBM 回归 + R²-weighted 搜索正常
- NPU HBM 显式释放 — 实验间 `gc.collect()` + `torch.npu.empty_cache()`
- Optimizer inf/nan 过滤 — 防止非有限 val_loss 污染 LightGBM

## Demo Scripts

| 脚本 | 设备 | 数据量 | 实验 | 搜索点 | 步数 | 耗时 | 用途 |
|------|------|--------|------|--------|------|------|------|
| `demo_run_quick.sh` | 8x NPU | 20 shards | 8 | 1,000 | 5,000 | ~1.5h | **快速测试** |
| `demo_run_full.sh` | 8x NPU | 500 shards | 500 | 5,000 | 5,000 | ~数h | 大规模验证 |
| `demo_revalidate.sh` | NPU | — | — | 100,000 | — | ~30min | 换验证集重评估 |
| `demo_reoptimize.sh` | CPU | — | — | 100,000 | — | ~5min | 用已有 loss 重优化 |
| `resample.sh` | CPU | 全量 | — | — | — | ~1h | θ* 重采样 |

所有训练 demo 使用 CAP v1 验证集（40K samples）、warmup_fraction=4%、`configs/schema_essential_web.yaml` schema（22 域）。

## Architecture Highlights

### Multi-Shard Scalability
|- **Schema-driven**: YAML config maps any parquet columns to domain/quality/text
|- **Metadata in memory**: only domain labels + quality scores (~12 GB for 275M docs, Essential-Web)
|- **Text on demand**: per-shard parquet, loaded only for selected documents
|- **mmap token cache**: `np.load(path, mmap_mode='r')` — pages loaded lazily, not full file
|- **Multi-format adapters**: JSON, JSONL, CSV, Parquet, plain text via unified registry

### Multi-NPU Parallelism
|- **Dynamic task queue**: Workers fetch tasks on-demand, no batch boundaries
|- **Auto load-balancing**: Fast workers naturally do more experiments
|- **CPU-NPU overlap**: Tokenize thread runs independently, ahead of training
|- **~8x speedup**: 3000 experiments reduced from ~100h to ~15h with 8 NPUs

### Per-Task LightGBM
|- **5 capability clusters**: world_knowledge, symbol_logic, language_understanding, reading_comprehension, common_sense_reasoning
|- **Adaptive regime**: conservative (n/p<3) / moderate (3-8) / aggressive (≥8) hyperparameters
|- **K-fold CV**: Per-task R² estimation, R²≤0 tasks auto-filtered
|- **R²-weighted search**: High-R² tasks contribute more to search objective

### Incremental Workflow
|- **Re-validate**: Swap validation set without retraining proxy models
|- **Re-optimize**: Re-run LightGBM + search with existing losses
|- **Resample**: Apply θ* to expanded data pool without re-running pipeline

### Directory Layout
| Path | Content | Persistence |
|------|---------|-------------|
| `result/<experiment>/` | optimal_parameters.json, sampled_dataset.parquet, report, figures | Permanent |
| `temp/preprocessed/` | domain labels + quality scores per shard (schema-driven) | Keep until data changes |
| `temp/token_cache/` | mmap-able .npy files (one per shard) | Auto-regenerated |

### Data Flow
```
Raw: 3291 shards × 246 MB = ~808 GB total (Essential-Web, ~260B tokens)
  │                                       (or any dataset with YAML schema)
  ▼ [preprocess: domain + quality signals, schema-driven]
Preprocessed: 1 shard → 1 parquet (~180 MB each)
  │
  ▼ [ShardMetadataManager: in-memory metadata, schema-driven]
In-memory: domain(275M int64) + quality_scores(275M×N float64)
  │
  ▼ [EssentialWebProxyRunner: per-experiment, schema-driven column names]
Token Cache: shard_{idx}_bs{bs}.npz (mmap-mode, int32 + row_index)
  │
  ▼ [Per-task LightGBM + R²-weighted search]
Final: optimal_parameters.json + sampled_dataset.parquet
```

## Output

```
result/<experiment_name>/
├── optimal_parameters.json        # Optimal θ (α_m + β_m)
├── pipeline_summary.json          # Config + metrics + statistics
├── sampled_dataset.parquet        # Final optimally sampled dataset
├── quadmix_report.md              # Comparison report (with per-task R²)
├── fig1_domain_distribution.png   # Original vs optimal domain distribution
├── fig2_quality_weights.png       # Quality signal weights
└── proxy_experiments/             # Per-experiment results
    ├── exp_0000/
    │   ├── meta.json                # Full parameters + per-task val_loss
    │   ├── model.pt                 # Saved proxy model weights (for re-validation)
    │   ├── selected_indices.npy     # Selected document indices
    │   └── checkpoint_trajectory.json  # val_loss at checkpoint intervals
    └── exp_0001/ ...
```

## Downstream Evaluation

`nanochat_mid_compare/` 提供通过中训练对比 QuadMix 与基线的框架：

```bash
# QuadMix vs Random vs Quality(dclm) vs Quality(fineweb_edu)
QUADMIX_SAMPLED_DATA=result/xxx/sampled_dataset.parquet \
PREPROCESSED_DATA_DIR=temp/preprocessed \
bash nanochat_mid_compare/run_experiment.sh
```

Baselines are token-budget aligned (same total tokens as QuadMix output) and share the same base model checkpoint.

## License

Apache 2.0
