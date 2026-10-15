# ModelArts 节点扩缩容说明

本文说明如何通过一个参数，把同一条流水线运行在2到16个ModelArts节点上。
配置支持的扩缩容边界是：**`NODE_COUNT=1..16`，每个节点固定8张NPU**。
配置支持不等于已完成所有规模的 Ascend/HCCL 实测。训练还必须满足本文的
全局 batch 整除条件；3、5、7 等节点数可能需要显式设置全局 batch。

## 1. 节点数与卡数

设节点数为 `N`，每节点 NPU 数为 `8`：

```text
QuaDMix/NanoChat 全局卡数 = N × 8
NanoChat world size       = N × 8
```

ModelArts 提交脚本把 `job_data["spec"]["resource"]["node_count"]` 写入作业。
作业启动
后，ModelArts 应向每个节点注入：

```text
MA_NUM_HOSTS=N
VC_TASK_INDEX=当前节点编号（0..N-1）
VC_WORKER_HOSTS=全部训练节点地址
```

QuaDMix 使用前两个变量分配代理实验；NanoChat 使用统一的
`nanochat_mid_compare/distributed_runtime.py` 解析启动配置。它也支持显式
`NNODES/NODE_RANK/MASTER_ADDR/MASTER_PORT`，以及 Climb 验证过的
ModelArts StatefulSet 主机名和 `/etc/hosts` 回退。缺少或冲突的节点编号会直接
报错，不会把所有节点默认成 node 0。多节点必须使用同一个唯一 `AMT_RUN_ID`。

## 2. 每次改变节点数需要修改的字段

### 修改节点数：`modelarts_training_job.py` 的 `NODE_COUNT`

```python
NODE_COUNT = 目标节点数
```

例如四节点：

```python
NODE_COUNT = 4
```

如果新的节点数量仍使用相同的“单节点 8 卡”规格，`flavor_id` 不需要
修改。只有切换了单节点资源规格或资源池时，才修改：

```python
job_data["spec"]["resource"]["flavor_id"] = "新的单节点规格ID"
job_data["spec"]["resource"]["pool_id"] = "能够提供目标节点数的资源池ID"
```

提交脚本会自动把该值写入ModelArts `node_count`、运行时节点数校验和带时间戳
的唯一作业名，不需要再同步修改其他节点数字段。

### 保持不变：`examples/configs/modelarts_pipeline.yaml`

保持自动读取平台节点数：

```yaml
algorithm_config:
  algorithm_nodes: auto
```

调整代理实验数：

```yaml
algorithm_config:
  num_experiments: <代理实验数>
```

最低要求为 `num_experiments >= N`，否则有节点没有实验，任务会主动失败。为了
让每个节点的 8 张 NPU 都有一轮实验，建议：

```text
num_experiments >= N × 8
```

最好使用 `N × 8` 的整数倍，使每个节点负载相同。`num_experiments` 越大，参数
空间覆盖越充分，但代理训练时间、NPU 费用和OBS临时结果也会增加；它不保证最终
配比一定更好。

默认仍运行16个代理实验，以保证不同节点规模使用同一组QuaDMix实验进行可比测试。
节点数超过2时，QuaDMix阶段不会占满所有NPU；NanoChat阶段仍使用全部节点和全部
NPU。如果目标是提高QuaDMix代理实验覆盖率，可另外把 `num_experiments` 调成
`NODE_COUNT × 8`，但这会改变实验数量和计算成本，不属于一键扩缩容参数。

## 3. 支持配置表

