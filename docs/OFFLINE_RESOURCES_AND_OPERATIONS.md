# 离线资源清单、用户提交材料与系统使用手册

核对日期：2026-09-07。依据当前 Auto-Mixture-Tool 源码、UI 两作业入口、本机 NanoChat 源码，以及用户补充的实际 base_eval.py。

## 1. 先明确本手册的适用范围

当前目标流程是：

```text
用户/Hadoop 事先生成标准 Parquet 并上传 OBS
  → 开发环境上的 UI/API 配置实验
  → ModelArts 配比作业：校验、QuaDMix、各策略采样
  → 前序成功后自动提交 ModelArts 训练评测作业
  → 依次训练各采样集、评测、输出 OBS
```

- 开发环境的 8 张卡不必用于远程作业计算；它可以只运行 UI/API 控制服务。
- 当前 UI 两作业入口接收已经准备好的 Parquet，不会自动调用 Hadoop 处理原始 JSON。
- “离线”指计算作业不依赖公共互联网下载；仍需访问 ModelArts API、OBS、镜像仓库，以及节点间通信。
- 本手册只整理资源和操作，没有修复上一轮审查发现的程序问题；发布文档不代表程序整改已完成。
- 当前不能承诺上传齐资源后整条链路一定跑通。人工采样清单跨作业路径、解释器不统一、多节点模型可见性、数据分片分配等问题仍需修复和验收。
- 用户已提供实际 base_eval.py，STEM 资源文件名和来源已据此补齐；其他 NanoChat 文件和目标镜像的精确版本仍需固定。

## 2. 系统管理员需要一次性准备的资源

| 资源 | 上传内容 | 来源/处理方式 | 是否每次重新下载 |
|---|---|---|---|
| 工具代码 | 完整 Auto-Mixture-Tool：src、scripts、configs、nanochat_mid_compare 和静态 UI | 使用同一个已验证代码版本，开发机与 OBS 保持一致 | 代码更新才重新上传 |
| NanoChat 框架 | 完整、兼容当前启动接口的 nanochat-npu 代码 | 使用你实际在用的 NPU 适配版本，不随意换成上游最新版 | 框架更新才上传 |
| NanoChat 初始模型 | base_checkpoints/d24 中同一步数的模型和元数据 | 复制你已有 nanochat_model_dir 的配套文件 | 模型更新才上传 |
| NanoChat tokenizer | tokenizer/tokenizer.pkl、tokenizer/token_bytes.pt | 与初始模型配套，两个文件一起复制 | tokenizer 更新才上传 |
| QuaDMix tokenizer | GPT-NeoX tokenizer 的完整导出目录，尤其 tokenizer.json | 你已上传的 gpt-neox-tokenizer 可以复用；不需要 GPT-NeoX 20B 模型权重 | 不必重复 |
| QuaDMix 代理验证集 | proxy_validation/stem_v2_tokenized.pt | 优先复制现有已验证文件；也可从代码指定的来源下载 | 不必重复 |
| 离线评测资源 | 实际 NanoChat 版本所需的 CORE/STEM 配置、数据和辅助文件 | 你已上传的 eval_bundle 需核对内容，不是只检查文件夹存在 | 评测内容更新才上传 |
| Python 离线包 | 控制端依赖、计算端缺失包及其全部传递依赖 | 在匹配目标平台的环境中准备，固定版本 | 镜像/依赖更新才准备 |
| OBS 访问工具 | 镜像内可用的 moxing，或可执行的 obsutil | 由平台管理员提供匹配镜像的组件和 OBS 权限 | 镜像已有则无需上传 |
| 可选 tokenizer 缓存 | 实际 tokenizer 加载时需要的 tiktoken 缓存 | 仅当 tokenizer 按注册名称恢复编码且需要外部词表时准备 | 条件需要 |

输入训练数据属于实验资产，见第 6 节；第一个作业生成的 sampled 采样集不需要用户提前下载或上传。

### 2.1 三种容易混淆的资源

- gpt-neox-tokenizer：QuaDMix 代理实验使用的分词器。
- nanochat_model_dir/tokenizer：NanoChat 初始模型配套的分词器与 token 字节长度表。
- stem_v2_tokenized.pt：已经分词的代理验证数据，不是分词器，也不是最终训练模型。

不能用其中一个代替另外两个。NanoChat 是训练框架；当前默认初始模型由 base_model_tag=d24 指定，实际参数量与结构应读取该 checkpoint 的元数据，不能只按名字推断。

### 2.2 NanoChat 模型目录最低要求

```text
nanochat_model_dir/
├── base_checkpoints/
│   └── d24/
│       ├── model_<step>.pt
│       └── meta_<step>.json
└── tokenizer/
    ├── tokenizer.pkl
    └── token_bytes.pt
```

