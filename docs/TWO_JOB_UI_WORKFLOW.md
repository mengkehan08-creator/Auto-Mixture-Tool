# UI 两作业自动工作流

## 1. 最终运行结构

开发环境中的 Auto-Mixture API 和 UI 负责配置、提交与监控；计算在 ModelArts 中完成。一次实验固定创建两个作业：

1. `mixing-<节点数>node-<启动时间>`：挂载标准 Parquet，先执行 QuaDMix 数据契约校验，再运行 QuaDMix，并为所有选中的 QuaDMix、随机配比和一个或多个人工配比生成采样集。
2. `training-evaluation-<节点数>node-<启动时间>`：只有第一个作业状态为 `Completed`、`Succeeded` 或 `Success` 后才自动提交；挂载第一个作业的 `sampled/`，校验 `dataset_stats.json`，跳过重复采样，依次训练、评测全部采样集。

两个作业的节点数独立，范围均为 1–16，每节点默认 8 张 NPU。自动评测 API 目前只在 UI 中展示，不会发送请求。

## 2. OBS 输入与输出

页面中的所有资源都填写 OBS 地址，不从浏览器上传大文件：

- 标准 Parquet 数据目录
- Auto-Mixture-Tool 代码目录
- NanoChat 代码目录
- NanoChat 模型目录（包含 `base_checkpoints/<base_model_tag>` 与 `tokenizer/tokenizer.pkl`）
- QuaDMix tokenizer 目录
- `stem_v2_tokenized.pt` 所在目录
- 离线评测资源目录
- 离线 Python wheels 目录
- 可选的随机或人工策略 `.py` 文件地址

若输出根目录为 `obs://bucket/path/chengchao/`，实验名为 `trial`，启动时间为 `20260904-120000`，最终结构是：

```text
obs://bucket/path/chengchao/runs/trial-20260904-120000/
├── mixing/     # QuaDMix 参数、配比和原始 sampled_dataset
├── sampled/    # 全部所选策略的 NanoChat 可训练采样集与 dataset_stats.json
└── training/   # 各采样集的 checkpoint、日志、指标和对比报告
```

每次都附加启动时间，因此重复点击不会覆盖上一次实验。

## 3. 首次配置 ModelArts 请求模板

只在仓库根目录 `modelarts_training_job.py` 中填写已有请求模板的以下值：

- `url`：创建训练作业的 API 地址；状态查询默认使用 `url/{job_id}`。
- `headers.region`
- `headers.Authorization`
- `job_data.metadata.workspace_id`
- `job_data.algorithm.engine.image_url`
- `job_data.algorithm.engine.image_repo_id`
- `job_data.spec.resource.flavor_id`
- `job_data.spec.resource.pool_id`

UI 后端会复用这个 `job_data` 主体结构，并仅替换作业名、节点数、阶段命令、OBS 输入输出和本次实验配置。不要把真实 Authorization 提交到 GitHub。

## 4. 在 8 卡开发环境启动

```bash
cd /home/ma-user/work
git clone https://github.com/AutoDataMixture/Auto-Mixture-Tool.git
cd Auto-Mixture-Tool

python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .

auto-mixture serve --host 0.0.0.0 --port 8080
```

浏览器打开 `http://<开发环境IP>:8080/ui`。若外部浏览器无法访问，需要在开发环境或安全组中放行 TCP 8080；也可以通过已有的端口转发访问。

## 5. 页面操作

1. “配比策略”填写标准 Parquet 输入、OBS 输出根目录和配比节点数。
2. 选择 QuaDMix、随机配比及任意数量的人工配比。自定义策略先上传 OBS，再填写 `.py` 地址。
3. “训练配置”填写独立的训练节点数、NanoChat 代码/模型地址及离线资源地址。
4. “评测配置”选择内置评测项；也可填写已上传评测资源的 OBS 目录。
5. “确认提交”检查输入输出后点击“一键启动实验”。
6. 页面每 3 秒刷新状态。第一个作业失败时第二个作业保持 `WAITING`，不会被提交；成功后第二个作业自动提交。

## 6. 接口

- `POST /api/v1/workflows`：创建一次两作业实验。
- `GET /api/v1/workflows`：列出实验及两个作业的进度。
- `GET /api/v1/workflows/{workflow_id}`：查询单个实验。

工作流记录保存在开发环境仓库的 `result/.workflows/`。ModelArts 鉴权只存在 API 服务端的 Python 文件中，不会返回到浏览器。

## 7. 切换节点数

直接在 UI 分别修改“配比作业节点数”和“训练评测作业节点数后”提交即可，无需改 YAML 或命令。当前支持 1–16 节点；例如配比 2 节点、训练 8 节点会创建两个规格相同但 `node_count` 分别为 2 和 8 的 ModelArts 作业。