| 节点数 | 总NPU数 | 唯一修改 |
|---:|---:|---|
| 2 | 16 | `NODE_COUNT=2` |
| 3 | 24 | `NODE_COUNT=3` |
| 4 | 32 | `NODE_COUNT=4` |
| 5 | 40 | `NODE_COUNT=5` |
| 6 | 48 | `NODE_COUNT=6` |
| 7 | 56 | `NODE_COUNT=7` |
| 8 | 64 | `NODE_COUNT=8` |
| 9 | 72 | `NODE_COUNT=9` |
| 10 | 80 | `NODE_COUNT=10` |
| 11 | 88 | `NODE_COUNT=11` |
| 12 | 96 | `NODE_COUNT=12` |
| 13 | 104 | `NODE_COUNT=13` |
| 14 | 112 | `NODE_COUNT=14` |
| 15 | 120 | `NODE_COUNT=15` |
| 16 | 128 | `NODE_COUNT=16` |

例如从两节点改为八节点，只修改：

```python
NODE_COUNT = 8
```

以下字段保持为每节点卡数，不要改成全局卡数：

```yaml
algorithm_config:
  npu_devices: 8

trainer_config:
  npu_devices: 8

executor_config:
  device_count: 8
```

错误示例：八节点时把 `npu_devices` 写成 `64`。这会让每个节点尝试访问
0..63 号设备，而不是表示全局64卡。

## 4. 自动完成的行为

改变节点数后，不需要修改 Python 或 Shell 代码：

- QuaDMix 从 `MA_NUM_HOSTS` 获取节点数；
- 节点 `r` 执行实验 `r, r+N, r+2N, ...`；
- 每个节点把代理结果写入当前作业独立的OBS协调目录；
- worker-0 收齐全部结果后执行 LightGBM、最优搜索和最终采样；
- 其他节点下载 worker-0 生成的 `sampled_dataset`；
- NanoChat 自动设置 `nnodes=N`、`nproc_per_node=8` 和
  `world_size=N×8`；
- 训练和评估使用不同的 rendezvous 端口；同作业内评估前，通过节点网络
  同步 node 0 保存的最新模型权重和 metadata，并验证大小、SHA-256 和作业标识；
- 每个节点确认文件完整后才启动评估；任何节点同步失败或超时都使作业失败；
- 接收的评估模型放在节点私有缓存中，不把临时文件或重复权重上传到 OBS；
- 只有全局主节点生成最终报告和主checkpoint。
- NanoChat 中的大型 AdamW 参数在首维不能整除 `world_size` 时自动补零分片，
  all-gather 后裁掉补齐部分，因此3、5、6等非2次幂节点数也可运行。
- 切换节点数时默认 `load_optimizer: false`：加载基础模型权重，但重新初始化与
  当前 `world_size` 匹配的优化器状态，避免2048/4096分片形状冲突。

提交脚本按节点数和当前时间自动生成唯一作业名，并用该名称更新OBS协调目录，
避免旧的 `_SUCCESS` 标记污染新任务。

## 5. 提交前检查

