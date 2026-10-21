"""Read-only checks for NanoChat framework and global-rank data coverage."""
import argparse
import ast
from collections import Counter
import hashlib
import os
from pathlib import Path
import socket
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nanochat_mid_compare.distributed_runtime import LEGACY_ROW_GROUP_LOADER_SHA256


PINNED_LOADER_SHA256 = "18e26e485e179edee763278d90c1b2b3b58f63f595e93bd4b6a714890d1d5acb"


def row_coverage(shards, world_size):
    """Compare per-file and global ownership of nonempty row groups."""
    old_rows, global_rows = [0] * world_size, [0] * world_size
    offset = 0
    for rows in shards:
        for index, count in enumerate(rows):
            old_rows[index % world_size] += count
            global_rows[offset % world_size] += count
            offset += 1
    return old_rows, global_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="实际使用的 NanoChat 框架目录")
    parser.add_argument("--data", type=Path, required=True, help="实际使用的 random_data 目录")
    parser.add_argument("--world-size", type=int, default=24)
    args = parser.parse_args()
    if args.world_size < 1:
        parser.error("world-size 必须为正整数")

    print("检查主机：", socket.gethostname())
    print("框架目录：", args.repo)
    print("训练数据：", args.data)
    for key in ("MA_NUM_HOSTS", "VC_TASK_INDEX", "NNODES", "NODE_RANK", "MASTER_ADDR",
                "HCCL_SOCKET_IFNAME", "HCCL_IF_IP", "HCCL_CONNECT_TIMEOUT"):
        print(f"{key}={os.environ.get(key, '(未设置)')}")
    print("以上是当前检查环境；Notebook 的环境变量不能代表训练容器。")

    source = (args.repo / "nanochat/dataloader.py").read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    tree = ast.parse(source.decode("utf-8-sig"))
    loader = next((node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == "_document_batches"), None)
    global_marker = loader is not None and any(
        isinstance(node, ast.Name) and node.id == "total_row_groups" for node in ast.walk(loader))
    print("加载器 SHA256：", digest)
    print("与 README 固定版本加载器完全一致：", digest == PINNED_LOADER_SHA256)
    compatible_legacy = digest == LEGACY_ROW_GROUP_LOADER_SHA256
    print("检测到全局行组分配结构线索：", global_marker)
    print("当前项目训练入口会适配的已知旧加载器：", compatible_legacy)

    import pyarrow.parquet as pq
    files = sorted(args.data.glob("*.parquet"))
    if len(files) < 2:
        raise ValueError("至少需要一个训练分片及最后一个验证分片；请核对实际挂载路径。")
    groups, distribution = [], Counter()
    for path in files[:-1]:
        meta = pq.read_metadata(path)
        if "text" not in meta.schema.names:
            raise ValueError(f"缺少 text 列：{path}")
        groups.append([meta.row_group(index).num_rows for index in range(meta.num_row_groups)])
        distribution[meta.num_row_groups] += 1
    old_rows, global_rows = row_coverage(groups, args.world_size)
    old_missing = [rank for rank, rows in enumerate(old_rows) if not rows]
    global_missing = [rank for rank, rows in enumerate(global_rows) if not rows]
    print("训练分片数：", len(groups), "；未计入训练的验证分片：", files[-1].name)
    print("训练分片行组数分布（行组数: 文件数）：", dict(sorted(distribution.items())))
    print("训练行组总数：", sum(map(len, groups)))
    print("旧式逐文件分配下没有行的 rank：", old_missing)
    print("全局行组分配下没有行的 rank：", global_missing)
    for rank in range(args.world_size):
        print(f"rank {rank:2d}: 旧式行数={old_rows[rank]}, 全局行数={global_rows[rank]}")
    if global_missing:
        print("需处理：训练行组无法覆盖全部 rank，请为目标卡数重新准备数据。")
    elif not (global_marker or compatible_legacy):
        print("需处理：未识别到全局分片结构，先核对并更新实际框架，勿直接启动完整训练。")
    else:
        print("源码结构和元数据初筛通过；自定义加载器仍需确认其实际分片逻辑。")
    print("本检查不读取正文，不验证内容有效性、读取性能或 NPU/HCCL 通信；不会修改输入。")
    return 2 if global_missing or not (global_marker or compatible_legacy) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, SyntaxError, ImportError) as error:
        raise SystemExit("检查未完成：" + str(error)) from None
