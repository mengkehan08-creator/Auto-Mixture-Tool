<a id="deployment"></a>

# 工具部署

[Wiki 首页](WIKI.md) · **工具部署** · [用户说明](WIKI_USER_GUIDE.md) · [工具设计](WIKI_DESIGN.md) · [实验结果与记录](WIKI_EXPERIMENTS.md)

适用：当前 Web 多策略实验流程。具体运行结果以实际作业、日志与报告为准。

部署成功的标准是：开发环境服务可访问、输入与评测资源可读取、云端运行资源齐备。此阶段不要求立即启动大规模训练。

## 1.1 部署前置条件与安全边界

- 可使用 Python 3.11 的 Linux 开发环境、Git，以及能安装依赖的环境或离线安装包。
- 开发环境可读的 OBS 本地挂载。当前约定为 `/l00916525`。
- 可供浏览器访问的服务入口：例如已认证的 JupyterLab 端口代理。
- ModelArts 创建作业 API 地址、工作空间、镜像与镜像仓库编号、规格及资源池编号。
- 私有 IAM 配置，或有权限且有效的手动 Authorization。
- 已上传的工具代码、NanoChat 代码、基础模型、Tokenizer、代理验证集、评测集及离线依赖。
- 作业身份拥有相应 OBS 输入读取、输出写入以及所需节点协调权限。

工具目前没有独立的多用户登录、租户隔离和不可信代码沙箱。仅面向可信内部用户，应放在受保护的网络或已有登录认证的代理后面，不能直接公开到互联网。

<a id="deploy-install"></a>

## 1.2 下载代码并安装开发环境

本章命令在 **开发环境的 JupyterLab Terminal** 中执行，不是在 Windows PowerShell 中执行。以下使用 `/home/ma-user/work/Auto-Mixture-Tool`。

### 1.2.1 首次下载

```bash
cd /home/ma-user/work
git clone https://github.com/AutoDataMixture/Auto-Mixture-Tool.git
cd Auto-Mixture-Tool
git branch --show-current
git log -1 --oneline
```

预期：目录存在，分支为 `main`，可看到最近提交号。若该目录已经存在，先检查它是不是原工作区，不要直接删除；更新方式见第 1.6 节。

若开发环境无法访问 GitHub，可在有网络的机器下载或克隆后通过 JupyterLab 上传解压。此时没有 `.git` 的目录不能使用 `git pull`，后续应重新上传同版本发布包。不要把 Token 写到 Git URL 中。

### 1.2.2 创建 Python 环境

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

### 1.2.3 无法联网安装时

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

<a id="deploy-resources"></a>

## 1.3 准备 OBS 数据和运行资源

### 1.3.1 地址填写规则

页面填写 `obs://桶名/目录/`，不是 OBS 控制台 HTTPS 链接。例如：

```text
obs://bucket-pangu-green-guangzhou/s00944147/l00916525/chengchao/prepared_parquet_57ffce0ca0a2/
```

目录地址保留末尾 `/`。地址中不要插入空格。策略脚本可填写具体 `.py` 文件；新增评测包填写**包含数据文件的目录地址**。

### 1.3.2 当前默认资源对照

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

### 1.3.3 标准 Parquet 数据

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

### 1.3.4 模型、Tokenizer 和评测包结构

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

### 1.3.5 容器离线安装包和镜像

当前默认 command 面向 Python 3.11 / aarch64 / Ascend 环境，明确使用以下文件名：

```text
python_wheels/
├── lightgbm-4.6.0-py3-none-manylinux2014_aarch64.whl
└── rustbpe-0.1.0-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl
```

其他依赖必须由镜像或配套离线安装过程提供。运行检查涉及 NumPy、Pandas、PyArrow、SciPy、scikit-learn、LightGBM、joblib、matplotlib、tqdm、psutil、Jinja2、PyTorch、torch_npu、Transformers、tokenizers、datasets、tiktoken、filelock、requests、PyYAML。

默认关闭 W&B 在线追踪，使用禁用记录的兼容实现；这不替代模型训练计算。需要 W&B 时必须另行安装和配置真实服务。不要独立升级 `torch`、`torch_npu` 或 CANN，三者需与镜像及硬件适配。