先检查脚本语法：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
python3 -m py_compile modelarts_training_job.py
```

人工确认脚本中的：

```text
NODE_COUNT = 2到16之间的目标节点数
job_data["algorithm"]["environments"]["NUM_NPU"] = "8"
```

然后确认镜像和平台满足：

- 每节点确实有8张NPU；
- 所有节点都能读取8个ModelArts输入挂载；
- 镜像包含 `moxing` 或 `obsutil`；
- 节点之间允许使用训练、评估及检查点同步端口（默认29500、29501、29502）；
- ModelArts正确注入 `MA_NUM_HOSTS`、`VC_TASK_INDEX` 和
  `VC_WORKER_HOSTS`；
- OBS输出目录有足够空间，且每次运行使用唯一作业名。

确认后提交：

```bash
python3 modelarts_training_job.py
```

## 6. 日志验收

四节点、32个代理实验时，每个节点应打印8个不同的全局实验编号：

```text
[Distributed] node-0/4: experiments=[0, 4, 8, ..., 28]
[Distributed] node-1/4: experiments=[1, 5, 9, ..., 29]
[Distributed] node-2/4: experiments=[2, 6, 10, ..., 30]
[Distributed] node-3/4: experiments=[3, 7, 11, ..., 31]
[Distributed] gathered 32 proxy results
```

NanoChat 应打印或包含等价参数：

```text
--nnodes=4
--nproc_per_node=8
--node_rank=0|1|2|3
```

如果某节点没有代理实验，增加 `num_experiments`；如果一直等待 `_SUCCESS`，检查
对应节点是否失败、OBS客户端是否可用以及各节点的 `AMT_RUN_OBS_URI` 是否相同。

### 同一模型跨节点训练与评估

平台训练阶段的 `run_stem_experiment.sh` 和快速验证入口
`run_quadmix_only.sh` 会让所有节点参与同一次 NanoChat 训练；训练完成后，
node 0 把同一个 `model_<step>.pt` 和 `meta_<step>.json` 同步给其他节点，
评估明确指定这一步的检查点。每个全局 rank 分配不同的评估样本，已有的
`adaptive_eval.py` 汇总正确数和样本数；只有全局 rank 0 写汇总结果。

各节点应出现相同的检查点步骤，例如：

```text
[Distributed] node-0/2: checkpoint step=15 verified
[Distributed] node-1/2: checkpoint step=15 verified
```

`AMT_CHECKPOINT_TIMEOUT` 默认 300 秒，必须为正且有限。检查点同步另外按
4 MiB/s 的传输速度下限增加与文件大小对应的时间预算；torchrun rendezvous
也使用显式超时。HCCL 运算和平台作业最大运行时间仍由各自配置控制。

ModelArts 采样阶段按 **训练节点数 × 每节点设备数** 准备 Parquet 行组，
与代理实验的采样节点数可以不同。复用旧数据时，训练前按 `dev-data-mix` 的全局行组序列检查每个 rank 是否都有
非空行组，防止某些进程空转而其他进程等待梯度同步。行组可以跨训练文件累计；
文件按名称排序，最后一个文件保留为验证集。损坏文件或非字符串 `text` 列在训练前报错。
启用训练中的 `eval_every` 时，验证 shard 也必须覆盖所有 rank；默认的
dummy validation shard 仅用于禁用这一周期验证时的格式兼容。

CPU 验证入口（需要允许本机回环网络）：

```bash
.venv/bin/python -m pytest -q tests/test_nanochat_distributed.py tests/test_adaptive_eval.py
```

测试使用两个独立 `torchrun` 进程组模拟两台节点，在 CPU/Gloo 上训练同一个
小模型、把检查点同步到不同目录并进行分布式评估；权重和全局指标与单进程
基准比对。也覆盖同步损坏、作业标识冲突、节点缺失和数据行组不足。
这确认启动、同步和指标汇总链路；NanoChat 实际模型、Ascend/HCCL 和
ModelArts 网络环境仍需接入真实设备后验收。QuaDMix 的可配置规模 NanoChat
代理模型尚未接入，本节的训练入口使用挂载的 NanoChat 基础模型。

### 单作业代理训练与评估的验收

代理阶段采用实验并行：同一个 ModelArts 作业内，节点 `r` 运行全局编号
`r, r+N, r+2N, ...` 的独立代理模型，并在本节点完成这些模型的验证。
每个代理模型仍由单张设备训练；节点内动态队列可以同时使用多张设备。

全局实验编号必须贯穿采样、预算子集随机种子、模型初始化、Token 临时缓存、
`exp_XXXX/`、`meta.json` 和评估记录。固定参数和 seed 时，改变节点数不应改变
某个实验的输入子集与初始化种子。真实 NPU 浮点计算仍可能存在数值差异。

节点 0 按全局编号收集全部训练和验证指标。汇总会拒绝重复、缺失、归属错误的
实验编号、不同的参数摘要、节点数和评估任务集合，也拒绝失败实验、非有限的
训练/评估指标，以及与实验清单不符的实际参数，然后执行回归搜索与最终采样。

训练开始前，各节点发布运行清单并等待节点 0 对齐：数据 Schema、分片相对路径
与大小、采样元数据摘要、Tokenizer、验证 Token/Mask/任务标签、模型结构、seed、
训练预算和参数集合必须一致。平台作业标识 `AMT_RUN_ID`（缺省使用 `MA_VJ_NAME`）
也纳入核对；CLI 会校验 `AMT_EXPECTED_NODES` 与实际节点数。配比和训练共用节点
身份解析：支持 `NNODES` / `MA_NUM_HOSTS`，缺省回退到 `AMT_EXPECTED_NODES`；
节点编号支持 `NODE_RANK` / `MA_NODE_RANK` / `VC_NODE_RANK` / `VC_TASK_INDEX`，
缺省从 `<作业名>-worker-N` 主机名取得。命令行参数与环境变量冲突时直接报错，
不会把缺少编号的多节点作业默认为节点 0。配比通过 OBS 协调，不要求训练用的
`MASTER_ADDR`、`MASTER_PORT` 或主节点 DNS 解析。

数据摘要复用已加载的采样元数据，不重新扫描全部训练文本；数据目录有
`manifest.json` 时也比较其内容摘要。因此需使用不可变的 OBS 数据版本：在不改变
元数据和文件大小的情况下原地替换文本，不能仅靠此摘要检测。

协调目录包含所有节点的训练产物，各节点完成上传后才发布结果完成标记：

```text
<coordination-uri>/
├── run_manifest.json
├── manifests/node-<rank>.json / node-<rank>.json._READY / _SUCCESS
├── proxy_results/node-<rank>.json / node-<rank>._SUCCESS
├── proxy_results/all.json              # 按全局实验编号排序的完整指标
├── proxy_experiments/exp_XXXX/         # 所有节点的模型、索引、meta 和评估轨迹
├── failures/node-<rank>.json
└── final/                             # 最终采样集、参数与报告；不重复上传代理模型
```

每个实验的 `meta.json` 记录节点编号、运行摘要和 `artifact_uri`。最终采样集完成后
仍由其他节点下载 `final/sampled_dataset`，下游训练入口保持原有路径。
`obsutil` 后端的目录上传、下载均使用 `-flat`，复制目录内容，避免多套源目录名。

运行入口在数据加载前建立失败通知：数据、Tokenizer、验证文件、训练、汇总或
最终输出发生异常时，尽力写入协调目录的 `failures/node-<rank>.json`；等待中的
其他节点在下一次轮询时失败退出。节点内 worker 无通知退出时，收集器将缺失
实验标为失败，跨节点阶段不会把它们当作成功结果继续运行。节点被直接杀死或
OBS 读写失败时，仍依赖失败通知或协调超时；`--coordination-timeout` 必须为有限正数。
该上限分别用于输入对齐、指标汇总、最终产物等待和节点内动态 worker 执行。
动态 worker 无响应会结束缺失实验并回收进程；未知或重复实验编号会报错退出。
顺序训练、预采样和 OBS 客户端自身阻塞仍需平台作业超时兜底，协调轮询不能
强制中断这些调用。
每次新作业继续使用独立协调目录，不复用旧的成功或失败标记。

只验收代理阶段时，可以在同一云作业的所有节点运行算法脚本，使用相同的
Schema、数据、验证文件、Tokenizer、seed 和协调 URI，并让
`MA_NUM_HOSTS` / `VC_TASK_INDEX` 指定节点数及当前节点；无需启动下游 NanoChat
训练。脚本仍会在主节点汇总指标、搜索配比并导出采样集。

在已完成依赖安装和输入挂载的 ModelArts 容器中，各节点使用同一条命令：

```bash
python scripts/runners/run_essential_web_v1.py \
  --schema configs/schema_stem_quadmix_parquet.yaml \
  --preprocessed-dir /home/ma-user/modelarts/inputs/data_dir_0 \
  --val-set stem_v2 \
  --val-path /home/ma-user/modelarts/inputs/proxy_validation_dir_5/stem_v2_tokenized.pt \
  --tokenizer-path /home/ma-user/modelarts/inputs/quadmix_tokenizer_dir_4 \
  --distributed-nodes "$MA_NUM_HOSTS" --node-rank "$VC_TASK_INDEX" \
  --coordination-uri "$AMT_RUN_OBS_URI" \
  --seed 42 --num-experiments 16 --tiny-steps 15 \
  --num-search 1000 --device-type npu --npu-devices 8 \
  --output /home/ma-user/modelarts/outputs/output_dir_0/proxy_only
