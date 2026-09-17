# Auto-Mixture-Tool 使用 Wiki

从下载代码、开发环境部署，到页面配置、ModelArts 作业运行和结果分析。

**适用版本**：以 `d9a3c58` 及本次文档整理时的代码为依据。本文优先说明当前 Web 界面的多策略并行流程，不是早期“两作业”模式。示例路径沿用当前开发环境；更换账户、桶或镜像时必须替换对应配置。

## 目录

1. [先了解完整流程](#1-先了解完整流程)
2. [首次使用需要准备什么](#2-首次使用需要准备什么)
3. [下载代码并安装开发环境](#3-下载代码并安装开发环境)
4. [准备 OBS 数据和运行资源](#4-准备-obs-数据和运行资源)
5. [配置数据挂载与自动认证](#5-配置数据挂载与自动认证)
6. [启动服务并打开界面](#6-启动服务并打开界面)
7. [第一步：配比策略](#7-第一步配比策略)
8. [第二步：训练配置](#8-第二步训练配置)
9. [第三步：评测配置](#9-第三步评测配置)
10. [第四步：任务配置与提交](#10-第四步任务配置与提交)
11. [查看进度、管理作业与阶段重试](#11-查看进度管理作业与阶段重试)
12. [查看模型、报告与结果分析](#12-查看模型报告与结果分析)
13. [日常启动、升级与备份](#13-日常启动升级与备份)
14. [首次验收与扩大实验规模](#14-首次验收与扩大实验规模)
15. [常见问题](#15-常见问题)
16. [进一步阅读与文件索引](#16-进一步阅读与文件索引)

## 1. 先了解完整流程

### 1.1 三个环境各自负责什么

| 位置 | 作用 | 不要混淆的地方 |
| --- | --- | --- |
| 浏览器 | 填写配置、提交实验、查看进度和分析 | 不在浏览器中训练模型 |
| 开发环境 | 运行 FastAPI 后端和 UI；读取挂载数据做检查；提交及监控 ModelArts 作业 | 开发环境的 8 张卡不会因为打开网页就自动参与云端训练 |
| ModelArts 容器 | 按作业运行配比、训练或评测；使用分配给作业的 NPU | Python、安装包、文件路径均与开发环境分开 |
| OBS | 保存输入资源、采样集、模型和报告，负责跨作业交接 | OBS URI 不是容器本地路径，也不是网页链接 |

前置条件：原始 STEM JSON 已在外部数据处理环境（例如 Hadoop）完成过滤、标签提取和 Parquet 转换。本版页面不负责提交 Hadoop 作业。

```text
标准 Parquet 上传 OBS
        ↓
开发环境读取挂载目录，自动抽查格式、预估数据量
        ↓
在 UI 配置策略、训练、评测及云端资源，提交一次实验
        ↓
QuaDMix 配比作业 ──成功──→ 对应训练作业 ──┐
人工配比作业    ──成功──→ 对应训练作业 ──┼─全部训练成功─→ 汇总评测作业
随机配比作业    ──成功──→ 对应训练作业 ──┘                     ↑
                                                可加入历史成功模型
                                                            ↓
                                               OBS 模型、指标、对比报告
                                                            ↓
                                               实验作业 → 结果分析
```

### 1.2 一个实验会创建几个作业

- 每个策略对应 **1 个配比作业 + 1 个训练作业**。
- 启用评测后，再增加 **1 个汇总评测作业**。
- 3 个策略通常规划 7 个作业；7 个策略通常规划 15 个作业。
- 不启用评测时，作业数为 `2 × 策略数`。
- 本次训练模型与选中的历史模型放在同一个汇总评测作业内逐个评测，不会重新训练历史模型。

同一策略的配比成功后即可提交自己的训练，不必等待其他配比完成。实际是否同时运行还取决于资源池容量、配额及排队情况。

## 2. 首次使用需要准备什么

### 2.1 管理员一次性准备

- 可使用 Python 3.11 的 Linux 开发环境、Git，以及能安装依赖的环境或离线安装包。
- 开发环境可读的 OBS 本地挂载。当前约定为 `/l00916525`。
- 可供浏览器访问的服务入口：例如已认证的 JupyterLab 端口代理。
- ModelArts 创建作业 API 地址、工作空间、镜像与镜像仓库编号、规格及资源池编号。
- 私有 IAM 配置，或有权限且有效的手动 Authorization。
- 已上传的工具代码、NanoChat 代码、基础模型、Tokenizer、代理验证集、评测集及离线依赖。
- 作业身份拥有相应 OBS 输入读取、输出写入以及所需节点协调权限。

工具目前没有独立的多用户登录、租户隔离和不可信代码沙箱。仅面向可信内部用户，应放在受保护的网络或已有登录认证的代理后面，不能直接公开到互联网。

### 2.2 每次实验用户需要准备

| 必需信息 | 说明 |
| --- | --- |
| 输入数据 OBS 目录 | 已符合算法要求的 Parquet 分片 |
| 策略及参数 | 可多选、多次添加 QuaDMix、人工或随机策略 |
| 训练配置 | NanoChat 兼容框架、基础模型与标签、Token 预算 |
| 节点与优先级 | 配比、训练和评测各自设置 |
| 输出目录 | 实验输出根目录；可另外指定模型和评测报告目录 |
| 评测选择 | 内置评测项、自定义评测包、可选历史模型 |
| 可选策略脚本 | 可信内部 Python 脚本的 OBS 地址，或本地 `.py` 文件 |

已由管理员配置的默认值通常可以复用，但“已填默认值”不代表当前用户一定拥有访问权限。

## 3. 下载代码并安装开发环境

本章命令在 **开发环境的 JupyterLab Terminal** 中执行，不是在 Windows PowerShell 中执行。以下使用 `/home/ma-user/work/Auto-Mixture-Tool`。

### 3.1 首次下载

```bash
cd /home/ma-user/work
git clone https://github.com/AutoDataMixture/Auto-Mixture-Tool.git
cd Auto-Mixture-Tool
git branch --show-current
git log -1 --oneline
```

预期：目录存在，分支为 `main`，可看到最近提交号。若该目录已经存在，先检查它是不是原工作区，不要直接删除；更新方式见第 13 章。

若开发环境无法访问 GitHub，可在有网络的机器下载或克隆后通过 JupyterLab 上传解压。此时没有 `.git` 的目录不能使用 `git pull`，后续应重新上传同版本发布包。不要把 Token 写到 Git URL 中。

### 3.2 创建 Python 环境

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
python3.11 --version
python3.11 -m venv .venv
source .venv/bin/activate
python --version
python -m pip --version
```

若 `python3.11` 不存在，先确认开发环境实际安装的 Python 路径，再用该 Python 3.11 的绝对路径替换命令。不要认为 ModelArts 镜像安装了 3.11，开发环境就一定也有。

可联网安装时：

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
export PYTHONPATH="$PWD:$PWD/src:${PYTHONPATH:-}"
python -c "import fastapi, uvicorn, requests, yaml, numpy, pandas, pyarrow; print('UI dependencies OK')"
```

预期：最后输出 `UI dependencies OK`。仓库根目录也要加入 `PYTHONPATH`，因为部分运行辅助模块位于 `nanochat_mid_compare/`，不在 `src/` 下。

这里只是在开发环境安装工具，**不会同时给 ModelArts 镜像安装训练依赖**。无需为了运行网页而替换开发环境的 PyTorch/CANN。

### 3.3 无法联网安装时

准备与开发环境 **Python 版本、CPU 架构和操作系统相匹配** 的完整 wheel 目录，包含 `pyproject.toml` 声明的依赖及构建依赖。假设放在 `/home/ma-user/work/ui_wheels/`：

```bash
source /home/ma-user/work/Auto-Mixture-Tool/.venv/bin/activate
cd /home/ma-user/work/Auto-Mixture-Tool
python -m pip install --no-index --find-links=/home/ma-user/work/ui_wheels/ 'setuptools>=68' wheel
python -m pip install --no-index --find-links=/home/ma-user/work/ui_wheels/ --no-build-isolation -e .
export PYTHONPATH="$PWD:$PWD/src:${PYTHONPATH:-}"
python -c "import fastapi, uvicorn, requests, yaml, numpy, pandas, pyarrow; print('UI dependencies OK')"
```

`python_wheels/` 中只有 LightGBM 和 rustbpe 两个文件，不足以保证开发环境可完整离线安装。离线缺包时补齐对应 wheel，不要通过跳过安装来掩盖缺失。

## 4. 准备 OBS 数据和运行资源

### 4.1 地址填写规则

页面填写 `obs://桶名/目录/`，不是 OBS 控制台 HTTPS 链接。例如：

```text
obs://bucket-pangu-green-guangzhou/s00944147/l00916525/chengchao/prepared_parquet_57ffce0ca0a2/
```

目录地址保留末尾 `/`。地址中不要插入空格。策略脚本可填写具体 `.py` 文件；新增评测包填写**包含数据文件的目录地址**。

### 4.2 当前默认资源对照

以下目录来自当前页面默认配置，填写前必须确认 OBS 中实际存在对应文件。

| 资源 | 当前目录（均位于 `obs://bucket-pangu-green-guangzhou/s00944147/l00916525/` 下） | 用途 |
| --- | --- | --- |
| 工具代码 | `Auto-Mixture-Tool/` | 容器运行本工具 |
| 输入数据 | `chengchao/prepared_parquet_57ffce0ca0a2/` | 配比候选数据 |
| NanoChat 代码 | `backup_0810/work/nanochat-npu/` | 训练及评测；不是工具代码目录 |
| NanoChat 基础模型 | `backup_0810/work/nanochat_model_dir/` | 初始权重及其 Tokenizer |
| QuaDMix Tokenizer | `gpt-neox-tokenizer/` | 代理实验分词 |
| 代理验证集 | `AMT_old/data/` | 包含 `stem_v2_tokenized.pt` |
| 内置评测资源 | `eval_bundle/` | CORE/STEM 评测资源 |
| 离线安装包 | `python_wheels/` | 容器启动时安装指定缺失依赖 |
| 实验输出根 | `chengchao/` | 采样数据、阶段输出 |
| 模型输出根 | `chengchao/models/` | 各策略训练后的模型 |
| 评测报告根 | `chengchao/reports/` | CSV、JSON/Markdown 对比报告 |

`backup_0810/work/…` 只是当前默认值。若你的真实资源在其他目录，应填写实际目录，不能仅凭表中示例新建空文件夹。

### 4.3 标准 Parquet 数据

当前 UI 配比入口要求每个 `.parquet` 分片至少包含：

| 字段 | 类型/要求 |
| --- | --- |
| `domain` | 非空领域名称或整数编码；整数含义以对应 schema 为准 |
| `text` | 非空文本字符串 |
| `char_count` | 正整数 |
| `stem_relevance` | 有限数值 |
| `knowledge_value` | 有限数值 |
| `notation_fidelity` | 有限数值 |
| `rigor_coherence` | 有限数值 |
| `noise_level` | 有限数值 |

生成示例见 [quadmix_parquet.py](../examples/datasets/quadmix_parquet.py)。这是格式示例，不是足够训练真实实验的数据集。不要将已经分词的 Token ID 文件冒充文本 Parquet。

### 4.4 模型、Tokenizer 和评测包结构

NanoChat 基础模型目录应有同版本训练代码可以读取的权重、元数据和 Tokenizer，例如：

```text
nanochat_model_dir/
├── base_checkpoints/
│   └── d24/
│       ├── model_XXXXXX.pt
│       └── meta_XXXXXX.json
└── tokenizer/
    ├── tokenizer.pkl
    └── token_bytes.pt
```

`d24` 是基础模型标签，不是 NanoChat 框架本身。模型参数量和结构以 checkpoint 元数据为准。QuaDMix 的 GPT-NeoX Tokenizer 与 NanoChat 模型的 Tokenizer 是两个不同资源，不能互相替代；`stem_v2_tokenized.pt` 则是预分词验证数据，不是 Tokenizer。

内置评测资源推荐按已验收结构上传，保留 `core.yaml` 引用的全部文件：

```text
eval_bundle/
├── core.yaml
├── eval_meta_data.csv
├── eval_data/                 # 含 core.yaml 中引用的 ARC 等数据
└── eval_stem/
    ├── eval_meta_data.csv
    └── eval_data/
        ├── gpqa_diamond.jsonl
        ├── gsm8k.jsonl
        ├── math500.jsonl
        └── mmlu_stem.jsonl
```

实际 NanoChat 版本还可能声明其他任务文件，例如 `mmlu.jsonl`；按所选任务准备，不能用空文件替代。仅有 `eval_stem/` 不能替代外层 `eval_bundle/`。

### 4.5 容器离线安装包和镜像

当前默认 command 面向 Python 3.11 / aarch64 / Ascend 环境，明确使用以下文件名：

```text
python_wheels/
├── lightgbm-4.6.0-py3-none-manylinux2014_aarch64.whl
└── rustbpe-0.1.0-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl
```

其他依赖必须由镜像或配套离线安装过程提供。运行检查涉及 NumPy、Pandas、PyArrow、SciPy、scikit-learn、LightGBM、joblib、matplotlib、tqdm、psutil、Jinja2、PyTorch、torch_npu、Transformers、tokenizers、datasets、tiktoken、filelock、requests、PyYAML。

默认关闭 W&B 在线追踪，使用禁用记录的兼容实现；这不替代模型训练计算。需要 W&B 时必须另行安装和配置真实服务。不要独立升级 `torch`、`torch_npu` 或 CANN，三者需与镜像及硬件适配。

多节点仅有 OBS 时，还需确认容器具有现有同步实现要求的 OBS 访问能力和权限；不能因为输入挂载成功就认定节点间产物同步一定成功。详细检查见 [离线资源说明](OFFLINE_RESOURCES_AND_OPERATIONS.md) 与 [多节点说明](SCALING_MODELARTS_NODES.md)。其中旧流程描述以本 Wiki 为准。

### 4.6 将工具代码上传 OBS

开发环境用于提供网页；OBS 的工具目录供云作业运行。**两份代码必须同步更新。**

建议只从已提交代码制作干净发布包，避免把私有认证和本地记录一起上传：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
RELEASE_ID=$(git rev-parse --short HEAD)
RELEASE_DIR="/home/ma-user/work/amt-release-$RELEASE_ID"
mkdir -p "$RELEASE_DIR"
git archive --format=tar --prefix=Auto-Mixture-Tool/ \
  -o "$RELEASE_DIR/Auto-Mixture-Tool.tar" HEAD
tar -xf "$RELEASE_DIR/Auto-Mixture-Tool.tar" -C "$RELEASE_DIR"
printf '待上传目录：%s/Auto-Mixture-Tool\n' "$RELEASE_DIR"
```

用已有 OBS 上传工具或控制台，将解压目录的**内容**上传到 UI 中的工具代码 OBS 目录。不要只上传 `.tar`，也不要多套一层 `Auto-Mixture-Tool/Auto-Mixture-Tool/`。

上传后该 OBS 目录下应直接看到 `pyproject.toml`、`src/`、`nanochat_mid_compare/`、`scripts/`、`configs/` 等。`git archive HEAD` 不包含未提交修改；如需发布未提交内容，应先经过审核，而不是误以为它已打包。

不要上传 `.venv/`、`private_auth/`、真实 IAM 脚本、Token、个人资料、`result/.workflows/` 或本机日志。共享 OBS 代码目录升级可能影响其他待启动作业，正式实验宜使用独立的版本目录并在 UI 修改代码地址。

## 5. 配置数据挂载与自动认证

### 5.1 确认 OBS 本地挂载

当前约定：

```text
obs://bucket-pangu-green-guangzhou/s00944147/l00916525/ → /l00916525/
```

管理员需先完成实际挂载。下面的环境变量只告诉工具如何映射，不会自动挂载磁盘：

```bash
export AMT_OBS_MOUNT_ROOT=/l00916525
export AMT_OBS_MOUNT_PREFIX=obs://bucket-pangu-green-guangzhou/s00944147/l00916525/
ls -ld /l00916525
ls -ld /l00916525/chengchao/prepared_parquet_57ffce0ca0a2
```

启动后端的用户必须能读取数据、NanoChat 评测定义、评测包和结果报告。当前提交前的数据与评测资源校验要求目录位于配置的本地映射范围；仅填写一个远端 URI，不代表后端已能读取它。

### 5.2 推荐方式：私有 IAM 自动获取 Authorization

只在开发环境保存认证文件，不上传 GitHub 或 OBS：

```bash
mkdir -p /home/ma-user/work/private_auth
chmod 700 /home/ma-user/work/private_auth
cp -n /home/ma-user/work/Auto-Mixture-Tool/iam_token_provider.py \
  /home/ma-user/work/private_auth/iam_token_provider.py
chmod 600 /home/ma-user/work/private_auth/iam_token_provider.py
```

通过 JupyterLab 编辑仓库外的 `/home/ma-user/work/private_auth/iam_token_provider.py`，在 `AUTH_CONFIG` 中填写管理员提供的 `account`、`secret`、`project`、`enterprise`。`modelarts_endpoint` 为可选目标限制；`authorization_prefix` 仅在网关要求时设为 `Bearer `。

也可在该私有文件中粘贴原始 IAM 脚本。工具只解析末尾字面量 `auth = {...}` 配置，不执行原脚本的打印或请求代码。原脚本中的 `verify=False` 不会自动生效。

启动服务前设置：

```bash
export AMT_IAM_PROVIDER=/home/ma-user/work/private_auth/iam_token_provider.py
```

页面 Authorization 应显示“自动获取（提交时执行）”。不需要把 Token 粘到网页里；真正创建每个作业前，后端自动获取并填写请求头。IAM 的取 Token URL 与页面的 ModelArts 创建作业 `url` 是两个不同地址，不能互换。

证书校验默认开启。如使用内部 CA，在私有配置的 `ca_bundle` 中填可信证书路径。关闭校验会带来凭据被截获风险，不是推荐部署方式；已有受控环境确需配置时，区分 `iam_verify_ssl` 与 `modelarts_verify_ssl`，详见 [IAM 配置](IAM_AUTH.md)。

### 5.3 网络与代理

若内部 IAM 和 ModelArts 网关应直连、环境代理反而无法访问，可在**启动后端的同一个终端**配置：

```bash
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost,iam.his-op.huawei.com,csbgw.roma.huawei.com"
export no_proxy="$NO_PROXY"
```

只应对确认可直连的域名这样设置。更改环境变量后要重启后端，正在运行的进程不会自动读取新终端的变量。代理错误、证书错误和鉴权失败是不同问题。

### 5.4 手动 Authorization 方式

不启用自动 IAM 时，在启动终端执行 `unset AMT_IAM_PROVIDER`，再启动服务，在“任务配置”填写有效 Authorization。不要把真实值放进 command、Git、截图或 Wiki。

## 6. 启动服务并打开界面

### 6.1 首次以前台方式启动

在已完成第 5 章环境变量配置的终端中：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
source .venv/bin/activate
export PYTHONPATH="$PWD:$PWD/src:${PYTHONPATH:-}"
python -m auto_mixture_tool.cli --workspace "$PWD" \
  serve --host 0.0.0.0 --port 8080
```

预期日志：`Application startup complete`、`Uvicorn running on http://0.0.0.0:8080`。保持该进程运行。`0.0.0.0` 是监听所有网卡，不是用户应在浏览器中输入的访问地址。

另开终端检查：

```bash
curl --noproxy '*' http://127.0.0.1:8080/api/v1/health
curl --noproxy '*' -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/ui
```

预期分别为健康 JSON、`200`。不要用 `curl -I` 验收，`/ui` 不接受 HEAD 时返回 `405` 并不代表页面故障。

### 6.2 通过 JupyterLab 打开

若当前 JupyterLab 地址为：

```text
https://你的Jupyter域名/你的实例ID/lab
```

且平台已启用端口代理，则浏览器打开：

```text
https://你的Jupyter域名/你的实例ID/proxy/8080/ui
```

保留域名和实例前缀，只替换末尾路径；若端口改为 8094，对应改成 `/proxy/8094/ui`。平台没有启用该代理时，需要管理员提供访问入口。

在自己电脑输入 `http://127.0.0.1:8080/ui` 指向的是自己电脑，不是远程开发环境；`172.16.*` 等内网 IP 也不保证能从本机访问。不要通过双击 `index.html` 代替完整服务。

当前工具没有额外的用户名密码登录页。访问保护应由 Jupyter/网关承担；打开 ModelArts 作业网页则可能需要登录对应云账号。

### 6.3 确认后再改为后台运行

先用 `Ctrl+C` 停止上面的前台服务，避免启动两个后端。保留同一终端中的挂载、IAM、代理环境变量：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
source .venv/bin/activate
export PYTHONPATH="$PWD:$PWD/src:${PYTHONPATH:-}"
mkdir -p result
nohup python -m auto_mixture_tool.cli --workspace "$PWD" \
  serve --host 0.0.0.0 --port 8080 \
  > result/ui-server.log 2>&1 &
echo $! > result/ui-server.pid
tail -n 40 result/ui-server.log
```

后端保持**单进程**运行，不要用多个 Uvicorn worker 共同管理同一个工作区。关闭网页不影响后端调度；关闭开发环境、结束后端或实例休眠则会暂停监控及后续自动提交。`nohup` 不能防止实例被平台回收。

## 7. 第一步：配比策略

### 7.1 创建实验和填写数据

1. 左侧点击“创建配比实验”；若提示重置，确认后会恢复初始默认配置。需要复用旧参数时使用“复制并调整参数”，不要先重置。
2. 填写输入数据 OBS 目录和实验输出根目录。
3. 等待自动校验结束。系统检查每个 Parquet 分片字段和类型，并在每片随机抽查最多 3 条记录。
4. 查看文档数、文件大小、预计 Token 数。校验失败时按具体文件/字段修正，不能提交实验。
5. 同一地址的数据已替换时点击“重新校验”。成功记录有效期为 1 小时，服务重启后需重新校验。

预计 Token 数来自抽样文本长度估算，不是对全部数据进行真实 Tokenizer 分词。提交时复用已通过的校验记录，不再次全量读取输入；抽查通过也不保证每一行都合格。

### 7.2 添加和设置策略

顶部选择策略类型并点击增加，可添加多个相同类型、不同参数的策略。每项都有独立策略 ID，不需要限制为一个 QuaDMix 或一个随机策略。

| 策略 | 用户需要设置 | 基本含义 |
| --- | --- | --- |
| QuaDMix | 代理实验数、步数、搜索次数、参数范围、随机种子 | 用代理实验结果学习配比参数，再生成采样集 |
| 人工配比 | 内置策略或自定义脚本、随机种子 | 使用人工给定的领域比例和对应选样规则 |
| 随机配比 | 内置策略或自定义脚本、随机种子 | 使用随机选样基线 |

点击策略说明可查看采样规则与样例。当前默认人工比例为数学 0.6、物理 0.15、化学 0.125、生物学 0.125；页面不单独展示领域比例输入框，不要把策略名称修改误认为比例已变化。

当前 QuaDMix 默认：**50 个代理实验、每组 15 步、搜索 5000 次、随机种子 42、每节点 8 卡**。15 步主要用于短流程验证，不能代表充分训练的正式实验。代理实验数建议不少于 50，但不是有效性保证。

步数旁的预计 Token 是**单组代理训练消耗**，按当前默认 `步数 × 8 × 2048` 计算，不是最终采样集大小，也不是所有代理实验消耗之和。

#### 批量配置控制变量实验

在任意 QuaDMix 策略卡点击“批量配置”，以该卡作为基准生成多项策略，无需逐项复制填写：

1. 填写代理实验数和步数；一个值保持一致，多个值用逗号分隔。
2. 选择扫描参数（ω、ε、λ、η）和修改方式（搜索上限、搜索下限、固定值）。固定值会把该参数上下限同时设为此值。
3. 填写扫描取值，右侧自动列出全部组合。可取消勾选不需要的组合；重复取值自动合并，范围错误时不能加入。
4. 在“本批次节点配置”中设置配比节点数；训练节点默认跟随统一训练配置，也可选择“本批次单独设置”覆盖为 1～16 节点。这是每个对应作业使用的节点数，不是整批共享总数；评测节点数仍在评测配置页设置。
5. 选择替换当前 QuaDMix 策略或追加保留当前策略，再点击“确认加入”。其他策略不会删除或被修改；这一步仅修改表单，不提交云作业。
6. 按原流程检查训练、评测和任务配置，再统一提交。每项生成策略仍对应独立配比和训练作业，采用原有并发调度。单独设置的训练节点数不会被统一默认值覆盖，也可在训练页恢复统一值；“载入示例”只恢复扫描参数，不重置节点设置。

内置示例：代理实验数 `100, 300, 500`，步数 `5000`，ω 搜索上限 `0.1, 0.15, 0.2, 0.25, 0.3`，生成 **15 项策略、15 个配比作业和 15 个训练作业**，代理实验总数为 **4,500**。示例是组合填写演示，不是计算成本或效果推荐；若只对比一个变量，其余输入各填写一个值。单次最多生成 1000 个组合。

非变化参数沿用当前策略：随机种子、搜索次数、其他参数范围和配比优先级等；训练参数和训练优先级由训练配置页统一控制，训练节点允许批次覆盖。新策略使用独立 ID，清空自定义策略名、作业名和模型名，以便自动命名；命令沿用当前策略，若曾在命令中写死参数，请先调整。创建时间在最终提交时确定。

批量作业数不包含页面上其他保留策略，也不包含汇总评测作业。例如原有人工和随机策略仍保留时，总策略数为 17；开启评测后，实验计划共 35 个云作业。最终数量以任务配置页为准。

### 7.3 参数范围和采样量预估

| 参数 | 默认范围 | 作用 |
| --- | --- | --- |
| `ω` | 0～0.1 | 优先选取的质量排名区域，不是原始质量分上限 |
| `ε` | 0～0.001 | 尾部文本的基础选取率 |
| `λ` | 0～1000 | 选取曲线的陡峭程度 |
| `η` | 0～1 | 优先区域的选取强度指数 |

上下限相同表示固定值。修改范围后，预计采样 Token 数会更新；它依赖数据量和采样函数，不由代理实验数或步数直接相乘得到。最终取决于实际搜索参数和采样结果。

### 7.4 使用自定义策略脚本

人工/随机策略可填写 `.py` 的 OBS URI，或选择/拖拽本地文件。两种来源在同一卡片中显示，但互斥。

- 单文件 UTF-8、最多 32 KiB；一次实验直接上传合计最多 128 KiB。较大文件改用 OBS 地址。
- 样例：[manual_quality_first.py](../examples/strategies/manual_quality_first.py)、[random_length_aware.py](../examples/strategies/random_length_aware.py)。前者实际按估算长度优先，不是默认质量排序策略。
- 接口：`STRATEGY_API_VERSION = "1"`，实现 `select(pool, context, config)`，返回候选池索引。
- 这不是任意 Python 脚本自动适配入口。领域配比与最终预算仍受工具协议约束，具体见 [策略脚本说明](STRATEGY_UPLOAD.md)。

脚本在云端容器执行，仅允许可信代码。工具不替脚本自动安装依赖，也不会保证脚本的业务正确性。

### 7.5 作业名称与节点数

每个配比作业独立设置节点数、优先级和名称。默认 QuaDMix 2 节点，人工/随机 1 节点；当前内置人工和随机选样由首节点处理，增加节点不意味着加速。

名称留空时按参数与提交时间生成，例如 `ex-50-15-0p2-0917-143025`：50 组代理实验、15 步、ω 搜索上限 0.2，9 月 17 日 14:30:25 提交。小数点用 `p` 表示；同秒同参数的自动名称会追加短编号。手动名称保持原样，以英文字母开头，可含字母、数字、`_`、`-`，不超过 64 字符。工具会检查本次及已保留的历史名称，手动名称重名拒绝提交。

## 8. 第二步：训练配置

### 8.1 统一训练设置

当前新建页面全部策略共用训练框架、基础模型、训练参数和训练优先级；统一训练节点数作为默认值，批量策略可单独覆盖。训练作业和模型名称自动生成，command 仍可按作业编辑。

1. 选择内置框架或 OBS 挂载框架，填写 **NanoChat 兼容代码目录**。
2. 填写训练 Token 预算，当前默认 `401395843`。
3. 设置每节点 NPU 数，默认 8。
4. 设置默认训练节点数（默认 2）和训练任务优先级（默认 2）。若有批量策略单独设置节点数，页面会显示数量，展开可逐项恢复统一值；修改默认节点不会覆盖这些例外。
5. 填写 NanoChat 模型 OBS 目录、基础模型标签（默认 `d24`）和模型输出 OBS 根目录。

NanoChat 是训练/评测框架，不是一个固定模型。任意 Hugging Face 模型或任意训练仓库不能只靠填地址就保证兼容。

“上一步 / 下一步”固定在页面右下角，无需滚动到页面末尾。复制旧实验时，不同于原统一节点数的策略保留为单独设置；训练优先级以首项策略为统一初值，可再修改。

每个策略从同一基础模型独立训练，产生不同 checkpoint，不是依次在同一个模型上累积训练。训练步数由 Token 预算和实际每步全局 Token 批量计算；采样集不足时可能循环读取数据。

单卡批量和训练期间验证/评测间隔当前不在新建页面显示，后台默认分别为 `1`、`-1`、`-1`。不要把“隐藏字段”理解为程序没有这些参数。

### 8.2 采样预算与重复使用提示

“目标参数/数据比例”默认 0.5，用于采样数据规模控制，与训练 Token 预算不是同一参数；它不能保证 QuaDMix 最终采样集达到训练预算。

“数据重复使用预判”默认只显示告警数量、最高估算倍数或待校验提示；点击“查看详细说明与各策略预判”，选择策略后查看完整估算和说明。它区分两种情况：

1. QuaDMix 采样时，同一文本本身可能重复入选；并非所有文本固定两倍。
2. 训练预算大于采样集 Token 数时，训练还可能循环读取。

预算除以预计采样量**严格超过 3 倍**时显示红色告警，但允许继续提交。估算已经包含采样函数中的重复入选，不能再统一乘 2；这个倍数不是每个 Token 的实测训练次数。

### 8.3 运行依赖配置

确认代码、QuaDMix Tokenizer、代理验证集、评测资源、离线包的 `name + OBS 地址`。可增加/删除资源，但不要误删默认命令依赖的必需项。修改默认资源显示名称，不会自动改变其内部用途或容器挂载位置。

训练目录使用容器的挂载路径，用户在这里填写的是 OBS 地址；不应手工把所有 command 中的容器本地路径替换为 `obs://…`。

## 9. 第三步：评测配置

### 9.1 选择内置评测项

打开“评测集评测”。默认 STEM 全选，包括：

`arc_easy`、`arc_challenge`、`mmlu_stem`、`gpqa_diamond`、`gsm8k_cot`、`math_cot_500`。

“STEM 全选”是批量选择按钮，可继续取消或增加单项，提交时去重。关闭评测集且不启用任何实际评测方式，则不创建汇总评测任务。

自动评估 API 目前仅有展示配置，尚未接入真实自动评估服务，不应把勾选它当作已经配置好外部评测。

### 9.2 添加自定义 OBS 评测包

切换到 OBS 路径入口，增加评测包名称和目录地址。可同时保留内置任务，也可取消内置任务只评测自定义包。

例如 SuperGPQA 的 JSONL 放在：

```text
obs://你的桶/评测数据/supergpqa/
└── supergpqa.jsonl
```

填写目录 `obs://你的桶/评测数据/supergpqa/`，不是文件 URI。当前可识别 JSON、JSONL、CSV、Parquet 中受支持的题目结构，也可使用原有 NanoChat 评测包。

普通选择题的一条 JSONL 示例：

```json
{"question":"水的化学式是什么？","options":["H2O","CO2"],"answer":"A"}
```

明确协议的包可按 [examples/evaluation/basic](../examples/evaluation/basic/) 组织 `core.yaml`、`eval_meta_data.csv` 和 `eval_data/`。

系统校验题型、字段、答案等，不支持时给出具体原因并阻止提交。生成题需明确评分器；目前支持现有 GSM8K/MATH 答案提取方式，不能自动评测任意开放问答、代码执行或图文任务。无配置自动适配通常使用零样本设置，不代表官方基准协议。

### 9.3 独立评测作业设置

- 评测节点默认 1，每节点 8 卡；可独立于训练节点调整。
- 批量默认 16。批量评分 OOM 时自动按 16→14→…→2→1 重试，保留已完成结果，不跳过题目。1 仍 OOM 则停止。
- 生成类逐题评测、模型加载失败和通信故障不适用该降批量机制。
- 当前 UI 使用全部评测样本，不显示“每项最大样本数”。
- 填写评测作业名、优先级、评测与对比报告输出根目录。

### 9.4 加入历史模型

在“加入历史模型对比”中搜索并勾选训练成功的模型，支持多选和分页。点击“同类型”或“有差异”筛选，展开可看来源实验、配置和保存地址。

相同参数标绿，已知差异标红，缺失或未核验信息标灰。节点数不同不算模型参数差异；两类均可选择。能选中不代表任何模型格式都能加载，仍需兼容当前 NanoChat 评测器。

## 10. 第四步：任务配置与提交

### 10.1 核对作业清单

确认作业总数、名称、节点数、优先级和依赖关系。`max_active_jobs` 默认 8，表示本实验最多同时已提交/排队/运行的作业数，不是节点数。

释放一个名额后就会补交符合依赖的作业，不必等待一整批 8 个全部完成。云状态默认每轮约间隔 15 秒查询，接口耗时另计；页面约每 3 秒刷新的是后端状态。

### 10.2 ModelArts 参数

| 页面参数 | 如何填写 |
| --- | --- |
| `url`（后端字段 `endpoint`） | 完整创建训练作业 API 地址；不是 IAM URL 或控制台详情页 |
| `region` | 与 API、资源池等匹配的区域 |
| `workspace_id` | 工作空间编号 |
| `workspaceName`（后端字段 `workspace_name`） | 控制台链接使用的工作空间名称 |
| `image_url` | 实际训练镜像完整地址 |
| `image_repo_id` | 与镜像匹配的企业镜像仓库编号 |
| `flavor_id` | 所选硬件规格 |
| `pool_id` | 有权限使用的资源池编号 |
| `Authorization` | 自动 IAM 模式无需填；手动模式填写有效凭据 |

默认非敏感参数来自 [modelarts_ui_defaults.json](../configs/modelarts_ui_defaults.json)。换环境时管理员可修改此文件并重启服务，或用户直接编辑页面。不要仅改镜像 URL 而保留不匹配的镜像仓库编号。

### 10.3 每个作业的 command

每个配比、训练、汇总评测作业都有一条完整可编辑的启动命令。默认命令会依据配置生成，通常不需要手动改写。

- command 不能为空；显示“正在加载默认命令”时等待加载完成。
- 手工改过的命令不会被自动覆盖。升级后需要使用新启动流程时，点击该作业恢复默认命令的按钮。
- 改镜像不等于工具能自动适配任意 Python/CANN 环境，应检查实际解释器和依赖。
- 不要把 Token、secret 写进命令。

页面提交不要求再运行 `modelarts_training_job.py`。脚本是另一条提交入口，同时执行会重复起作业。

### 10.4 提交并确认受理

1. 点击“检查配置（不创建作业）”，处理所有校验提示。
2. 确认输入校验通过、资源和输出地址正确、作业数量与资源消耗符合预期。
3. 点击“提交到 ModelArts”。这会创建真实云作业并可能产生费用。
4. 到“实验作业”查看记录；取得实际作业编号后，详情提供 ModelArts 网页链接。

如果返回超时、非 JSON、连接失败或“待人工核对”，**不要连续重复提交**。先到实验记录和 ModelArts 控制台核对是否已创建。作业已受理、正在排队、正在运行、运行成功是不同状态。

## 11. 查看进度、管理作业与阶段重试

### 11.1 实验作业管理

- 列表按创建时间倒序，最新在上。
- 可按作业名片段搜索，通过状态按钮筛选，每页显示 5 条。
- 打开详情，横向策略分支显示配比→训练→汇总评测的阶段进度。
- 进度表示已知作业阶段，不是所有训练 step 的实时完成百分比。
- 查看各作业 ModelArts 链接、失败信息、输入/输出地址。
- “复制并调整参数”创建新的配置草稿，不会自动复用旧采样；需要原地复用前序输出时使用阶段重试。

### 11.2 失败后从指定阶段重试

实验结束并满足重试条件后，在详情中点击对应阶段重试按钮，直接打开配置弹窗，不跳到创建向导。

| 重试入口 | 复用内容 | 新建内容 |
| --- | --- | --- |
| 配比阶段重试 | 其他已成功模型按依赖规则复用 | 当前策略配比、对应训练及依赖评测 |
| 训练阶段重试 | 原配比成功输出的同一 OBS 采样集 | 当前训练及依赖评测 |
| 评测阶段重试 | 原成功训练模型及对应 Tokenizer | 评测作业 |

弹窗可调整节点、优先级、预算或评测批量、代码/运行资源地址、输出地址及 command。前序输入地址只读，避免误换来源。再次确认后才提交，新输出使用新的实验目录，不覆盖旧结果。

更换基础模型或 Tokenizer 可能改变采样/分词条件，不属于普通训练重试；应新建实验。若另一个必需训练仍失败，汇总评测依然不会开始。

内存不足自动降批量是**一次正在运行的评测内部重试**；这里的阶段重试是**修复后创建一个新的云作业**，两者不同。

### 11.3 删除实验

删除前有确认。已知正在运行的云作业会请求终止；没有实际提交的条目无需终止。提交结果不明确、拿不到云作业 ID 时，必须先人工核对，不能凭界面删除就认为云端一定停止。

删除实验记录不等于删除 OBS 数据、模型或报告。OBS 文件按团队的数据保留规则另行管理，不要误删仍被历史模型或重试任务引用的产物。

## 12. 查看模型、报告与结果分析

### 12.1 去哪里找输出

以作业详情中的最终地址为准，工具会追加实验名称/时间/唯一标识，避免不同实验覆盖。

```text
实验输出根/runs/<实验名>/
└── strategies/<策略ID>/
    ├── mixing/                  # 配比相关结果
    ├── sampled/data/            # 训练用 Parquet 分片、dataset_stats.json 等
    ├── sampled/experiment.log
    └── training/results/        # 训练日志

模型输出根/runs/<实验名>/<策略ID>/
├── <模型标签>/model_XXXXXX.pt
├── <模型标签>/meta_XXXXXX.json
└── models_manifest.json

评测报告根/runs/<实验名>/
├── comparison_report.json
├── comparison_report.md
├── <模型ID>.csv
└── <模型ID>_adaptive_batch.jsonl
```

以上展示显式填写模型、报告根目录时的典型结构；留空则沿用实验输出约定。同时有多个评测包时，报告位于 `builtin/`、`package_0/`、`package_1/` 等子目录。

`model_XXXXXX.pt` 是模型 checkpoint，`meta_XXXXXX.json` 记录相应元数据；最终评测按模型清单指定的 checkpoint 读取，不是任意选择第 1 步。

### 12.2 在页面分析结果

1. 在实验列表或详情点击“结果分析”。
2. 工具自动从此实验的报告地址读取 `comparison_report.json`，无需再次提交计算作业。
3. 顶部查看共同评测项平均正确率最高的模型及已记录配置。
4. 查看平均正确率、各项对比图、逐项得分、采样量和配比；最优值及并列最优以红色标记。
5. 阅读可比性提示；预算、模型等不同不能直接归因为配比策略的收益。

正确率显示为百分比，差值为百分点；Centered/官方汇总分不是同一个指标。页面平均正确率对共同有效评测项等权平均，不把缺失项补零，也不冒充官方综合分数。

报告尚未同步时先等待，再点击刷新。训练完成但未运行评测，不会有评测对比图。分析说明由规则生成，不调用外部大模型，不提供未经实验支持的显著性结论。

## 13. 日常启动、升级与备份

### 13.1 日常启动

已完成安装和资源准备时，只需激活环境、设置本终端的挂载/IAM/代理变量、启动第 6 章服务。无需每天重新安装包、重新上传模型或重新运行提交脚本。

自动 IAM 模式的日常前台启动命令如下；仅在确认没有另一个后端运行时执行：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
source .venv/bin/activate
export PYTHONPATH="$PWD:$PWD/src:${PYTHONPATH:-}"
export AMT_OBS_MOUNT_ROOT=/l00916525
export AMT_OBS_MOUNT_PREFIX=obs://bucket-pangu-green-guangzhou/s00944147/l00916525/
export AMT_IAM_PROVIDER=/home/ma-user/work/private_auth/iam_token_provider.py
# 如内部网关需要直连，再按第 5.3 节设置 NO_PROXY。
python -m auto_mixture_tool.cli --workspace "$PWD" serve --host 0.0.0.0 --port 8080
```

### 13.2 更新代码

先确认当前后端进程及运行中的实验，安排维护窗口。停止后台服务前核对 PID 确实属于本工具；不要使用批量杀死所有 Python 的命令。

前台启动的服务在原终端按 `Ctrl+C` 停止。按第 6.3 节后台启动时，可先执行以下只读检查：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
cat result/ui-server.pid
ps -p "$(cat result/ui-server.pid)" -o pid,user,args
```

确认输出是本工作区的 `auto_mixture_tool.cli ... serve` 后，使用 `kill -TERM` 加上刚确认的 PID 停止该进程。PID 文件可能过期，不要省略核对。停止服务本身不会自动终止已在云端运行的训练。

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
git status --short
git pull --ff-only origin main
git log -1 --oneline
```

有本地修改导致无法拉取时，先备份和核对，不要直接强制覆盖或删除整个仓库。升级后：

1. 按第 4.6 节同步相同版本工具代码到 OBS，必要时使用新的版本目录。
2. 重新启动开发环境后端，再刷新浏览器；仍显示旧页面时强制刷新。
3. 复制旧实验或重试时，检查是否保留了旧的自定义 command，按需恢复默认命令。
4. 正在运行的云容器不会因为 `git pull` 自动更新，新版本通过新作业生效。

仓库已包含构建后的前端，普通部署无需 Node.js。仅修改 Vue 源码的维护人员需要执行：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool/ui_demo
npm ci
npm run build
```

### 13.3 必须保留的记录

开发环境 `result/.workflows/` 保存实验、模型索引及调度恢复所需记录。删除整个工具目录重新克隆前，务必先停服务并备份此目录；它不属于 GitHub 代码。

私有认证保存在仓库外，单独按敏感配置备份和管理。不要把实验配置/策略脚本当作可以公开上传的无敏感数据。后端重启可恢复已知作业监控，但提交结果不确定的情况仍需人工核对。

## 14. 首次验收与扩大实验规模

### 14.1 第一次只验证链路

建议先用一个策略、较小但有效的数据集、较小训练预算及少量评测项验证。保留当前生产配置另建实验，不要为测试覆盖生产参数或原输出。

- 快速验证调度可先选择内置随机策略，避免等待 QuaDMix 代理搜索。
- 需要验证 QuaDMix 时可先使用短代理步数；短流程结果不用于判断策略优劣。
- 训练预算需与模型序列长度、全局 Token 批量相容，过小预算可能在步数取整后只有很少步；实际消耗以日志为准。
- 自定义小型评测包应包含有效题目和答案，不能用空包跳过评测。

### 14.2 判定真正跑通

- [ ] 浏览器能打开页面，健康接口成功。
- [ ] 自动数据校验通过，预计数据量显示正常。
- [ ] IAM/手动认证有效，取得真实 ModelArts 作业 ID。
- [ ] 配比成功，生成采样分片和统计。
- [ ] 对应训练自动提交，生成模型和 `models_manifest.json`。
- [ ] 评测自动提交，生成 CSV 和对比报告。
- [ ] “结果分析”能读取并展示真实模型结果。
- [ ] 失败时能看到原因，阶段重试可复用正确的前序输出。

仅“提交成功”或只看到 Parquet 文件，不算完成全链路。

### 14.3 从 2 节点切换到更多节点

在页面分别修改需要扩容的配比、训练或评测作业节点数，支持设置 1～16；不需要为每种节点数改一份 Python 源码。每节点 8 卡时，2 节点为 16 卡，4 节点为 32 卡。

同时检查资源池规格/配额、镜像、HCCL 网络、所有节点的数据/模型可见性、OBS 同步权限与全局训练批量。增大节点数不保证线性加速；人工/随机采样、多策略并发和汇总评测也有各自瓶颈。

**验证边界**：已有本地测试覆盖编排和 OOM 回退逻辑，但不等同于任意镜像、任意节点数都通过 NPU 真机测试。当前自动降批量的真实 HCCL 场景仍需在目标环境验收。

## 15. 常见问题

| 现象 | 优先检查与处理 |
| --- | --- |
| `.venv/bin/activate` 不存在 | 先按第 3 章创建虚拟环境，或使用管理员提供的已安装依赖环境 |
| `auto-mixture: command not found` | 激活正确环境；使用本文 `python -m auto_mixture_tool.cli` 启动并设置 `PYTHONPATH` |
| 旧 pip 报 editable 安装需要 setup.py | 当前项目使用 pyproject；在服务虚拟环境升级 pip/setuptools，勿添加空 setup.py 掩盖问题 |
| 本地健康 200，但电脑无法访问内网 IP | 使用 Jupyter 代理入口；确认平台开放端口访问 |
| `curl -I` 返回 405 | 使用 GET 检查；405 不等于服务未启动 |
| 页面接口返回非 JSON/HTTP 504 | 查后端日志、代理超时、Jupyter 会话；先核对是否已创建作业再重试 |
| 输入无法校验、提示挂载目录不存在 | 确认 `/l00916525` 实际挂载、映射前缀正确、服务用户可读 |
| 校验后仍不能提交 | 检查是否过期、更换地址、重启后端；重新校验，并查看评测包的独立错误 |
| IAM 获取失败 | 区分网络、代理、CA、认证参数；私有文件路径与环境变量正确，修改后重启 |
| `ProxyError` 指向 CSB 网关 | 仅给 IAM 配 NO_PROXY 不够；按网络实际情况同时检查 ModelArts 网关 |
| `CERTIFICATE_VERIFY_FAILED` | 配置可信内部 CA；不建议用关闭验证作为默认解决方案 |
| `image_repo_id/image_url` 错误 | 两者须匹配且作业身份有镜像访问权限 |
| OBS `object not found` | 查完整前缀、目录末尾 `/`、嵌套层数及作业身份权限；URI 看起来正确不代表可访问 |
| `command` 为空 | 等待默认命令加载或恢复该作业默认命令，查看默认值接口/后端是否失败 |
| 提交后很久没训练 | 区分配比未成功、云端排队、并发名额限制、前序失败和后端未运行 |
| 缺少 lightgbm/rustbpe | 查默认命令使用的 wheel 文件名、版本、架构和实际挂载目录 |
| 修改了代码仍报旧错误 | 同时更新开发环境与 OBS 代码；旧作业不会热更新；检查旧自定义 command |
| 评测不支持数据格式 | 查看具体文件、字段、答案/题型错误，按样例补任务协议；不是所有 JSONL 都可直接评分 |
| 评测批量 1 仍 OOM | 检查长题、多选项、模型大小和剩余内存；自动降批量不能保证解决所有 OOM |
| HCCL 超时或通信错误 | 检查前面是否有 rank 失败、网络和运行环境；不要一律归因于批量 |
| 训练成功却没有评测 | 查看其他必需训练是否失败、是否启用实际评测、后端是否仍在调度 |
| 结果分析暂无报告 | 查评测是否成功、OBS 是否同步、报告挂载/读取权限和格式 |
| 历史实验消失 | 检查是否更换工作区或删除了 `result/.workflows/`；Git 拉取不恢复本地运行记录 |

排查时保留实验 ID、作业 ID、完整错误栈、实际版本和失败前日志；不要公开 Authorization、secret 或带凭据的完整请求。

## 16. 进一步阅读与文件索引

| 文件 | 用途 |
| --- | --- |
| [UI_VALIDATION_AND_CONFIGURATION.md](UI_VALIDATION_AND_CONFIGURATION.md) | 当前数据抽查、采样估算、统一训练、评测适配和 OOM 回退 |
| [IAM_AUTH.md](IAM_AUTH.md) | 私有 IAM 文件、CA、代理和认证模式 |
| [STRATEGY_UPLOAD.md](STRATEGY_UPLOAD.md) | 策略脚本接口、大小限制和可信代码边界 |
| [PARALLEL_STRATEGY_JOBS.md](PARALLEL_STRATEGY_JOBS.md) | 并行策略调度、输入输出与阶段复用；旧 UI 参数布局以本 Wiki 为准 |
| [MODEL_COMPARISON.md](MODEL_COMPARISON.md) | 历史模型识别、对比和模型身份清单 |
| [RESULT_ANALYSIS.md](RESULT_ANALYSIS.md) | 结果读取、指标口径与解读边界 |
| [modelarts_ui_defaults.json](../configs/modelarts_ui_defaults.json) | 非敏感 ModelArts 默认参数 |
| [iam_token_provider.py](../iam_token_provider.py) | 仅含占位符的私有配置模板 |
| [quadmix_parquet.py](../examples/datasets/quadmix_parquet.py) | 配比输入数据格式示例 |
| [examples/strategies](../examples/strategies/) | 人工与随机策略脚本示例 |
| [examples/evaluation/basic](../examples/evaluation/basic/) | 自定义评测包示例 |
| [modelarts_runtime_check.py](../scripts/modelarts_runtime_check.py) | 容器依赖预检入口，不是 UI 服务启动命令 |

页面默认值、资源文件和镜像属于不同层次的配置。实际部署应记录工具提交号、NanoChat 版本、镜像地址、数据/模型版本及依赖清单，以便复现和定位问题。不要把本 Wiki 当作真实 OBS 对象或云端权限已经验收的证明。