多节点仅有 OBS 时，还需确认容器具有现有同步实现要求的 OBS 访问能力和权限；不能因为输入挂载成功就认定节点间产物同步一定成功。详细检查见 [离线资源说明](OFFLINE_RESOURCES_AND_OPERATIONS.md) 与 [多节点说明](SCALING_MODELARTS_NODES.md)。其中旧流程描述以本 Wiki 为准。

### 1.3.6 将工具代码上传 OBS

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

<a id="deploy-auth"></a>

## 1.4 配置数据挂载与自动认证

### 1.4.1 确认 OBS 本地挂载

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

### 1.4.2 推荐方式：私有 IAM 自动获取 Authorization

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

### 1.4.3 网络与代理

若内部 IAM 和 ModelArts 网关应直连、环境代理反而无法访问，可在**启动后端的同一个终端**配置：

```bash
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost,iam.his-op.huawei.com,csbgw.roma.huawei.com"
export no_proxy="$NO_PROXY"
```

只应对确认可直连的域名这样设置。更改环境变量后要重启后端，正在运行的进程不会自动读取新终端的变量。代理错误、证书错误和鉴权失败是不同问题。

### 1.4.4 手动 Authorization 方式

不启用自动 IAM 时，在启动终端执行 `unset AMT_IAM_PROVIDER`，再启动服务，在“任务配置”填写有效 Authorization。不要把真实值放进 command、Git、截图或 Wiki。

<a id="deploy-start"></a>

## 1.5 启动服务并打开界面

### 1.5.1 首次以前台方式启动

在已完成第 1.4 节环境变量配置的终端中：

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

### 1.5.2 通过 JupyterLab 打开

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

### 1.5.3 确认后再改为后台运行

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

<a id="deploy-maintenance"></a>

## 1.6 日常启动与版本升级

### 1.6.1 日常启动

已完成安装和资源准备时，只需激活环境、设置本终端的挂载/IAM/代理变量、启动第 1.5 节服务。无需每天重新安装包、重新上传模型或重新运行提交脚本。

自动 IAM 模式的日常前台启动命令如下；仅在确认没有另一个后端运行时执行：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
source .venv/bin/activate
export PYTHONPATH="$PWD:$PWD/src:${PYTHONPATH:-}"
export AMT_OBS_MOUNT_ROOT=/l00916525
export AMT_OBS_MOUNT_PREFIX=obs://bucket-pangu-green-guangzhou/s00944147/l00916525/
export AMT_IAM_PROVIDER=/home/ma-user/work/private_auth/iam_token_provider.py
# 仅在已确认以下内部域名应直连时启用；保留原有 NO_PROXY。
export NO_PROXY="${NO_PROXY:+$NO_PROXY,}iam.his-op.huawei.com,csbgw.roma.huawei.com,127.0.0.1,localhost"
export no_proxy="$NO_PROXY"
python -m auto_mixture_tool.cli --workspace "$PWD" serve --host 0.0.0.0 --port 8080
```

### 1.6.2 更新代码

先确认当前后端进程及运行中的实验，安排维护窗口。停止后台服务前核对 PID 确实属于本工具；不要使用批量杀死所有 Python 的命令。

前台启动的服务在原终端按 `Ctrl+C` 停止。按第 1.5.3 节后台启动时，可先执行以下只读检查：

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

1. 按第 1.3.6 节同步相同版本工具代码到 OBS，必要时使用新的版本目录。
2. 重新启动开发环境后端，再刷新浏览器；仍显示旧页面时强制刷新。
3. 复制旧实验或重试时，检查是否保留了旧的自定义 command，按需恢复默认命令。
4. 正在运行的云容器不会因为 `git pull` 自动更新，新版本通过新作业生效。

仓库已包含构建后的前端，普通部署无需 Node.js。仅修改 Vue 源码的维护人员需要执行：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool/ui_demo
npm ci
npm run build
```


运行记录的备份与保留要求见 [4.4 记录备份](WIKI_EXPERIMENTS.md#record-backup)。升级前先备份，开发环境与 OBS 作业代码保持同一发布版本。