```

该命令是容器内启动命令，不创建 ModelArts 作业；提交时仍需为单个作业配置
`node_count`、镜像、资源池、OBS 输入输出和所有节点一致的唯一协调 URI。

本地回归命令（使用项目虚拟环境，需已有 pytest、PyTorch 和项目依赖）：

```bash
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  .venv/bin/python -m pytest -q \
  tests/test_distributed_proxy.py tests/test_distributed_proxy_execution.py
```

测试用两个独立进程模拟节点，以微型模型执行真实 CPU 训练、逐任务验证和
checkpoint 写出；五个实验分别分配为 `[0,2,4]` 与 `[1,3]`，并与单节点结果
对照采样索引、逐任务 loss 与模型权重，并检查两个节点的模型均已发布。
另有输入/预算不一致、无效指标、产物缺失、旧协调目录、节点身份缺失、动态
worker 乱序返回、进程异常退出、无响应超时和错误编号测试。该检查使用本地存储，
不能替代 ModelArts 环境变量、OBS 读写权限和真实 NPU 验收。

2026-10-13 本地验收：在 macOS ARM64、Python 3.12.14 / PyTorch 2.14.1 CPU 环境中，
分布式代理及相关配置、插件、评测和工作流回归共 154 项测试、15 项子测试通过。
Gloo 回环通信测试需要本机网络权限；本次在具备该权限的环境中验证通过。
空分片及不同挂载路径的输入摘要也已覆盖。真实 ModelArts、OBS 和 NPU 验收待执行。

## 7. 当前不支持的自动扩缩容

当前提交脚本把每节点卡数固定为8。如果需要改成每节点4卡、16卡或混合规格，不能
只修改 `job_data` 的 `node_count`。还需要统一修改提交脚本中的设备环境、YAML三处
设备数以及训练规格，并重新验证HCCL和batch size；这属于“改变单节点规格”，不是
本文所述的“改变节点数量”。


## 2026-10-14：训练验证迁移与验收

参考代码基线：QuaDMix `refactor/structure@2591a6d`、NanoChat
`dev-data-mix@6e5baa2`、Climb `main@3e3cebb`，以及本地 climbmix-ma 包。
部署到 OBS 时应记录这些版本及本工具实际部署的提交。容器启动前检查 NanoChat
训练参数、全局行组加载器和 DistMuonAdamW 的接口；默认分支或旧接口不能冒充此基线。

### 全局 batch 与实际训练量

每个优化步的全局 Token 数满足：

```text
world_size = training_nodes × devices_per_node
micro_tokens = world_size × device_batch_size × sequence_len
total_batch_size = micro_tokens × grad_accum_steps
num_iterations = ceil(token_budget / total_batch_size)
actual_tokens = num_iterations × total_batch_size
```

`training.total_batch_size` 可选，留空继承基础检查点；CLI 对应
`TRAIN_TOTAL_BATCH_SIZE`。它必须整除 `micro_tokens`，否则在启动训练前报错并给出
一个可用值，阻止 NanoChat 自动上调 batch 后悄悄增加训练量。
同一比较实验应保持共同的全局 batch、基础权重、冷优化器、数据打包方式和评测协议。
固定 Token 预算按完整优化步向上取整，额外 Token 少于一个全局 batch。

例如，序列长度 2048、单卡 batch 1、3 节点 × 8 卡时：

```yaml
training_nodes: 3
training:
  devices_per_node: 8
  device_batch_size: 1
  total_batch_size: 540672
  token_budget: 401395843
