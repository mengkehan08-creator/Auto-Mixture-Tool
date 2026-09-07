# 离线运行整改与上线检查

## 本次已落实

- 从提供的脚本提取区域、工作空间、镜像、资源规格与资源池等非敏感默认值，统一放在 `configs/modelarts_ui_defaults.json`，页面默认填写且可编辑。认证凭据仍手动输入，仅在内存保留。
- 页面默认 command 直接包含可编辑的环境配置、离线安装和启动命令，不再调用 shell 启动文件。
- 长配置采用压缩、分段和摘要校验；清除旧分段，避免旧数据混入。缺段、损坏和超限明确失败。
- 默认启动路径强制 Python 3.11，依赖从镜像或 OBS wheel 获取，不访问 PyPI。仅自动安装已有的离线 LightGBM wheel；不擅自替换 torch、torch_npu 或 CANN。
- 启动检查列出依赖版本、缺失及不兼容模块。容器在配比/训练前检查模型、Tokenizer、验证文件与数据挂载，汇总缺项。
- QuaDMix 离线模式不再向 Hugging Face 查询验证文件大小；缺失/损坏时不删除文件再下载。Tokenizer 缺失时不回退在线加载。
- 训练前按挂载的 NanoChat `base_eval.py` 的任务定义检查所选评测文件。不会因为部分 STEM 数据存在就静默跳过其他任务。
- 训练中与最终评测均使用本地评测资源检查。ZIP 拒绝越界路径和符号链接写入。
- 默认资源角色映射集中管理；修复独立评测资源地址被默认列表覆盖的问题。页面说明缩短，保留必要风险提示。

## 必备离线资源

| 资源 | 内容要求 |
|---|---|
| 工具代码 | 新版完整代码，包含 `scripts/run_modelarts_stage.sh` 与 `config_transport.py` |
| 输入数据 | 已校验的 Parquet 分片，使用实际算法所需标签 |
| QuaDMix Tokenizer | `tokenizer.json` 及配套配置，不是 20B 模型权重 |
| 代理验证集 | `stem_v2_tokenized.pt`，内容必须与代理模型 Tokenizer 兼容 |
| NanoChat 代码 | 与镜像兼容的完整代码，包括训练及评测模块 |
| NanoChat 初始模型 | `base_checkpoints/<标签>/`、`tokenizer/tokenizer.pkl`、`tokenizer/token_bytes.pt` |
| 评测包 | `eval_bundle/core.yaml`、相应 `eval_meta_data.csv`、任务引用的 `eval_data/*.jsonl`；STEM 额外数据位于 `eval_stem/eval_data/` |
| 离线 wheel | Python 3.11 / Linux aarch64 对应包；LightGBM 默认文件名见启动脚本 |

优先上传解压好的评测目录，避免压缩包根目录层级不符。默认 STEM 组合包含哪些任务由挂载版 NanoChat 声明决定；工具会检查所选文件，不能仅上传其中一个数据集。

## 更新步骤

1. 同时更新开发环境后端和 OBS 中的工具代码，不要只更新 HTML。
2. 重启后端，刷新页面，进入任务配置。核对自动填写的镜像、区域和资源池；填写 Authorization。
3. 复制旧实验时点击“恢复默认命令”，否则会继续使用旧的自定义长命令。
4. 核对每个 OBS 目录确实存在，并且作业身份有读写权限。配置检查不是 OBS 权限检查。
5. 先用当前 2 节点、小数据量和较少步骤做完整验收，确认采样、训练、评测及输出，再扩大任务规模。

## 仍需目标环境确认

- 新镜像实际安装的包可能与名称描述不同，应以运行日志版本清单为准。本机没有 NPU，不能验证算子、显存、HCCL 或多节点网络。
- ModelArts 资源配额、镜像权限、请求总大小、环境变量数量等由实际平台决定；已修复已知单变量 4096 字符问题，不保证所有平台限制都被覆盖。
- 上传的策略、自定义 command 和外部 NanoChat 版本属于可信用户代码，可能含自己的联网逻辑。本次约束默认入口与已检查的路径，不是系统级网络沙箱；强制隔离应由集群出口策略实现，保留必要的 OBS/ModelArts 通信。
- `scripts/preprocess/download_essential_web.py`、`scripts/validation_set/` 等独立数据准备工具本来用于下载资源，不是默认 UI 运行链路，未删除它们的联网功能。
- W&B 禁用兼容与可选 Dask 屏蔽是既有行为，未伪装成真实服务。若需要 W&B 在线跟踪或 Dask 分布式计算，必须安装并验证真实依赖。
- 当前控制台面向可信内部用户，没有多用户权限隔离；现有 ModelArts 客户端仍沿用原企业网关的证书验证设置，不能直接开放到公网。

本地测试验证逻辑和错误路径，不代替真实 ModelArts 两作业端到端验收。
