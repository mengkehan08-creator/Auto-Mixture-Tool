# Auto-Mixture-Tool

数据配比、小规模训练验证与结果对比工具。通过网页配置 QuaDMix、自定义配比或随机基线，在华为云 ModelArts 上执行配比、NanoChat 训练和汇总评测。

本仓库包含当前已完成的多节点适配：**一次 NanoChat 训练作业可跨多个节点组成同一个分布式训练组**；QuaDMix 代理实验则在同一配比作业内按节点分配实验。当前 Web 流程中，各策略分别创建配比和训练作业，全部必需训练成功后创建汇总评测作业。

**仓库地址：** [mengkehan08-creator/Auto-Mixture-Tool](https://github.com/mengkehan08-creator/Auto-Mixture-Tool)。本仓库为公开仓库，可直接克隆。

## 1. 版本与运行边界

| 组件 | 本次分析及适配使用的版本 | 部署方式 |
| --- | --- | --- |
| QuaDMix | [liujin99/quadmix](https://github.com/liujin99/quadmix)，`refactor/structure`，`2591a6d5e215a62e17f0a1769dcd769ca69f3c1a` | 算法及适配代码已在本仓库 `src/quadmix/` 中，运行本工具无需另装 QuaDMix 仓库 |
| NanoChat NPU | [liujin99/nanochat-npu](https://github.com/liujin99/nanochat-npu)，`dev-data-mix`，`6e5baa26317defa669c08e329ee819fff5908c40` | 作为独立框架代码上传 OBS，训练和评测使用同一版本 |
| Climb / Climb-MA | [liujin99/climbmix](https://github.com/liujin99/climbmix) 与已跑通的 Climb-MA 启动方式 | 用于参考拓扑解析、全局数据分片、训练与评测衔接；运行本工具不要求额外启动 Climb |

配置支持 **1～16 节点，每节点固定 8 张 NPU**。配置范围不等于所有节点规模均已完成 Ascend/HCCL 验收。此版本已有 CPU/Gloo 数值测试、脚本执行测试和前端构建验证；真实云端多节点运行须按第 10 节完成验收。

本工具的网页和 API 是控制面，可以部署在 ModelArts Notebook 或可访问云端资源的 Linux 主机。NPU 训练由 ModelArts 作业容器执行，运行网页不需要在控制面安装 `torch_npu`。

### 当前支持的 ModelArts 提交接口

现有 Web 提交器使用 `modelarts_training_job.py` 定义的 `kind / metadata / algorithm / spec` 请求体，通过 `Authorization` 和 `region` 请求头访问已适配的 ModelArts 网关。可复用你已经跑通 Climb-MA 的镜像、资源池和网关参数。

`iam_token_provider.py` 的自动取 Token 逻辑面向现有网关的 IAM JWT 服务。华为云标准 API 的 Token 认证使用 `X-Auth-Token`，不能仅替换 URL 就认定 Web 自动提交可用。没有兼容网关时，可由管理员基于本工具生成的作业配置使用控制台/API Explorer 创建作业，或者先适配提交与查询鉴权；参见华为云官方 [创建训练作业 API](https://support.huaweicloud.com/api-modelarts/CreateTrainingJob.html) 与 [使用 API 创建训练作业](https://support.huaweicloud.com/develop-modelarts/develop-modelarts-0139.html)。

## 2. 部署前准备

建议先复用已跑通 Climb-MA 的同一环境，再迁移工具代码和小规模验证链路。

| 需要准备 | 检查内容 |
| --- | --- |
| ModelArts 与 OBS 权限 | 创建、查询训练作业；读取代码、数据、模型和评测集；写入输出与节点协调目录 |
| 运行资源 | 对应区域的资源池、每节点 8 卡 NPU 规格及足够节点配额 |
| 训练镜像 | 已匹配 Ascend 驱动、CANN、PyTorch、`torch_npu` 的 Python 3.11 / aarch64 镜像 |
| 控制面 | Linux、Python 3.11、Git；能访问作业网关并读取配置的 OBS 本地挂载 |
| 网络 | 训练节点可相互访问，能进行 rendezvous、HCCL 通信与必要的检查点传输 |
| 资产 | 原始候选 Parquet、两套 Tokenizer、基础 checkpoint、代理验证集、评测包与离线 wheel |

在 ModelArts 中完成委托授权，自定义训练镜像按区域上传至 SWR；操作入口以当前控制台为准，参考官方 [创建训练作业指南](https://support.huaweicloud.com/develop-modelarts/develop-modelarts-0022.html)。多机资源与网络准备可参考官方 [多机多卡训练指南](https://support.huaweicloud.com/bestpractice-modelarts/modelarts_20_2040.html)，其中 GPU 示例不能直接替代本项目的 Ascend 镜像与启动脚本。

本工具当前面向可信内部用户，没有独立的多用户登录和租户隔离。网页应经已认证的 Jupyter 端口代理或内部网关访问。

## 3. 下载代码并部署控制面

以下命令在 ModelArts Notebook 的 JupyterLab Terminal 或 Linux 控制面主机执行。

```bash
cd /home/ma-user/work
git clone https://github.com/mengkehan08-creator/Auto-Mixture-Tool.git
cd Auto-Mixture-Tool
git log -1 --oneline

python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
export PYTHONPATH="$PWD:$PWD/src:${PYTHONPATH:-}"
python -c "import fastapi, uvicorn, requests, yaml, numpy, pandas, pyarrow; print('UI dependencies OK')"
```

公开仓库可通过 HTTPS 无需登录克隆。云环境无法访问 GitHub 时，在可联网机器制作代码包，再上传到 JupyterLab 解压。

安装成功应输出 `UI dependencies OK`。仓库已包含构建后的前端，普通部署无需安装 Node.js。控制面完整离线安装步骤见 [部署 Wiki](docs/WIKI_DEPLOYMENT.md#deploy-install)。

## 4. 准备 OBS 资源

下面统一使用 `obs://YOUR_BUCKET/amt/` 作为示例，必须替换成自己的真实桶和目录。仓库中的旧环境默认资源仅供已有环境复用，不能作为新账号拥有这些资源的依据。

```text
obs://YOUR_BUCKET/amt/
├── releases/<版本>/Auto-Mixture-Tool/  # 当前工具代码
├── frameworks/nanochat-npu/           # dev-data-mix 固定版本代码
├── datasets/prepared/                 # 候选文本 Parquet
├── models/nanochat-base/              # checkpoint 与 NanoChat Tokenizer
├── tokenizers/gpt-neox/               # QuaDMix Tokenizer
├── validation/proxy/                  # stem_v2_tokenized.pt
├── validation/eval_bundle/            # CORE/STEM 评测资源
├── wheels/                           # 与训练镜像匹配的离线 wheel
└── runs/                             # 作业输出、模型和报告
```

### 4.1 下载指定 NanoChat 分支

在可访问 GitHub 的 Linux 主机执行：

```bash
cd /home/ma-user/work
git clone --branch dev-data-mix https://github.com/liujin99/nanochat-npu.git
cd nanochat-npu
git checkout --detach 6e5baa26317defa669c08e329ee819fff5908c40
git rev-parse HEAD
```

将这个 checkout 的代码上传至 `frameworks/nanochat-npu/`。以后升级分支时重新执行兼容检查和短训练验收；不要让训练与评测使用不同版本。

### 4.2 输入数据格式

当前 Web 配比流程读取文本 Parquet。每个分片须至少包含以下字段，具体定义见 [数据 Schema](configs/schema_stem_quadmix_parquet.yaml)：

| 字段 | 要求 |
| --- | --- |
| `domain` | 非空领域名称或符合 Schema 的编码 |
| `text` | 非空字符串 |
| `char_count` | 正整数 |
| `stem_relevance`、`knowledge_value`、`notation_fidelity`、`rigor_coherence`、`noise_level` | 有限数值，不能为 NaN 或无穷大 |

格式示例见 [Parquet 示例生成脚本](examples/datasets/quadmix_parquet.py)。示例数据用于检查格式，不能作为正式算法有效性验证的数据集。

网页会抽查各分片；云端采样/训练还会检查实际使用的数据。NanoChat 按全局 rank 分配 Parquet 行组，因此准备后的训练文件须为所有 rank 提供非空数据。仅把作业节点数调大，不会自动补足小数据集。

### 4.3 基础模型和两套 Tokenizer

NanoChat 基础模型目录示例：

```text
nanochat-base/
├── base_checkpoints/
│   └── d24/
│       ├── model_XXXXXX.pt
│       └── meta_XXXXXX.json
└── tokenizer/
    ├── tokenizer.pkl
    └── token_bytes.pt
```

`d24` 必须是模型目录中真实存在的标签，权重与元数据应成对。模型结构、序列长度和默认全局 batch 以 checkpoint 元数据为准。

QuaDMix 的 GPT-NeoX Tokenizer 目录须包含 `tokenizer.json` 等文件。它与 NanoChat 基础模型的 Tokenizer 是不同资源；`stem_v2_tokenized.pt` 是代理验证数据，不能替代任何一套 Tokenizer。

### 4.4 评测包与离线依赖

评测包须保留所选任务引用的所有文件，例如：

```text
eval_bundle/
├── core.yaml
├── eval_meta_data.csv
├── eval_data/
└── eval_stem/
    ├── eval_meta_data.csv
    └── eval_data/
        ├── gpqa_diamond.jsonl
        ├── gsm8k.jsonl
        ├── math500.jsonl
        └── mmlu_stem.jsonl
```

真实任务依赖以固定版本 NanoChat 的定义为准。自定义任务包见 [评测包说明](docs/OBS_EVALUATION_PACKAGES.md)。空文件不能代替评测数据。

当前默认云端 command 使用 Python 3.11 / aarch64，离线资源目录至少要提供以下两个指定文件：

```text
lightgbm-4.6.0-py3-none-manylinux2014_aarch64.whl
rustbpe-0.1.0-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl
```

其他依赖应已在训练镜像中：NumPy、Pandas、PyArrow、SciPy、scikit-learn、joblib、matplotlib、tqdm、psutil、Jinja2、PyTorch、`torch_npu`、Transformers、tokenizers、datasets、tiktoken、filelock、requests、PyYAML。完整运行检查以 [modelarts_runtime_check.py](scripts/modelarts_runtime_check.py) 为准。

这两个 wheel 不是完整离线 Python 环境。不要单独升级镜像中的 PyTorch、`torch_npu` 或 CANN；沿用已经验收的配套版本。

## 5. 上传同一版本的工具代码

控制面代码与云作业读取的 OBS 代码必须是同一版本。在已克隆本仓库的控制面执行：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
RELEASE_ID=$(git rev-parse --short HEAD)
RELEASE_DIR="/home/ma-user/work/amt-release-$RELEASE_ID"
mkdir -p "$RELEASE_DIR"
git archive --format=tar --prefix=Auto-Mixture-Tool/ \
  -o "$RELEASE_DIR/Auto-Mixture-Tool.tar" HEAD
tar -xf "$RELEASE_DIR/Auto-Mixture-Tool.tar" -C "$RELEASE_DIR"
```

用 OBS 控制台或现有 OBS 上传工具，把解压后 `Auto-Mixture-Tool/` 中的文件上传到：

```text
obs://YOUR_BUCKET/amt/releases/<RELEASE_ID>/Auto-Mixture-Tool/
```

该目录下直接包含 `pyproject.toml`、`src/`、`nanochat_mid_compare/`、`scripts/`、`configs/`。保留末级目录名称 `Auto-Mixture-Tool`，因为默认启动命令按此名称查找下载后的代码目录。

不要只上传压缩包，也不要套成两层同名目录。`git archive HEAD` 仅打包已提交的代码，不包含未提交修改。运行记录、虚拟环境与真实 IAM 认证文件不属于发布代码。

## 6. 配置控制面的 OBS 映射和认证

### 6.1 配置真实挂载

先由环境管理员将 OBS 资源映射为控制面可读取的目录。假设实际映射为：

```text
obs://YOUR_BUCKET/amt/ → /mnt/amt/
```

在启动后端的终端设置：

```bash
export AMT_OBS_MOUNT_ROOT=/mnt/amt
export AMT_OBS_MOUNT_PREFIX=obs://YOUR_BUCKET/amt/
ls -ld /mnt/amt/datasets/prepared
ls -ld /mnt/amt/frameworks/nanochat-npu
ls -ld /mnt/amt/validation/eval_bundle
```

这些环境变量只声明 URI 与本地目录的对应关系，**不会自动挂载 OBS**。后端需要这份映射进行输入和评测资源校验，并读取结果报告。实际资源不在映射范围时，应调整真实挂载和对应配置。

### 6.2 使用现有网关的自动 IAM 认证

已有兼容网关时，将认证模板复制到仓库外：

```bash
mkdir -p /home/ma-user/work/private_auth
chmod 700 /home/ma-user/work/private_auth
cp -n /home/ma-user/work/Auto-Mixture-Tool/iam_token_provider.py \
  /home/ma-user/work/private_auth/iam_token_provider.py
chmod 600 /home/ma-user/work/private_auth/iam_token_provider.py
export AMT_IAM_PROVIDER=/home/ma-user/work/private_auth/iam_token_provider.py
```

在私有副本中填写管理员提供的 `account`、`secret`、`project`、`enterprise`。网关不是默认地址时，应配置真实 `modelarts_endpoint` 限制认证目标；需要内部 CA 时设置 `ca_bundle`。保留证书验证。

这份文件只放在控制面，不上传 GitHub、OBS 或训练镜像。后端在提交作业时取 Token，不要求把长期凭据写进页面。完整参数见 [IAM 认证说明](docs/IAM_AUTH.md)。

也可不启用自动 IAM：在启动终端执行 `unset AMT_IAM_PROVIDER`，然后在“任务配置”填入网关要求的有效 Authorization。此方式的 Token 更新由使用者负责。

## 7. 启动网页和 API

在已经设置好挂载与认证变量的同一个终端执行：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
source .venv/bin/activate
export PYTHONPATH="$PWD:$PWD/src:${PYTHONPATH:-}"
python -m auto_mixture_tool.cli --workspace "$PWD" \
  serve --host 0.0.0.0 --port 8080
```

保持服务运行。另开终端验收：

```bash
curl --noproxy '*' http://127.0.0.1:8080/api/v1/health
curl --noproxy '*' -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/ui
```

预期分别为健康 JSON 和 HTTP `200`。

如果 JupyterLab 地址为 `https://<域名>/<实例前缀>/lab`，并且已启用端口代理，打开：

```text
https://<域名>/<实例前缀>/proxy/8080/ui
```

保留实际域名和实例前缀。直接在自己电脑打开 `127.0.0.1` 访问的是自己电脑，不能访问远程 Notebook；不能通过双击静态 HTML 替代运行后端。

后端采用单进程管理一个工作区。关闭网页不会停止云作业；控制面实例休眠或后端退出会影响监控和后续作业提交。后台运行及升级方法见 [部署 Wiki](docs/WIKI_DEPLOYMENT.md#deploy-start)。

## 8. 在网页创建首个实验

按页面四步依次填写。

### 8.1 配比策略

1. 填写真实输入目录，例如 `obs://YOUR_BUCKET/amt/datasets/prepared/`。
2. 填写实验输出根目录，例如 `obs://YOUR_BUCKET/amt/runs/`。
3. 首次链路验证可以只保留随机策略，以便先确认数据准备与多节点训练能够衔接；采样作业用 1 节点。
4. 测试 QuaDMix 时，将代理实验数设置为至少 `节点数 × 8`，代理步数可用 15；正式算法验证应增加实验量并查看回归与验证表现。
5. 等待输入校验通过。默认抽查不是全文数据质量保证。

### 8.2 训练配置

填写 NanoChat 框架 OBS 目录、基础模型目录与真实模型标签。所有策略共用相同基础权重、Tokenizer、训练预算和评测协议，避免比较口径变化。

以基础 checkpoint 的序列长度为 **2048** 为前提，2 节点短训练示例：

| 参数 | 示例 |
| --- | ---: |
| 训练节点数 | 2 |
| 每节点 NPU 数 | 8 |
| 单卡 batch | 1 |
| 全局 batch Token 数 | 524288 |
| 训练 Token 预算 | 10485760 |
| 预计优化步数 | 20 |
| `eval_every` / `core_metric_every` | -1 / -1 |

这组参数用于检查链路。使用不同序列长度的模型前，按第 9 节重新计算。增加节点数不会降低模型每张卡所需的基础显存。

当前流程加载基础模型权重、默认冷启动优化器。旧优化器状态可能按原 world size 分片，改变节点数时不能直接恢复。

### 8.3 评测配置

选择已准备好的内置任务和评测包目录。初次验收可选择少量任务并使用页面提供的样本上限，随后对同一 checkpoint 使用完整任务协议验收。

评测节点数独立于训练节点数。训练完成后的模型通过 INPUT 挂载交给独立评测作业；不要把评测作业自己的 OUTPUT 路径当成已训练模型来源。

### 8.4 任务配置与提交

将资源全部改成第 4、5 节的实际 OBS 地址，然后填写以下环境参数：

| 字段 | 获取方式 |
| --- | --- |
| 作业创建 API 地址、region | 已跑通环境提供的兼容网关与区域 |
| Authorization | 自动 IAM 获取，或手动填写当前有效值 |
| `workspace_id` / 工作空间 | ModelArts 环境中的真实工作空间 |
| `image_url` / `image_repo_id` | 已准备好的训练镜像和镜像仓库信息 |
| `flavor_id` | 每节点 8 张 NPU 的规格 |
| `pool_id` | 可分配所需节点数的资源池 |
| 工具代码、GPT-NeoX Tokenizer、代理验证集、评测包、离线 wheel | 相应 OBS 目录 |

默认命令已经负责离线环境设置、依赖检查与阶段启动，优先保留默认命令。检查预览中的节点数、输入挂载和输出目录，再点击提交。

在“实验作业”查看各策略阶段、云作业 ID、日志及结果。配比成功后自动创建对应训练，全部必需训练成功后进行汇总评测。关闭页面不取消作业。

网页流程无需直接执行根目录 `modelarts_training_job.py`。该脚本用于另一路完整流水线提交样例，节点数为 2～16，并需同步配置 `examples/configs/modelarts_pipeline.yaml` 的全部资源。不要同时执行它和网页提交同一实验。

## 9. 多节点训练的计算与检查

### 9.1 拓扑和单作业执行

```text
一个 ModelArts 训练作业
  ├── 节点 0：torchrun → rank 0..7
  ├── 节点 1：torchrun → rank 8..15
  └── ……
       所有 rank 属于同一个训练组，共同更新同一个模型
```

平台应提供 `MA_NUM_HOSTS`、节点编号 `VC_TASK_INDEX` 和节点列表 `VC_WORKER_HOSTS`；也支持显式 `NNODES / NODE_RANK / MASTER_ADDR / MASTER_PORT` 及已适配的 worker 主机名回退。环境变量有冲突或缺失时会失败。

所有节点使用同一个唯一 `AMT_RUN_ID`。默认训练 rendezvous 端口为 29500，同作业评测和检查点 relay 使用后续端口；HCCL 还需环境规定的通信网络。不要将所有节点的 `NODE_RANK` 都设置为 0。

QuaDMix 是代理实验并行：各节点运行不同全局编号的实验，由协调流程汇总。它与 NanoChat 的同模型多节点训练采用不同并行方式。
两者共用节点身份解析，支持上述节点数、节点编号及 worker 主机名回退；QuaDMix
通过 OBS 协调，不要求配置训练用的 `MASTER_ADDR`。使用 `obsutil` 时，工具会为
目录上传和下载自动添加 `-flat`，保持模型和采样数据目录层级一致。

### 9.2 全局 batch 必须符合拓扑

```text
world_size = 节点数 × 8
micro_tokens = world_size × device_batch_size × sequence_len
梯度累积次数 = total_batch_size / micro_tokens
优化步数 = ceil(token_budget / total_batch_size)
actual_tokens = 优化步数 × total_batch_size
```

全局 batch 必须是 `micro_tokens` 的整数倍。字段留空时继承基础 checkpoint；继承值不兼容新拓扑时，启动前报错，不会静默增加 batch。预算会向上取整到完整优化步。

在序列长度 2048、单卡 batch 1 时：

| 节点配置 | 可用全局 batch 示例 | 用法 |
| --- | ---: | --- |
| 1 / 2 / 4 节点 | 524288 | 各拓扑均可整除 |
| 单个 3 节点作业 | 540672 | 适合 24-rank，不能直接套用到 2 节点 |
| 对比 1 / 2 / 3 / 4 节点 | 1572864 | 所有比较作业共同使用这个兼容值 |

比较节点扩缩容时，还要固定基础权重、优化器初始化、数据打包方式和评测协议。检查 `training_record.json` 的实际步数与 `actual_tokens`，不要只比较页面请求的预算。

### 9.3 输出不依赖共享 OUTPUT 目录

运行布局区分只读基础模型/Tokenizer 和每节点可写目录。同作业内需要评测时，node 0 将明确 step 的 model/meta 传给其他节点，按作业身份和 SHA-256 校验后再启动评测。

完整拓扑、协调、检查点与数据分片说明见 [SCALING_MODELARTS_NODES.md](docs/SCALING_MODELARTS_NODES.md)。

## 10. 按顺序验收，再扩大规模

1. **控制面验收：** `/api/v1/health` 与 `/ui` 可访问；输入数据、框架和评测包可通过本地映射读取。
2. **单节点验收：** 用一项策略完成配比、10～20 步训练和少量评测，检查训练记录与模型发布。
3. **两节点验收：** 完成 16-rank 短训练，确认各全局 rank 均有非空数据；参数、节点编号与协调目录一致。
4. **四节点验收：** 在同一模型和兼容全局 batch 下完成 32-rank 短训练，检查 HCCL、HBM 释放及大文件同步。
5. **评测一致性：** 对同一 checkpoint 比较 8/16/32-rank 的样本覆盖和指标，提前定义并核查合理容差。
6. **正式实验：** 增加代理实验数、训练预算和完整评测任务；保留版本、镜像、模型、统计与报告。

短训练只说明链路可执行，不足以证明 QuaDMix 优于随机或人工策略。

### 本地回归测试

开发主机安装测试依赖后执行：

```bash
python -m pip install pytest
python -m pytest -q tests
```

要启用固定 NanoChat 版本的真实优化器 CPU/Gloo 数值测试，还需在独立测试环境安装兼容的 CPU PyTorch，并设置：

```bash
NANOCHAT_TEST_REPO=/path/to/nanochat-npu \
python -m pytest -q tests/test_nanochat_training_runtime.py
```

未设置外部框架路径时跳过该项测试。不要用 CPU PyTorch 包覆盖 Ascend 训练镜像的 PyTorch。仓库根目录历史文件 `test_v4.2_implementation.py` 不符合 pytest 模块命名规则，完整回归使用 `pytest tests`。

前端源码维护者执行：

```bash
cd ui_demo
npm ci
node --test --test-concurrency=1 src/*.test.mjs
npm run build
```

本次多节点适配的此前验收：后端 519 项测试及 20 项子测试通过，包含真实固定版本优化器测试；前端构建和相关测试通过。完整前端套件曾为 90/91 项通过，未通过项是既有 `configuration-safety.test.mjs` 的策略说明文案断言。此记录不表示真实 Ascend/ModelArts 作业已在本机运行。

## 11. 查看结果与排查问题

训练计划 `training_plan_<model_tag>.json`、模型目录的 `training_record.json` 和 `models_manifest.json` 记录实际训练量、step、模型摘要和运行身份。结果页面会显示已有记录；旧模型无记录时显示“未记录”。

采样数据、各阶段日志及结果写入所配置的 OBS 输出目录；模型和报告也可使用页面指定的独立目录。控制面工作区的 `result/.workflows/` 保存编排记录，需单独备份，代码拉取不能恢复这些记录。

| 问题 | 优先检查 |
| --- | --- |
| 仓库无法克隆 | GitHub 网络连通性、代理和仓库地址 |
| 网页打不开或 502 | 后端进程、端口、Jupyter 代理路径 |
| 输入/评测校验失败 | OBS 与本地映射一致性、挂载权限、字段和任务文件 |
| 401/403 | 网关鉴权方式、Token 有效期、委托和资源权限 |
| 作业长时间排队 | 资源池剩余节点与当前规格 |
| 缺少 lightgbm/rustbpe | 离线 wheel 名称、Python 版本和 CPU 架构 |
| 分布式启动失败 | 节点编号、主节点地址、唯一 run ID、端口与前序 rank 错误 |
| 全局 batch 不可整除 | 按第 9.2 节重新设置；不要通过增大单卡 batch 随意补齐 |
| 某 rank 无数据 | 训练文件行组数、非空行组和采样数据量 |
| 训练成功但评测失败 | 模型 step/校验和、评测 INPUT 挂载、任务依赖与剩余 HBM |
| 结果页未显示报告 | 评测完成状态、OBS 输出同步、控制面结果挂载 |

同作业评测的默认 HBM 释放等待上限为 120 秒，每卡空闲显存阈值为 24576 MiB，可按实际卡型配置 `AMT_EVAL_SETTLE_TIMEOUT` 与 `AMT_EVAL_MIN_FREE_MIB`。超时保留已训练模型并报错；硬件阈值必须在真实环境校准。

## 12. 进一步阅读与来源

- [部署 Wiki](docs/WIKI_DEPLOYMENT.md)：后台启动、离线安装、版本更新和认证细节。
- [用户指南](docs/WIKI_USER_GUIDE.md)：四步表单、批量策略、重试与作业管理。
- [多节点适配说明](docs/SCALING_MODELARTS_NODES.md)：拓扑、代理实验并行、数据和检查点同步。
- [训练 Token 预算](docs/TRAINING_TOKEN_BUDGET.md)：训练量与比较口径。
- [实验记录与验收](docs/WIKI_EXPERIMENTS.md)：输出、分析及故障排查。
- [QuaDMix 算法与早期入口参考](docs/QUADMIX_ALGORITHM_REFERENCE.md)：迁移前 README 的算法、Schema 与历史实现说明。

本项目基于 [AutoDataMixture/Auto-Mixture-Tool](https://github.com/AutoDataMixture/Auto-Mixture-Tool) 的现有实现，继续集成多节点适配和训练验证。QuaDMix 论文参见 [arXiv:2504.16511](https://arxiv.org/abs/2504.16511)。仓库中的 QuaDMix 为论文的个人实现，非论文作者官方代码。许可证声明沿用项目 `pyproject.toml` 的 Apache 2.0；引用与使用各模型、数据集时应遵守其自身许可证。
