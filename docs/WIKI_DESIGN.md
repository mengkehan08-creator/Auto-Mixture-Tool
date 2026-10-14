<a id="tool-design"></a>

# 工具设计

[Wiki 首页](WIKI.md) · [工具部署](WIKI_DEPLOYMENT.md) · [用户说明](WIKI_USER_GUIDE.md) · **工具设计** · [实验结果与记录](WIKI_EXPERIMENTS.md)

适用：当前 Web 多策略实验流程。具体运行结果以实际作业、日志与报告为准。

本章解释现有实现，不把未来扩展接口当作已经验证的能力。部署命令见[工具部署](WIKI_DEPLOYMENT.md)，页面填写方法见[用户说明](WIKI_USER_GUIDE.md)。

<a id="design-flow"></a>

## 3.1 运行环境与端到端依赖关系

### 3.1.1 各部署位置的职责

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
自定义配比作业    ──成功──→ 对应训练作业 ──┼─全部训练成功─→ 汇总评测作业
随机配比作业    ──成功──→ 对应训练作业 ──┘                     ↑
                                                可加入历史成功模型
                                                            ↓
                                               OBS 模型、指标、对比报告
                                                            ↓
                                               实验作业 → 结果分析
```

### 3.1.2 一个实验会创建几个作业

- 每个策略对应 **1 个配比作业 + 1 个训练作业**。
- 启用评测后，再增加 **1 个汇总评测作业**。
- 3 个策略通常规划 7 个作业；7 个策略通常规划 15 个作业。
- 不启用评测时，作业数为 `2 × 策略数`。
- 本次训练模型与选中的历史模型放在同一个汇总评测作业内逐个评测，不会重新训练历史模型。

同一策略的配比成功后即可提交自己的训练，不必等待其他配比完成。实际是否同时运行还取决于资源池容量、配额及排队情况。

## 3.2 代码模块与技术职责

当前网页主流程采用“前端表单 → FastAPI → 持久化作业依赖图 → ModelArts 分阶段执行”。仓库内仍保留 YAML/命令式适配器及规范契约，不应把它们误认为所有 Web 操作都经过同一套编排器。

| 模块 | 技术与职责 | 主要代码 |
| --- | --- | --- |
| 页面与交互 | Vue 3 管理四步表单、批量策略、作业列表及结果图表；Vite 构建静态页面 | [ui_demo/src](../ui_demo/src/)、[App.vue](../ui_demo/src/App.vue) |
| 服务入口 | FastAPI 提供 JSON API 和静态 UI；Uvicorn 运行服务 | [server.py](../src/auto_mixture_tool/api/server.py)、[cli.py](../src/auto_mixture_tool/cli.py) |
| 配置与作业编排 | 校验实验配置、生成作业及依赖、限制并发、持久化状态、重试与恢复 | [workflow.py](../src/auto_mixture_tool/modelarts/workflow.py)、[parallel_workflow.py](../src/auto_mixture_tool/modelarts/parallel_workflow.py) |
| 云请求与启动配置 | 获取 IAM 凭据，构造 ModelArts 请求与启动命令，分片传递运行配置 | [iam_auth.py](../src/auto_mixture_tool/modelarts/iam_auth.py)、[command_preview.py](../src/auto_mixture_tool/modelarts/command_preview.py)、[config_transport.py](../src/auto_mixture_tool/modelarts/config_transport.py) |
| 输入检查 | 通过本地 OBS 映射读取 Parquet 元数据和少量样本；后台检查、短请求轮询 | [input_validation.py](../src/auto_mixture_tool/modelarts/input_validation.py)、[dataset_checks.py](../src/auto_mixture_tool/modelarts/dataset_checks.py) |
| 配比与选样 | QuaDMix 代理训练、LightGBM 回归搜索；自定义/随机基线及脚本策略 | [src/quadmix](../src/quadmix/)、[prepare_data.py](../nanochat_mid_compare/prepare_data.py) |
| 训练与多节点 | 调用挂载的 NanoChat；PyTorch 分布式启动、Ascend HCCL 通信、分片兼容 | [run_stem_experiment.sh](../nanochat_mid_compare/run_stem_experiment.sh)、[run_nanochat_mid_train.py](../nanochat_mid_compare/run_nanochat_mid_train.py) |
| 模型交接与评测 | 发布/核对模型清单、挂载各模型与 Tokenizer、适配评测包、输出得分 | [evaluation_job.py](../src/auto_mixture_tool/modelarts/evaluation_job.py)、[eval_formats.py](../nanochat_mid_compare/eval_formats.py) |
| 结果读取与分析 | 读取已有 JSON 报告、对齐共同评测项、生成确定性分析及中文摘要 | [result_analysis.py](../src/auto_mixture_tool/modelarts/result_analysis.py)、[ResultAnalysis.vue](../ui_demo/src/components/ResultAnalysis.vue) |

开发环境后端负责协调，重计算在 ModelArts；前端不能代替后端持续调度。开发环境安装的依赖也不等于容器镜像中的依赖。

## 3.3 数据校验与 Token 口径

数据在不同阶段有不同含义，不能把以下数值混为一谈：

| 名称 | 来源/计算方式 | 用于什么，不代表什么 |
| --- | --- | --- |
| 输入预计 Token 总量 | 每片随机至多 3 条文本的平均字符长度 × 该片文档数 ÷ 4，再汇总 | 数据规模估算；不是全量分词精确计数 |
| 代理实验消耗 | 页面默认每组步数 × 8 × 2048 | 小模型训练工作量，含重复读取；不是最终样本量 |
| 最终采样量预估 | 输入估算量与 ω、ε、λ、η 范围下的采样函数情景 | 配置阶段预判；不是回归搜索的最终结果保证 |
| 采样预算上限 | 参数量口径 × 目标比例 × 1.1 × 数据倍率 | 数据准备的预算上限，不保证候选数据足够 |
| 报告中的采样 Token 数 | 已准备样本文本的分词计数；是否精确以报告的统计方式为准 | 输出数据规模；重复入选的文本也计入，不等于唯一 Token 数 |
| 训练 Token 预算 | 用户配置，传递给各策略训练作业 | 计划累计训练消耗；实际步数取整及运行情况以训练日志为准 |

当前训练步数按 `ceil(训练 Token 预算 / 每步全局 Token 批量)` 计算；数据不足时训练可能再次读取已有文本。提高预算不等于产生新样本，也不会直接改变 QuaDMix 的搜索结果。

数据校验是异步任务：用户填写 OBS 地址后启动检查，前端查询结果；提交实验时只检查成功记录及有效期。默认每片最多抽查 3 条，并非全量质量审计。评测包另行检查题型、字段与评分方式，不能因文件扩展名正确就认定可评测。

## 3.4 模块扩展与当前兼容边界

| 扩展位置 | 当前支持 | 新增实现需要完成 |
| --- | --- | --- |
| 配比策略 | 多个 QuaDMix、自定义、随机策略；自定义/随机可提供可信 Python 脚本 | 遵循策略接口并验证采样输出；新增算法还需接入适配器、注册与执行路径 |
| 输入数据 | 当前 Web 入口使用满足算法契约的 Parquet | 新字段/领域需匹配 schema、校验器与算法，不能只改文件名 |
| 训练框架与模型 | NanoChat 兼容代码及 checkpoint；代码/模型地址可配置 | 新框架须实现启动、数据输入和模型输出清单协议，不能仅填写任意仓库地址 |
| 评测 | 内置 STEM 与可适配的 OBS 评测包 | 新题型需有可执行评分器；自动评估 API 目前尚未接真实服务 |
| 执行方式 | 本地执行器及 ModelArts/HPC 相关适配 | 容器内部使用本地执行，不应再次递归提交同一远程流程 |

命令式适配器位于 [plugins](../src/auto_mixture_tool/plugins/) 与 [PlatformService](../src/quadmix_platform/service.py)；规范契约注册表位于 [core/registry.py](../src/auto_mixture_tool/core/registry.py)。新增模块必须核对实际入口使用哪条路径，完成契约与端到端测试；存在插件接口不代表该模块已在 UI 和云端验证可用。

包初始化应维持既有惰性导入约定，避免可选重型依赖与循环导入阻断轻量服务。自定义策略属于可信内部代码，不提供沙箱隔离。

## 3.5 作业调度、产物交接与失败恢复

1. 后端将一次实验展开为独立配比、对应训练和汇总评测作业，保存名称、依赖、节点、命令与输入输出地址。
2. 只有前序成功的作业可以进入提交窗口。默认并发上限是本实验的 8 个活动作业，含排队；不是整个工具的全局资源配额。
3. 创建请求发出前持久化 `SUBMITTING`，收到云作业 ID 后保存。若超时导致结果不明，则标记待核对，不盲目再次创建付费作业。
4. 已知 ID 的作业状态查询失败时继续查询，不重新提交。单分支失败不终止其他独立分支，但阻止自己的下游和依赖全部模型的汇总评测。
5. 配比输出的 OBS 采样目录成为对应训练输入；训练的 `models_manifest.json` 指定模型文件与 checkpoint，成为评测输入依据。
6. 多节点依赖容器内的通信与现有产物同步机制。OBS 是持久化对象存储，不是保证实时共享可见的本地文件系统。
7. 阶段重试生成新的关联记录和输出目录，复用允许复用的前序产物。页面详情中的最终地址是核对依据。

完整配置通过压缩、编码及环境变量分片传递，避免把全部 JSON 塞进单个变量触发 4096 限制；解码大小仍有安全上限，不代表无限配置容量。源码见 [config_transport.py](../src/auto_mixture_tool/modelarts/config_transport.py)。

## 3.6 安全、运行限制与维护原则

- 私有 IAM 文件只保存在开发环境仓库外；IAM 和 ModelArts 网关是不同请求目标，代理/证书配置分别核对。
- OBS 数据读取依赖本地映射或相应 OBS 权限；ModelArts Authorization 不会自动变成 OBS 凭据。
- 同一工作区仅由一个后端进程调度；当前 JSON 持久化方式不提供多服务实例的分布式锁。
- 真实训练日志、模型和报告保留在输出目录；服务状态保留在开发环境。两处备份职责不同。
- 无独立租户隔离、不可信脚本沙箱或任意框架自动兼容能力。公开部署、多用户隔离和新的训练框架需要另行设计。
- 本机测试用于验证代码逻辑，不能替代目标镜像、OBS 权限、真实 NPU 和 HCCL 多节点验收。
