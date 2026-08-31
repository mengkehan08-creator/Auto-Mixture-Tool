# ModelArts 节点扩缩容说明

本文说明如何在不修改 Python 代码的情况下，把同一条流水线运行在 1、2、4、8
或更多 ModelArts 节点上。当前支持的扩缩容边界是：**节点数可变，每个节点固定
8 张 NPU**。

## 1. 节点数与卡数

设节点数为 `N`，每节点 NPU 数为 `8`：

```text
QuaDMix/NanoChat 全局卡数 = N × 8
NanoChat world size       = N × 8
```

ModelArts 提交脚本把 `MODELARTS_NODE_COUNT` 写入作业的 `node_count`。作业启动
后，ModelArts 应向每个节点注入：

```text
MA_NUM_HOSTS=N
VC_TASK_INDEX=当前节点编号（0..N-1）
VC_WORKER_HOSTS=全部训练节点地址
```

QuaDMix 使用前两个变量分配代理实验；NanoChat 还使用
`VC_WORKER_HOSTS` 建立 `torchrun` 多节点通信。

## 2. 每次改变节点数需要修改的字段

### 必须修改：`.env.modelarts`

```env
MODELARTS_NODE_COUNT=<目标节点数>
```

例如四节点：

```env
MODELARTS_NODE_COUNT=4
```

如果新的节点数量仍使用相同的“单节点 8 卡”规格，`MODELARTS_FLAVOR_ID` 不需要
修改。只有切换了单节点资源规格或资源池时，才修改：

```env
MODELARTS_FLAVOR_ID=<新的单节点规格ID>
MODELARTS_POOL_ID=<能够提供目标节点数的资源池ID>
```

### 必须检查：`examples/configs/modelarts_pipeline.yaml`

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

## 3. 推荐配置表

| 节点数 | 总NPU数 | 两个配置文件中的修改 | 建议最低代理实验数 | 实验分配 |
|---:|---:|---|---:|---|
| 1 | 8 | `NODE_COUNT=1` | 8 | 单节点本地汇总 |
| 2 | 16 | `NODE_COUNT=2` | 16 | 每节点8个 |
| 4 | 32 | `NODE_COUNT=4` | 32 | 每节点8个 |
| 8 | 64 | `NODE_COUNT=8` | 64 | 每节点8个 |

这里的 `NODE_COUNT` 是 `.env.modelarts` 中的 `MODELARTS_NODE_COUNT`。例如从
两节点改为八节点：

```env
MODELARTS_NODE_COUNT=8
```

```yaml
algorithm_config:
  num_experiments: 64
  algorithm_nodes: auto
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
- 只有全局主节点生成最终报告和主checkpoint。

提交脚本默认使用时间戳生成不同的作业名和OBS协调目录。不要为两次并行任务手动
指定相同的 `--job-name`，否则旧的 `_SUCCESS` 标记可能污染新任务。

## 5. 提交前检查

先生成请求，不创建任务：

```bash
cd /home/ma-user/work/Auto-Mixture-Tool
python3 modelarts_training_job.py --env-file .env.modelarts --dry-run
```

确认输出中的：

```text
spec.resource.node_count = 目标节点数
algorithm.environments.NUM_NPU = 8
```

然后确认镜像和平台满足：

- 每节点确实有8张NPU；
- 所有节点都能读取5个ModelArts输入挂载；
- 镜像包含 `moxing` 或 `obsutil`；
- 节点之间允许使用训练通信端口（默认29500）；
- ModelArts正确注入 `MA_NUM_HOSTS`、`VC_TASK_INDEX` 和
  `VC_WORKER_HOSTS`；
- OBS输出目录有足够空间，且每次运行使用唯一作业名。

确认后提交：

```bash
python3 modelarts_training_job.py --env-file .env.modelarts
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

## 7. 当前不支持的自动扩缩容

当前提交脚本把每节点卡数固定为8。如果需要改成每节点4卡、16卡或混合规格，不能
只修改 `MODELARTS_NODE_COUNT`。还需要统一修改提交脚本中的设备环境、YAML三处
设备数以及训练规格，并重新验证HCCL和batch size；这属于“改变单节点规格”，不是
本文所述的“改变节点数量”。