```

540672 适用于这个 3 节点作业。若比较 1/2/3/4 节点，1572864 是这些拓扑共同
兼容的 batch 示例，应在所有比较作业中一起设置。增加节点数不能消除模型单卡显存需求。

### 训练产物先于评测保存

`run_stem_experiment.sh`、`run_experiment.sh`、`run_quadmix_only.sh` 共用拓扑解析、
数据检查、预算计划与检查点记录。运行目录按节点隔离，基础模型、Tokenizer 和已准备
数据保持只读。日志目录另存 `dataset_stats.json`，不改写输入挂载的统计文件。
通用入口支持 QuaDMix/随机及原有质量基线；人工方案使用 STEM 入口。
历史捕获、回放及 `run_eval_only.sh` 等诊断入口尚未统一到这套多节点运行契约。

每次训练先写 `training_plan_<model_tag>.json`，成功后 node 0 在模型目录原子写入
`training_record.json`，包含明确的 step、model/meta SHA-256、实际训练量、梯度累积
次数、优化器初始化方式、采样统计摘要、训练文件及行组清单，以及框架和本工具运行源码的摘要。保存的 step/batch 与计划
不同会失败。独立评测的模型清单会校验并携带该记录，分析界面展示实际训练信息。
旧模型清单没有此记录时保留兼容，其实际训练量显示为未记录。

同作业评测同步 model/meta 到各节点的私有缓存并显式指定 step，随后检查训练进程
释放的 HBM。默认等待上限 120 秒、每卡至少 24576 MiB 可用（沿用 Climb 参考环境）：

```text
AMT_EVAL_SETTLE_TIMEOUT=120
AMT_EVAL_MIN_FREE_MIB=24576
```

不同卡型须按真实显存校准阈值；超过等待上限会报错并保留已训练模型。
`npu-smi` 不存在的 CPU 测试主机会跳过硬件检查；存在但输出不可解析时不会继续评测。
评测进程在未显式配置时使用 `HCCL_BUFFSIZE=100`。独立评测读取 INPUT 模型挂载，
不能用当前作业自己的 OUTPUT 挂载取回已有模型。

### 可复现的本地验证

```bash
NANOCHAT_TEST_REPO=/path/to/nanochat-npu-dev-data-mix \
.venv/bin/python -m pytest -q \
  tests/test_nanochat_training_runtime.py tests/test_nanochat_shell_execution.py \
  tests/test_nanochat_distributed.py tests/test_adaptive_eval.py \
  tests/test_training_token_budget.py