- model 与 meta 必须是同一步数且相互匹配；目录中不要混入缺少对应 meta 的更高步数模型。
- token_bytes.pt 必须与 tokenizer.pkl 的词表匹配，不能随便拿另一个模型的文件。
- 当前两作业入口设置 NANOCHAT_LOAD_OPTIMIZER=0，因此仅加载初始模型时不要求上传 optimizer 分片。
- 若恢复优化器，则另需匹配世界大小/分片方式的 optim_<step>_rank*.pt，不能因节点数改变就认为旧优化器分片仍可用。
- 不要求预先准备未来训练输出的 mid_checkpoints；模型输出目录应是可写的新目录。

## 3. 在联网准备机下载，再上传 OBS

以下下载操作在可联网的准备机执行，不在长时间训练作业启动后临时执行。本次整理没有实际下载大文件。

### 3.1 QuaDMix tokenizer

你已提供的 OBS 地址可以继续使用：

```text
obs://bucket-pangu-green-guangzhou/s00944147/l00916525/gpt-neox-tokenizer/
```

若内容不完整，在联网 Windows PowerShell 中执行：

```powershell
python -m pip install --upgrade huggingface_hub packaging
hf download EleutherAI/gpt-neox-20b --include "tokenizer*" "special_tokens_map.json" "vocab.json" "merges.txt" "added_tokens.json" "config.json" --local-dir ./offline_assets/gpt-neox-tokenizer
```

只下载 tokenizer 相关文件，不下载 *.safetensors 或模型权重。保留实际下载到的完整 tokenizer 目录；至少检查 tokenizer.json 和 tokenizer_config.json。首次准备后记录上游 revision，后续用 --revision 固定版本。

