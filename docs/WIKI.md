# Auto-Mixture-Tool Wiki

Wiki 已拆分为以下四篇独立文档。首次使用按“部署 → 用户说明”阅读；开发维护与实验归档分别查阅后两篇。

| 文档 | 内容 |
| --- | --- |
| [工具部署](WIKI_DEPLOYMENT.md) | 安装、OBS 资源、IAM 与网络、启动、升级 |
| [用户说明](WIKI_USER_GUIDE.md) | 策略与批量配置、训练、评测、任务提交及重试 |
| [工具设计](WIKI_DESIGN.md) | 架构、模块、数据契约、调度依赖与扩展边界 |
| [实验结果与记录](WIKI_EXPERIMENTS.md) | 输出位置、结果解读、验收、记录模板、备份与排障 |

新建实验每节点固定 8 张 NPU；采样参数仅设置上限，下限固定为 0。“人工配比”在界面中更名为“自定义配比”，内部 `manual` 标识保持兼容。

## 快速导航

以下保留原 Wiki 锚点，便于从旧链接跳转到新文档。

### 工具部署

<a id="deployment"></a>

- [工具部署](WIKI_DEPLOYMENT.md#deployment)

<a id="deploy-install"></a>

- [1.2 下载代码并安装开发环境](WIKI_DEPLOYMENT.md#deploy-install)

<a id="deploy-resources"></a>

- [1.3 准备 OBS 数据和运行资源](WIKI_DEPLOYMENT.md#deploy-resources)

<a id="deploy-auth"></a>

- [1.4 配置数据挂载与自动认证](WIKI_DEPLOYMENT.md#deploy-auth)

<a id="deploy-start"></a>

- [1.5 启动服务并打开界面](WIKI_DEPLOYMENT.md#deploy-start)

<a id="deploy-maintenance"></a>

- [1.6 日常启动与版本升级](WIKI_DEPLOYMENT.md#deploy-maintenance)

### 用户说明

<a id="user-guide"></a>

- [用户说明](WIKI_USER_GUIDE.md#user-guide)

<a id="user-mixing"></a>

- [2.2 配比策略：输入数据、策略与批量配置](WIKI_USER_GUIDE.md#user-mixing)

<a id="user-training"></a>

- [2.3 训练配置：模型、预算与统一参数](WIKI_USER_GUIDE.md#user-training)

<a id="user-evaluation"></a>

- [2.4 评测配置：任务、评测包与历史模型](WIKI_USER_GUIDE.md#user-evaluation)

<a id="user-submit"></a>

- [2.5 任务配置：资源、启动命令与提交](WIKI_USER_GUIDE.md#user-submit)

<a id="user-jobs"></a>

- [2.6 管理作业与阶段重试](WIKI_USER_GUIDE.md#user-jobs)

### 工具设计

<a id="tool-design"></a>

- [工具设计](WIKI_DESIGN.md#tool-design)

<a id="design-flow"></a>

- [3.1 运行环境与端到端依赖关系](WIKI_DESIGN.md#design-flow)

### 实验结果与记录

<a id="experiment-records"></a>

- [实验结果与记录](WIKI_EXPERIMENTS.md#experiment-records)

<a id="results-output"></a>

- [4.1 输出文件与存储位置](WIKI_EXPERIMENTS.md#results-output)

<a id="results-analysis"></a>

- [4.2 结果分析页面与指标口径](WIKI_EXPERIMENTS.md#results-analysis)

<a id="acceptance"></a>

- [4.3 链路验收与扩大实验规模](WIKI_EXPERIMENTS.md#acceptance)

<a id="record-backup"></a>

- [4.4 必须保留的记录与备份](WIKI_EXPERIMENTS.md#record-backup)

<a id="troubleshooting"></a>

- [4.6 故障排查与问题记录](WIKI_EXPERIMENTS.md#troubleshooting)

<a id="reference-index"></a>

- [4.7 进一步阅读与代码索引](WIKI_EXPERIMENTS.md#reference-index)

<a id="acceptance-checks"></a>

- [查看相关章节](WIKI_EXPERIMENTS.md#acceptance-checks)