```

`NANOCHAT_TEST_REPO` 指向固定版本的真实 NanoChat checkout，启用实际 DistMuonAdamW
的 CPU/Gloo 数值测试：2/3 进程、连续 5 步、整除/不整除/空分片、小参数与 Muon 混合
更新，比较权重和动量，并拒绝不兼容的优化器状态。不设置时仅跳过该外部框架测试。
完整脚本测试只替换 Ascend 环境和加速器训练子进程，真实执行三个生产脚本的预算、
数据检查、布局和产物发布，验证输入资源不被修改。

CPU 验证通过后仍应进行 2 节点、4 节点的 10～20 步真实 NanoChat 短训练，再核对
同一 checkpoint 的 8/16/32-rank 评估样本覆盖和指标容差。Ascend/HCCL、平台网络、
HBM 释放及大文件同步的硬件验收不能由本地测试替代。


本次本机验收：规范 `tests/` 目录 519 项测试及 20 项子测试通过，包含真实
`dev-data-mix@6e5baa2` 优化器数值测试和完整脚本模拟。前端本次相关 9 项测试及
构建通过；完整前端套件 90/91 项通过，余下为已有 ResourceGuide 策略说明文案断言。
训练配置已检查桌面与 390px 窄屏布局。真实 Ascend/ModelArts 作业尚未在本机执行。
仓库根目录历史文件 `test_v4.2_implementation.py` 不符合 pytest 模块命名规则，
完整自动化回归使用 `pytest tests`。