命令依据 [Hugging Face CLI 下载文档](https://huggingface.co/docs/huggingface_hub/guides/cli)；文件来源为 [EleutherAI/gpt-neox-20b](https://huggingface.co/EleutherAI/gpt-neox-20b/tree/main)。若本机 hf 命令缺 packaging，应在准备机修复下载工具，不要把这个问题带入训练镜像。

### 3.2 代理验证集

代码中记录的来源为 liujin99/quadmix-stem-v2，文件名为 stem_v2_tokenized.pt。已有配套文件时优先复用。

```powershell
hf download liujin99/quadmix-stem-v2 stem_v2_tokenized.pt --repo-type dataset --local-dir ./offline_assets/proxy_validation
Get-FileHash ./offline_assets/proxy_validation/stem_v2_tokenized.pt -Algorithm SHA256
```

当前仓库 src/quadmix/constants.py 对这个版本记录的 SHA256 是：

```text
aa9f86d137446e44942ddcd5d833246d5b435f35096b35a3e35a7fe085aafca6
```

这里的来源取自代码，本次没有验证该仓库的大文件能否下载。若不可访问，使用你已有的同版本文件；若是自己生成的新版验证集，应显式记录新版本和校验值，而非忽略不匹配。

无需在集群重新执行 prepare_stem_v2.py。重新制作验证集才涉及 GSM8K、MMLU、ARC、GPQA、MATH 等上游数据，部分来源可能需要权限。

### 3.3 离线评测包

你已上传：

```text
obs://bucket-pangu-green-guangzhou/s00944147/l00916525/eval_bundle/
```

根据你补充的实际 base_eval.py，即使只选择 stem，也仍需 CORE 包：它会读取 core.yaml，ARC-Easy/ARC-Challenge 从 CORE 数据中选取。除此之外，还需要 eval_stem 包。

推荐将以下已解压文件树上传到你现有的 OBS eval_bundle/ 目录：

```text
eval_bundle/
├── core.yaml
├── eval_meta_data.csv
├── eval_data/
│   └── core.yaml 引用的全部文件与子目录，包括 ARC 数据
└── eval_stem/
    ├── eval_meta_data.csv       # 原包有此文件时保留，用于相应任务的随机基线
    └── eval_data/
        ├── gpqa_diamond.jsonl
        ├── gsm8k.jsonl
        ├── math500.jsonl
        ├── mmlu.jsonl
        └── mmlu_stem.jsonl
```

实际脚本指定的两个下载来源，均在联网 Windows 准备机操作：

```powershell
curl.exe --fail --location "https://karpathy-public.s3.us-west-2.amazonaws.com/eval_bundle.zip" --output ./eval_bundle.zip
Expand-Archive -LiteralPath ./eval_bundle.zip -DestinationPath ./offline_eval
hf download liujin99/nanochat-npu-stem-eval eval_stem.zip --repo-type dataset --local-dir ./stem_download
Expand-Archive -LiteralPath ./stem_download/eval_stem.zip -DestinationPath ./offline_stem
```

下载地址来自你提供的代码，本次没有实际下载或验证远端文件是否可访问；需要权限时在联网准备机取得授权，不要绕过访问限制。

组装方法：以 offline_eval/eval_bundle 为最终评测目录，将 offline_stem/eval_stem 整个子目录复制到其中，再上传这一层的内容。不要嵌套成 eval_bundle/eval_bundle，也不要把两个 eval_data 混到一起覆盖。

当前 shell 将挂载根链接为运行时 eval_bundle，并通过 prepare_offline_eval_bundle.py 将其中的 eval_stem 子目录链接为运行时同级 eval_stem。因此上述结构同时满足：

```text
NANOCHAT_BASE_DIR/eval_bundle/core.yaml
NANOCHAT_BASE_DIR/eval_stem/eval_data/gsm8k.jsonl
```

仅上传解压后的文件树，不要同时保留原 ZIP。当前解压器会扫描所有 ZIP，可能沿已经建立的软链接写回输入挂载；预先解压可避免只读挂载错误。

#### 实际评测项与文件的对应关系

| 参数标签 | 数据来源 | 默认 stem 是否包含 |
|---|---|---|
| arc_easy | core.yaml 中同名任务的 dataset_uri，位于 CORE eval_data 下 | 是，前提是 core.yaml 确实包含该标签 |
| arc_challenge | core.yaml 中同名任务的 dataset_uri，位于 CORE eval_data 下 | 是，前提同上 |
| gpqa_diamond | eval_stem/eval_data/gpqa_diamond.jsonl | 是 |
| gsm8k_cot | eval_stem/eval_data/gsm8k.jsonl | 是 |
| math_cot_500 | eval_stem/eval_data/math500.jsonl | 是 |
| mmlu_stem | eval_stem/eval_data/mmlu_stem.jsonl | 是 |
| mmlu_zeroshot | eval_stem/eval_data/mmlu.jsonl | 否，显式选择或 all 时才用 |

因此保留整个 CORE 包和完整 STEM 包最方便，不需要再额外下载一份 HF ARC 数据集。这里的 gsm8k_cot 是实际任务标签，不等于 UI 目前提供的 gsm8k；字段映射需要统一后才能保证按用户选择运行。

#### 必须检查“完整”，不能只检查“存在”

实际 base_eval.py 的 get_available_stem_tasks 会跳过不存在的文件；只剩一个 STEM 文件也可能继续执行并计算一个不完整的 STEM 平均分。

验收时应确认：

- 默认 stem 所需的六个任务全部出现在最终报告中；
- ARC 两项在 core.yaml 中存在且其引用文件可读；
- 四个默认 STEM JSONL 均非空、格式符合加载器；完整包额外保留 mmlu.jsonl；
- 保留原包的 eval_meta_data.csv，核对对应基线；若没有基线，脚本会使用未中心化的准确率，报告应说明；
- 不能把“只成功评测部分任务”视为完整 STEM 评测成功。

可在下载并解压后的 Linux 准备环境执行以下存在性检查（需要 PyYAML）。它不加载模型，也不访问网络：

```bash
python3.11 - /绝对路径/eval_bundle <<'PY'
import sys
from pathlib import Path
import yaml

root = Path(sys.argv[1])
required = [
    root / "core.yaml",
    root / "eval_meta_data.csv",
    *[root / "eval_stem" / "eval_data" / name for name in (
        "gpqa_diamond.jsonl", "gsm8k.jsonl", "math500.jsonl",
        "mmlu.jsonl", "mmlu_stem.jsonl",
    )],
]
missing = [str(p) for p in required if not p.is_file() or p.stat().st_size == 0]
if missing:
    raise SystemExit("Missing/empty evaluation assets:\n" + "\n".join(missing))
config = yaml.safe_load((root / "core.yaml").read_text(encoding="utf-8"))
tasks = {t["label"]: t for t in config["icl_tasks"]}
for label in ("arc_easy", "arc_challenge"):
    if label not in tasks:
        raise SystemExit(f"CORE config is missing task: {label}")
    path = root / "eval_data" / tasks[label]["dataset_uri"]
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"Missing/empty ARC data: {path}")
print("Evaluation asset file check OK; still verify JSONL schema and model loading.")
PY
```

工具当前通过 offline_base_eval.py 替换 prepare_eval_data，阻止这个 helper 重新下载 CORE/STEM；但替换后的检查不保证全部任务文件完整，所以上述核对仍必要。直接运行原始 base_eval.py 则仍保留其下载分支。

### 3.4 Python 离线依赖

#### 控制端：运行 UI/API

当前控制端基础直接依赖为：

```text
fastapi>=0.100
uvicorn>=0.23
pydantic>=2.0
requests>=2.28
PyYAML>=6.0
numpy>=1.24
```

若控制端还要读取和检查 Parquet，需要 pyarrow。下载时必须同时取得传递依赖，例如 pydantic-core、starlette、anyio、h11、click、typing-extensions 和 requests 的依赖。

在与开发机相同平台和 Python 3.11 的联网准备环境执行：

```bash
python3.11 -m pip download --only-binary=:all: \
  --dest ./offline_assets/control_wheels \
  "fastapi>=0.100" "uvicorn>=0.23" "pydantic>=2.0" \
  "requests>=2.28" "PyYAML>=6.0" "numpy>=1.24" pyarrow
```

上面的开放版本只是首次收集命令，不是经过验证的兼容版本锁。应在隔离环境验证后固定全部解析版本，保留这次 wheel 快照供后续安装，不能每次都重新获取最新版。

#### ModelArts 计算端：运行配比、训练和评测

当前运行预检要求以下包：

```text
PyYAML numpy pandas pyarrow scipy scikit-learn lightgbm joblib
matplotlib tqdm psutil jinja2 torch torch_npu transformers tokenizers
datasets tiktoken filelock requests
```

此外还需检查实际 nanochat-npu 版本、策略脚本的额外依赖，以及 moxing 或 obsutil。

必须区分两类依赖：

1. 镜像基础栈：Python 3.11、torch、torch_npu、CANN、驱动、HCCL。以平台验证过的配套版本为准，不要直接 pip 升级 torch/torch_npu，也不能用 CUDA wheel 替代。
2. 额外 Python 包：按镜像实际缺口补齐。使用同镜像、Linux AArch64、相同 Python ABI 收集离线包并验安装，不能拿 Windows/x86_64 wheel 直接上传。

已明确的 LightGBM 文件名：

```text
lightgbm-4.6.0-py3-none-manylinux2014_aarch64.whl
```

只收集这个明确缺失包的 Windows 跨平台示例：

```powershell
python -m pip download --only-binary=:all: --no-deps --platform manylinux2014_aarch64 --python-version 311 --implementation cp --dest ./offline_assets/python_wheels "lightgbm==4.6.0"
```

此处 --no-deps 只适用于镜像已有兼容 numpy/scipy 的情况。不能将它推广成“所有包都不下载依赖”。其他包的 Linux 平台标签需与目标镜像兼容，不应机械复用 LightGBM 的标签。参见 [pip download 官方说明](https://pip.pypa.io/en/stable/cli/pip_download/)。

完整计算依赖的离线包应由镜像管理员生成已验证的 compute-addons.lock.txt 后收集：

```bash
# 文件必须事先列出已经验证的额外包及精确版本；不要填猜测版本。
python3.11 -m pip download --only-binary=:all: \
  --dest ./offline_assets/python_wheels -r compute-addons.lock.txt
```

当前 UI 工作流启动命令只自动安装上述指定 LightGBM。其他 wheel 放进 OBS 不会自动安装，必须在正式镜像中预装，或后续修改统一启动程序进行离线安装。本手册未修改启动程序。

系统动态库不能用 wheel 代替：需要验证 OpenMP/C++ 运行库、Ascend 环境脚本路径及 HCCL。镜像名字和环境目录名不能作为实际版本证据。

#### 导出不含凭据的实际版本信息

在目标镜像和实际 Python 下运行，保留输出供制作版本锁：

```bash
python3.11 - <<'PY'
import importlib.metadata as md
import platform
import sys
print("python:", sys.version)
print("executable:", sys.executable)
print("architecture:", platform.machine())
names = [
    "torch", "torch-npu", "numpy", "pandas", "pyarrow", "scipy",
    "scikit-learn", "lightgbm", "joblib", "matplotlib", "PyYAML",
    "tqdm", "psutil", "jinja2", "transformers", "tokenizers",
    "datasets", "tiktoken", "filelock", "requests",
]
for name in names:
    try:
        print(f"{name}=={md.version(name)}")
    except md.PackageNotFoundError:
        print(f"{name}: MISSING")
PY
python3.11 -m pip check
```

此脚本只输出版本，不打印环境变量、Authorization 或 pip 配置中的凭据。

### 3.5 不需要默认全部下载的内容

| 内容 | 当前是否需要 |
|---|---|
| GPT-NeoX 20B 模型权重 | 不需要，QuaDMix 使用其 tokenizer，不靠这些预训练权重启动代理模型 |
| ClimbMix 通用训练数据 | 两作业入口当前 MIX_GENERAL_DATA=0，不需要；开启后才需另外准备且避免现场下载 |
| 所有历史代理验证集 CORE-BMK/OpenHermes/CAP | 当前选 stem_v2 时不需要全部下载 |
| 所有 HF chat/SFT/评测任务数据 | 只有实际启用对应代码路径才需要；不是当前默认流程全部必需 |
| WandB 服务/账号/数据 | 当前按此前确认使用 disabled 日志兼容实现，不要求 WandB 联网；启用真实 WandB 才另行准备 |
| 真正的 rustbpe 编译环境 | 只加载现有兼容 tokenizer 时通常不需要；重新训练 tokenizer 时需要实际实现 |
| Node.js/npm 包 | 运行已构建 UI 不需要；只有重新构建前端时才需要 |
| tiktoken 全部编码缓存 | 不需要盲目下载；用实际可信 tokenizer.pkl 测试，若需要外部编码再收集对应缓存 |

若 tiktoken 需要缓存，应在相同软件版本的联网准备环境中对实际可信 tokenizer 做加载/编码测试，收集生成的缓存，并设置容器 TIKTOKEN_CACHE_DIR。当前 UI 没有该专用挂载字段，必要时还需增加挂载配置；不能只上传而不配置。相关行为以实际 tiktoken 版本为准。

## 4. OBS 目录组织和挂载关系

可以保留你当前已有目录，不必为了本手册全部改名。下面除你已给出的 tokenizer、eval_bundle、chengchao 地址外，其余是建议位置，不表示已经存在：

```text
obs://bucket-pangu-green-guangzhou/s00944147/l00916525/
├── Auto-Mixture-Tool/             # 发布代码快照，不含真实凭据
├── nanochat-npu/                  # 配套训练框架
├── nanochat_model_dir/            # 模型、tokenizer.pkl、token_bytes.pt
├── gpt-neox-tokenizer/            # 已有，可复用
├── proxy_validation/             # stem_v2_tokenized.pt
├── eval_bundle/                  # 已有，需核对 STEM 完整性
├── python_wheels/                # 计算镜像额外包
├── control_wheels/               # 开发环境 UI/API 包
├── strategies/                   # 可选可信 .py 文件
└── chengchao/
    ├── prepared_parquet_57ffce0ca0a2/
    └── runs/                     # 每次实验的输出
```

在 UI 填 OBS 地址；代码中的容器本地路径由后端配置。不要把开发机的 /home/ma-user/work/... 直接填入 OBS 地址框。

| UI/API 资源字段 | 容器路径 |
|---|---|
| input_data_obs_uri | /home/ma-user/modelarts/inputs/data_dir_0 |
| resources.nanochat_model_obs_uri | /home/ma-user/modelarts/inputs/nanochat_model_dir_1 |
| resources.code_obs_uri | /home/ma-user/modelarts/user-job-dir/Auto-Mixture-Tool，另有 inputs/code_dir_2 |
| resources.nanochat_repo_obs_uri | /home/ma-user/modelarts/inputs/nanochat_npu_dir_3 |
| resources.quadmix_tokenizer_obs_uri | /home/ma-user/modelarts/inputs/quadmix_tokenizer_dir_4 |
| resources.proxy_validation_obs_uri | /home/ma-user/modelarts/inputs/proxy_validation_dir_5 |
| resources.eval_bundle_obs_uri | /home/ma-user/modelarts/inputs/eval_bundle_dir_6 |
| resources.python_wheels_obs_uri | /home/ma-user/modelarts/inputs/python_wheels_dir_7 |
| 第一个作业的 sampled 输出 | 第二作业的 /home/ma-user/modelarts/inputs/comparison_data_dir_8 |

- 用 OBS 控制台或已有授权的 OBS 客户端上传实际文件，保留目录层级。
- 模型、框架、tokenizer 等目录应上传展开的文件，不能只上传一个 ZIP 并假设作业会自动解压。评测 ZIP 是否受支持以加载器为准。
- 不上传真实 Authorization、AK/SK、HF token、浏览器缓存或带凭据的 Git 配置。配置了凭据的开发机工作目录，不应直接整目录打包到 OBS。
- 输入目录需可读；输出及多节点协调目录需允许相应读写/列举操作。OBS 同路径不等于跨节点共享的 POSIX 目录。
- 当前没有访问 OBS 检查这些目录，本表不是上传成功证明。

## 5. 管理员在开发机首次配置什么

不使用 .env.modelarts。仅在开发机本地 modelarts_training_job.py 填写：

| 字段 | 含义 |
|---|---|
| url | ModelArts 创建作业 API；当前后端按 url/{job_id} 查询，必须确认平台实际协议匹配 |
| headers.region | 区域 |
| headers.Authorization | 有效的完整鉴权值，只保留在控制服务端 |
| job_data.metadata.workspace_id | 工作空间 |
| job_data.algorithm.engine.image_url | 经过验证的 NPU 镜像地址 |
| job_data.algorithm.engine.image_repo_id | 与镜像匹配的镜像仓库 ID |
| job_data.spec.resource.flavor_id | 每节点规格 |
| job_data.spec.resource.pool_id | 资源池 |
| job_data.spec.resource.policy | 资源策略，按平台授权选择 |

UI 两作业后端复用请求主体，替换本次作业名称、节点数、阶段 command、输入输出和配置；不需要用户每次手改整个脚本。

当前两个作业可以分别设置节点数，但仍共享模板中的镜像、每节点规格和资源池。模板 NODE_COUNT 保持默认 2；UI 会分别覆盖两作业节点数。

凭据过期后应按平台流程更新。当前进程缓存客户端，不应假设编辑文件会立即刷新正在运行的客户端；调度恢复机制修复前也不要在运行中贸然重启服务。

## 6. 每次实验用户需要提交什么

### 6.1 必填材料/配置

| 用户提交项 | 示例/要求 |
|---|---|
| 标准数据 OBS 目录 | obs://bucket-pangu-green-guangzhou/s00944147/l00916525/chengchao/prepared_parquet_57ffce0ca0a2/ |
| 输出 OBS 根目录 | obs://bucket-pangu-green-guangzhou/s00944147/l00916525/chengchao/ |
| 配比策略 | 当前入口必须保留一个 QuaDMix；可加随机及多个不同人工方案 |
| 配比参数 | 代理实验数、每实验步数、搜索次数；当前默认 16 / 15 / 1000 |
| 配比、训练节点数 | 分别填写，当前测试目标均为 2，每节点 8 卡 |
| 训练框架与模型 | 兼容的 NanoChat 代码/模型 OBS 地址，base_model_tag 如 d24 |
| 训练数据预算 | target_param_data_ratio，如 0.5；它不是训练步数或学习率 |
| 评测选择 | 与实际 NanoChat 版本匹配的 stem 及离线资源目录 |
| 共享运行资源地址 | 管理员提供的工具代码、tokenizer、代理验证集、eval_bundle、wheel 目录 |

实验名可填写 trial_001 等标识。无需在浏览器上传全部数据文件，先上传 OBS，再提供路径。默认两作业，不是三种方法各提交一个作业。

### 6.2 输入 Parquet 的当前契约

UI 工作流目前固定使用 configs/schema_stem_quadmix_parquet.yaml：

| 列 | 要求 |
|---|---|
| text | 非空训练文本 |
| domain | 统一领域，当前配置为数学、化学、生物学、物理 |
| stem_relevance | 数值质量分 |
| knowledge_value | 数值质量分 |
| notation_fidelity | 数值质量分 |
| rigor_coherence | 数值质量分 |
| noise_level | 数值质量分 |
| char_count | 非负整数文本长度 |
| source_record_idx | 分片内来源记录索引，保留可追溯性 |

字符串化标签与质量对象应在上游过滤转换阶段展开；质量值必须是有限数，禁止 NaN/Infinity，范围按实际算法 schema 确认。当前校验器对这些规则尚有漏洞，不能用“通过现有校验”代替数据质量验收。

目前 UI 没有任意 schema 上传/选择能力。更换领域和标签不只是改数据地址，还需适配 schema 与算法契约。

### 6.3 人工配比和自定义脚本

内置人工方案只需提交比例，例如：

```yaml
数学: 0.60
物理: 0.15
化学: 0.125
生物学: 0.125
```

使用自定义策略时额外提交：

1. 可信 Python .py 文件的 OBS 路径。
2. 策略名称/方案 ID、比例及可选配置对象。
3. 依赖包与版本清单；当前单文件自动挂载不会自动安装依赖或上传被 import 的辅助文件。
4. 如有额外模型/配置/数据文件，列出它们的 OBS 地址和容器挂载要求；当前 UI 尚不自动处理这些附件。

当前策略接口示例：

```python
STRATEGY_API_VERSION = "1"

def select(pool, context, config):
    import numpy as np
    return np.random.default_rng(context.seed).permutation(len(pool.document_ids))
```

此示例返回候选池位置下标，由平台按预算裁剪。下标必须为一维整数、无重复、不越界，并满足平台预算检查。

pool 目前只提供 shard_ids、document_ids、estimated_tokens、domain_ids；context 包含 method、token_budget、seed、domain_name。当前不是任意训练脚本接口，也不提供完整文本/质量分给脚本；不能宣称上传后可以执行任何采样逻辑。

现有 examples/strategies/random_length_aware.py 可作接口参考；manual_quality_first.py 实际按估算长度排序，不应当作真实质量分优先采样的证明。自定义脚本执行仍受上一轮发现的分支串线和领域传参问题影响，修复前不要用于正式对比。

### 6.4 训练框架和评测上传的边界

- “OBS 挂载框架”要求 NanoChat 兼容接口，并非上传任意 PyTorch/其他训练框架就能运行。
- 模型必须符合 NanoChat checkpoint/tokenizer 格式，并不是任意 Hugging Face 模型目录都可直接替换。
- 评测集必须符合实际评测器的文件协议，不是任意 JSON 都能读取。
- 自动评测 API 目前只展示，不提交请求；无需现在上传其未知依赖，也不要把 API 密钥填入演示页面。

## 7. 在开发环境拉取和启动 UI/API

### 7.1 获取代码

首次拉取，在开发机执行：

```bash
cd /home/ma-user/work
git clone https://github.com/AutoDataMixture/Auto-Mixture-Tool.git
cd /home/ma-user/work/Auto-Mixture-Tool
```

若不能访问 GitHub，用 OBS 下载同一版本的代码快照并放到上述目录。已有代码不要直接删：先检查 git status，保留本地凭据配置；有本地修改时先明确合并方式，不要强制覆盖。

更新后检查 docs/OFFLINE_RESOURCES_AND_OPERATIONS.md 是否存在，并用 git log -1 核对版本。拉取文档更新不会自动取得尚未实施的程序整改。

### 7.2 安装离线控制端依赖

把 control_wheels 从 OBS 下载到开发机，例如 /home/ma-user/work/control_wheels，然后执行：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --no-index \
  --find-links /home/ma-user/work/control_wheels \
  "fastapi>=0.100" "uvicorn>=0.23" "pydantic>=2.0" \
  "requests>=2.28" "PyYAML>=6.0" "numpy>=1.24" pyarrow
python -m pip check
```

这个环境只用于控制服务，不在这里随意安装/升级 NPU 框架。不要复制开发机 .venv 到 AArch64 容器。

### 7.3 填好模板并启动

先按第 5 节填写本地模板，再启动。当前采用源码入口，并显式加入仓库根与 src，避免根模板导入问题：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
source .venv/bin/activate
export PYTHONPATH="$PWD:$PWD/src:${PYTHONPATH:-}"
python -m auto_mixture_tool.cli --workspace "$PWD" \
  serve --host 127.0.0.1 --port 8080
```

另一个终端检查：

```bash
curl --fail http://127.0.0.1:8080/api/v1/health
```

通过开发环境已有的端口转发打开 /ui。需要内网直接访问时可以改 --host 0.0.0.0，但必须先限制访问来源；当前 API 未实现鉴权，不要向公网开放。

访问地址格式为 http://<开发环境地址>:8080/ui，不是 file:///.../index.html。文件预览不能承担后端提交和轮询。

服务需持续运行；当前服务重启不会自动续接未完成工作流。在恢复机制修复前，不能把服务简单重启等同于恢复任务。

## 8. UI 中如何配置并提交

资源准备和已知阻断问题修复后，按以下顺序进行小规模联调：

1. 配比策略页：填写标准 Parquet OBS 目录和输出根目录，配比节点数填 2。
2. 保留 QuaDMix，代理实验数 16、代理步数 15、搜索次数 1000、每节点 8 卡；15 步只适合连通性测试，不代表算法效果已验证。
3. 按需要添加随机和人工方案，人工方案填写名称与比例；首次联调先不要启用额外第三方脚本。
4. 训练配置页：训练节点数独立填 2，框架 NanoChat，模型标签 d24，确认模型/代码地址和所有离线资源地址正确。
5. 评测页：选择实际兼容的 stem 与对应离线包；自动评测 API 保持未启用。
6. 确认页：检查预计两个作业、各自节点数、原始输入目录、采样输出目录和训练输出目录，再点击一次启动。
7. 第一个作业完成并输出全部采样数据后，后端自动提交第二个作业。第一作业失败时不应提交第二个作业。
8. 到 ModelArts 和 OBS 同时核对状态、日志、模型及报告。当前 UI 百分比主要是阶段状态，不是精确训练步数进度。

当前 UI 的 CPU/CUDA 选择、人工/随机独立 seed、Base/Mid 切换及关闭评测存在未生效问题，修复前不要依赖这些设置。当前 API 强制包含 QuaDMix，不能仅选择人工/随机。

节点数目前是参数上允许 1–16，不代表所有规模已经验证。先验收 2 节点，再确认数据分片和 checkpoint 跨节点契约后扩容。配比节点与训练节点无需相同，但不能仅改节点数字就跳过这两项检查。

### 8.1 如何理解 modelarts_training_job.py 与 YAML

- UI 两作业方式：开发机服务读取 modelarts_training_job.py 的模板；UI 提供实验配置；后端使用 stage_runner 分别启动两阶段。
- 直接执行 python3 modelarts_training_job.py：使用脚本自身的单作业提交路径与 modelarts_pipeline.yaml，不等同于 UI 的两个作业。
- 因而修改 modelarts_pipeline.yaml 中的参数，不会自动改变 UI 两作业的同名设置；修改模板中的 command 也不会改变后端生成的两阶段 command。
- 同一次实验不要一边点击 UI、一边直接运行脚本，以免提交两套不同任务。

### 8.2 如果只在开发机本地 8 卡计算

使用单独的本地 YAML，所有输入资源都应是已下载的开发机本地路径，executor_id=local，节点为单机、每节点 8 卡：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
export PYTHONPATH="$PWD:$PWD/src:${PYTHONPATH:-}"
# 使用已验证且装有 torch_npu 的计算解释器，不是仅安装控制端依赖的 .venv。
python3.11 -m auto_mixture_tool.cli --workspace "$PWD" run /绝对路径/local_pipeline.yaml
```

local_pipeline.yaml 需事先配置本地 Parquet、schema、tokenizer、代理验证集、NanoChat 框架/模型、eval_bundle 和独立输出目录。不要直接照搬 demo_pipeline.yaml：它目前仍是原始 JSON 转换与前 200 分片的旧示例，没有完整的当前离线资源配置。

本地 YAML 与远程 UI 两作业是两种执行方式；本地校验/训练成功不等于 OBS 跨作业交接或多节点同步已通过。

## 9. 输出在哪里、包含什么

UI 输出根目录是 chengchao 时，输出按实验名称及启动时间组织：

```text
obs://bucket-pangu-green-guangzhou/s00944147/l00916525/chengchao/
└── runs/
    └── <实验名>-<时间戳>/
        ├── mixing/
        │   ├── ...QuaDMix 搜索、最优配比及采样产物
        │   └── coordination/
        ├── sampled/
        │   └── data/
        │       ├── quadmix_data/
        │       ├── random_data/
        │       ├── manual_ratio_data/
        │       ├── manual_<方案ID>_data/
        │       ├── dataset_stats.json
        │       └── manual_plans_manifest.json
        └── training/
            ├── checkpoints/
            └── results/
                ├── mid_train_*.log
                ├── eval_*.log
                ├── experiment_report.md
                └── ...其他统计及人工方案报告
```

只输出实际选择并成功执行的策略；不是每次都必然有所有目录。NanoChat 默认训练使用采样后的 Parquet，不需要额外转 JSON。

正常完成时，各采样方案分别训练模型，从同一个初始模型起点对比，而不是拿同一个训练模型重复打分。报告需检查实际 token 数、领域比例、训练预算和各方案指标；只有文件夹或作业创建成功不算实验成功。

实验名目前带时间戳，可降低名称冲突，但没有完善的重复提交防护；不要把重复点击当成安全重试。

## 10. 严格离线验收清单

资源齐备与程序完全不访问外网是两项不同验收。

- [ ] 固定工具代码、实际 nanochat-npu 版本、模型版本、镜像及实际包版本。
- [ ] 所有模型文件、元数据、tokenizer.pkl、token_bytes.pt 可在目标镜像正常加载。
- [ ] GPT-NeoX tokenizer 可在 local_files_only 模式加载；代理验证集校验值和内容兼容。
- [ ] 实际选中的每个 STEM/其他评测任务可从本地资源加载，不只是目录存在。
- [ ] 镜像内所需 Python 包、动态库、CANN 路径、NPU、HCCL 可用。
- [ ] moxing 或 obsutil 可在容器中实际访问输入、输出及协调 OBS 目录。
- [ ] 采样清单和缓存使用可迁移路径；全部训练 rank 能读到非空数据。
- [ ] 在允许 OBS/API/集群通信、禁止公共下载站点的环境完成小规模完整测试。
- [ ] 两作业自动衔接，各选中方案均生成采样集、模型、指标和配比报告。

当前仍需整改的外网入口：

1. scripts/runners/run_essential_web_v1.py 中 _ensure_hf_data 即使有本地文件仍发 urllib HEAD 检查远端；尺寸不同时可能删除并重下。HF_HUB_OFFLINE 不能拦截 urllib。应改为离线模式只做本地验证，缺失或不匹配直接明确失败。
2. 当前工具的 offline_base_eval.py 已替换实际 base_eval.prepare_eval_data，阻止该评测 helper 下载；但直接运行原始脚本仍可能下载。其他 NanoChat/辅助脚本中的 requests、curl 和下载回调还需按实际调用路径验收。
3. HF_HUB_OFFLINE、HF_DATASETS_OFFLINE、TRANSFORMERS_OFFLINE 是辅助设置，不是网络隔离，也不会自动制造缺失资源。
4. 现有 offline_resource_check.py 漏查 token_bytes.pt、具体评测文件和 OBS 工具；UI 的新 command 也没有调用完整资源预检。预检成功不代表所有资源均齐备。

建议验收后形成固定资源 manifest：资源名、OBS URI、代码/model revision、文件清单、SHA256、适用镜像及许可证/访问限制。不要把凭据写进 manifest。

## 11. 尚需固定的版本与资源证据

1. 实际 base_eval.py 已由你提供，STEM 资源目录和下载来源已补齐。下载后的两个评测包仍要核对内容与校验值；JSONL 字段兼容性最终以同版本 nanochat/core_eval.py 的实际加载测试为准。
2. 目标镜像的实际 Python/torch/torch_npu/CANN 与第 3.4 节包版本输出尚未提供：据此才能给出最终计算依赖版本锁。

本手册是基于现有代码和你提供的评测脚本的准备清单及操作说明，不是“OBS 实物已核实、集群保证零下载且不会缺包”的证明。
