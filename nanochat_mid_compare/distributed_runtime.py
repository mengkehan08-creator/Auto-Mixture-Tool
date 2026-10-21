"""One NanoChat job: resolve the node topology and relay rank-0 checkpoints.

ModelArts output mounts can be node-local. Evaluation must receive the exact
model/meta pair over the pod network before starting its own torchrun group.
This uses only the standard library, including on CPU test hosts.
"""
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time


# Verified backup_0810 loader; the training wrapper supplies global sharding.
LEGACY_ROW_GROUP_LOADER_SHA256 = "2add94bfac910f44d24781347c4e7f7a4433768aef8f28c75b0b38798eecc298"


def _integer(env, names, default=None):
    values = {name: int(env[name]) for name in names if env.get(name)}
    if len(set(values.values())) > 1:
        raise ValueError(f"Conflicting distributed settings: {values}")
    return next(iter(values.values()), default)


@dataclass(frozen=True)
class Topology:
    nodes: int
    rank: int
    devices: int
    master_addr: str
    master_port: int

    @property
    def world_size(self):
        return self.nodes * self.devices

    def torchrun_args(self, *, evaluation=False, timeout=300):
        port = self.master_port + int(evaluation)
        return [f"--nnodes={self.nodes}", f"--node_rank={self.rank}",
                f"--nproc_per_node={self.devices}", "--rdzv_backend=static",
                f"--rdzv_endpoint={self.master_addr}:{port}",
                f"--rdzv_conf=timeout={math.ceil(timeout)}"]


def resolve_node_identity(env=None, *, nodes=None, rank=None, hostname=None):
    """Resolve shared mixing/training identity without requiring a rendezvous."""
    env = dict(os.environ if env is None else env)
    if nodes is not None:
        env["--distributed-nodes"] = str(nodes)
    if rank is not None:
        env["--node-rank"] = str(rank)
    configured = _integer(env, ("AMT_EXPECTED_NODES",))
    nodes = _integer(env, ("--distributed-nodes", "NNODES", "MA_NUM_HOSTS"),
                     1 if configured is None else configured)
    expected = _integer(env, ("AMT_EXPECTED_NODES",), nodes)
    if nodes < 1 or nodes != expected:
        raise ValueError(f"Invalid node count: reported={nodes}, AMT_EXPECTED_NODES expected={expected}")
    rank = _integer(env, ("--node-rank", "NODE_RANK", "MA_NODE_RANK", "VC_NODE_RANK", "VC_TASK_INDEX"))
    if nodes > 1 and rank is None:
        host = (hostname or socket.gethostname()).split(".")[0]
        match = re.fullmatch(r"(.+)-worker-(\d+)", host)
        if not match:
            raise ValueError("Multi-node job requires NODE_RANK/VC_TASK_INDEX or a ModelArts worker hostname")
        rank = int(match[2])
    if nodes == 1 and rank is None:
        rank = 0
    if rank is None or not 0 <= rank < nodes:
        raise ValueError(f"Node rank {rank} is outside [0, {nodes})")
    return nodes, rank


def resolve_topology(devices, env=None, *, hostname=None, hosts_file="/etc/hosts"):
    env = os.environ if env is None else env
    if type(devices) is not int or devices < 1:
        raise ValueError(f"Invalid node/device count: devices={devices}")
    nodes, rank = resolve_node_identity(env, hostname=hostname)
    addresses = {env[key].strip() for key in ("MASTER_ADDR", "MA_MASTER_ADDR", "VC_MASTER_ADDR") if env.get(key)}
    if len(addresses) > 1:
        raise ValueError("Conflicting distributed master addresses")
    addr = next(iter(addresses), "")
    if not addr and env.get("VC_WORKER_HOSTS"):
        addr = env["VC_WORKER_HOSTS"].split(",")[0].strip()
    port = _integer(env, ("MASTER_PORT", "MA_MASTER_PORT", "VC_MASTER_PORT"), 29500)
    # Climb's verified fallback: ModelArts StatefulSet <service>-worker-N and
    # the pod's FQDN in /etc/hosts identify both rank and the worker-0 address.
    if nodes > 1 and not addr:
        host = (hostname or socket.gethostname()).split(".")[0]
        match = re.fullmatch(r"(.+)-worker-(\d+)", host)
        if not match:
            raise ValueError("Multi-node job requires NODE_RANK/VC_TASK_INDEX and MASTER_ADDR/VC_WORKER_HOSTS")
        derived_rank = int(match[2])
        if rank is not None and rank != derived_rank:
            raise ValueError("Node rank conflicts with the ModelArts worker hostname")
        rank = derived_rank
        if not addr:
            records = [line.split("#", 1)[0].split() for line in Path(hosts_file).read_text().splitlines()]
            fqdn = next((alias for record in records if host in record[1:]
                         for alias in record[1:] if alias.startswith(host + ".")), "")
            if not fqdn:
                raise ValueError(f"No ModelArts pod FQDN for {host} in {hosts_file}")
            master = f"{match[1]}-worker-0.{fqdn.split('.', 1)[1]}"
            addr = next((record[0] for record in records if master in record[1:]), "") or socket.gethostbyname(master)
    if nodes == 1:
        addr = addr or "127.0.0.1"
    if not addr or any(char.isspace() for char in addr) or ":" in addr or not 1 <= port <= 65533:
        raise ValueError("Invalid master address/port (reserve port+1 for eval and port+2 for checkpoint relay)")
    if nodes > 1 and not env.get("AMT_RUN_ID"):
        raise ValueError("Multi-node jobs require the same unique AMT_RUN_ID on every node")
    return Topology(nodes, rank, devices, addr, port)


def _digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def checkpoint_manifest(directory, topology, run_id, phase):
    weights = [(int(match[1]), path) for path in directory.glob("model_*.pt")
               if (match := re.fullmatch(r"model_(\d+)\.pt", path.name))]
    if not weights:
        raise ValueError(f"No trained model checkpoint in {directory}")
    step, weight = max(weights, key=lambda item: item[0])
    meta = directory / weight.name.replace("model_", "meta_").replace(".pt", ".json")
    files = []
    for path in (weight, meta):
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Incomplete model checkpoint: {path}")
        files.append({"name": path.name, "size": path.stat().st_size, "sha256": _digest(path)})
    json.loads(meta.read_text(encoding="utf-8"))
    return {"run_id": run_id, "phase": phase, "nodes": topology.nodes, "step": step, "files": files}


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Checkpoint synchronization timed out")
    return remaining


def _send_json(connection, value):
    connection.sendall(json.dumps(value, separators=(",", ":")).encode() + b"\n")


def _read_json(stream):
    line = stream.readline(65537)
    if not line or len(line) > 65536 or not line.endswith(b"\n"):
        raise ValueError("Incomplete checkpoint relay response")
    value = json.loads(line)
    if not isinstance(value, dict) or value.get("error"):
        raise ValueError(f"Checkpoint relay failed: {value}")
    return value


def _serve_checkpoint(directory, topology, manifest, timeout):
    condition = threading.Condition()
    ready, connected, errors = set(), set(), []
    deadline = time.monotonic() + timeout

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            rank = None
            try:
                self.connection.settimeout(min(30, _remaining(deadline)))
                request = _read_json(self.rfile)
                rank = request.get("rank")
                if (type(rank) is not int or not 1 <= rank < topology.nodes
                        or request.get("run_id") != manifest["run_id"]
                        or request.get("phase") != manifest["phase"]
                        or request.get("nodes") != topology.nodes):
                    raise ValueError("Checkpoint relay job/phase/node identity mismatch")
                with condition:
                    if rank in connected:
                        raise ValueError(f"Duplicate checkpoint receiver: node {rank}")
                    connected.add(rank)
                _send_json(self.connection, manifest)
                for item in manifest["files"]:
                    with (directory / item["name"]).open("rb") as source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            self.connection.settimeout(min(30, _remaining(deadline)))
                            self.connection.sendall(chunk)
                self.connection.settimeout(_remaining(deadline))
                if _read_json(self.rfile) != {"ready": True}:
                    raise ValueError(f"Node {rank} did not verify the checkpoint")
                with condition:
                    ready.add(rank)
                    condition.notify_all()
                    while len(ready) != topology.nodes - 1 and not errors:
                        condition.wait(_remaining(deadline))
                    if errors:
                        raise ValueError(errors[0])
                _send_json(self.connection, {"ready": True, "step": manifest["step"]})
            except Exception as exc:
                with condition:
                    errors.append(f"node {rank}: {exc}")
                    condition.notify_all()
                try:
                    _send_json(self.connection, {"error": str(exc)})
                except OSError:
                    pass

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

    with Server(("0.0.0.0", topology.master_port + 2), Handler) as server:
        # ModelArts overlay networks can blackhole full-size TCP segments.
        if hasattr(socket, "TCP_MAXSEG"):
            try:
                server.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_MAXSEG, 1200)
            except OSError:
                pass
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        thread.start()
        try:
            with condition:
                while len(ready) != topology.nodes - 1 and not errors:
                    condition.wait(_remaining(deadline))
                if errors:
                    raise ValueError("Checkpoint synchronization failed: " + errors[0])
        finally:
            with condition:
                if len(ready) != topology.nodes - 1:
                    errors.append("Checkpoint synchronization aborted")
                    condition.notify_all()
            server.shutdown()
            thread.join(timeout=2)
    if errors:
        raise ValueError("Checkpoint synchronization failed: " + errors[0])
    return manifest["step"]


def _receive_checkpoint(directory, topology, run_id, phase, timeout):
    deadline = time.monotonic() + timeout
    while True:
        try:
            connection = socket.create_connection((topology.master_addr, topology.master_port + 2),
                                                 timeout=min(5, _remaining(deadline)))
            break
        except OSError:
            time.sleep(min(0.1, _remaining(deadline)))
    temporary = []
    with connection, connection.makefile("rb") as stream:
        try:
            _send_json(connection, {"rank": topology.rank, "run_id": run_id, "phase": phase, "nodes": topology.nodes})
            connection.settimeout(min(30, _remaining(deadline)))
            manifest = _read_json(stream)
            if any(manifest.get(key) != value for key, value in (("run_id", run_id), ("phase", phase), ("nodes", topology.nodes))):
                raise ValueError("Checkpoint relay job/phase/node identity mismatch")
            files = manifest.get("files", [])
            if (len(files) != 2 or not re.fullmatch(r"model_(\d+)\.pt", files[0].get("name", ""))
                    or files[1].get("name") != files[0]["name"].replace("model_", "meta_").replace(".pt", ".json")
                    or int(Path(files[0]["name"]).stem.removeprefix("model_")) != manifest.get("step")):
                raise ValueError("Invalid checkpoint file manifest")
            deadline += sum(item["size"] for item in files) / (4 * 1024 * 1024)
            directory.mkdir(parents=True, exist_ok=True)
            for item in files:
                if type(item["size"]) is not int or item["size"] <= 0:
                    raise ValueError("Invalid checkpoint file size")
                with tempfile.NamedTemporaryFile(dir=directory, prefix=".relay-", delete=False) as output:
                    path = Path(output.name)
                    temporary.append((path, directory / item["name"]))
                    remaining = item["size"]
                    result = hashlib.sha256()
                    while remaining:
                        connection.settimeout(min(30, _remaining(deadline)))
                        chunk = stream.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError("Truncated checkpoint transfer")
                        remaining -= len(chunk)
                        result.update(chunk)
                        output.write(chunk)
                    if result.hexdigest() != item["sha256"]:
                        raise ValueError(f"Checkpoint checksum mismatch: {item['name']}")
            json.loads(temporary[1][0].read_text(encoding="utf-8"))
            for path, target in temporary:
                path.replace(target)
            _send_json(connection, {"ready": True})
            connection.settimeout(_remaining(deadline))
            if _read_json(stream) != {"ready": True, "step": manifest["step"]}:
                raise ValueError("Checkpoint barrier did not complete")
            return manifest["step"]
        finally:
            for path, _ in temporary:
                path.unlink(missing_ok=True)


def sync_checkpoint(directory, topology, run_id, phase, *, timeout=300):
    """Return the agreed step only after every node has verified its model/meta.

    No optimizer shards or unrelated files are sent. A missing peer, damaged
    file or conflicting job identity fails the job instead of scoring another
    model. The caller must pass the returned step explicitly to base_eval.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Checkpoint timeout must be positive and finite")
    directory = Path(directory)
    if topology.rank == 0:
        manifest = checkpoint_manifest(directory, topology, run_id, phase)
        if topology.nodes == 1:
            return manifest["step"]
        # Size-aware budget: at least 4 MiB/s for one streaming model copy.
        timeout += sum(item["size"] for item in manifest["files"]) / (4 * 1024 * 1024)
        return _serve_checkpoint(directory, topology, manifest, timeout)
    return _receive_checkpoint(directory, topology, run_id, phase, timeout)


def validate_training_data(directory, world_size, *, validation=False):
    """Match dev-data-mix's global row-group sequence and final val shard."""
    import pyarrow.parquet as pq
    import pyarrow as pa
    if type(world_size) is not int or world_size < 1:
        raise ValueError("WORLD_SIZE must be a positive integer")
    shards = sorted(Path(directory).glob("*.parquet"))
    if len(shards) < 2:
        raise ValueError("NanoChat needs training shards and a final validation shard")
    groups = []
    for path in shards:
        try:
            parquet = pq.ParquetFile(path)
            text = parquet.schema_arrow.field("text")
            if not (pa.types.is_string(text.type) or pa.types.is_large_string(text.type)):
                raise ValueError("text must be a string column")
            groups.append([parquet.metadata.row_group(i).num_rows for i in range(parquet.num_row_groups)])
        except (OSError, KeyError, ValueError) as exc:
            raise ValueError(f"Invalid training shard {path}: {exc}") from exc
    def covered(shard_groups):
        rows = [count for counts in shard_groups for count in counts]
        return {index % world_size for index, count in enumerate(rows) if count > 0}
    if len(covered(groups[:-1])) < world_size:
        raise ValueError(f"Training row groups cannot cover WORLD_SIZE={world_size}; reprepare data with --num-npu {world_size}")
    if validation and len(covered(groups[-1:])) < world_size:
        raise ValueError(f"Validation row groups cannot cover WORLD_SIZE={world_size}; prepare real validation data or disable eval_every")


def validate_framework(repo):
    """Check the pinned branch's executable interfaces without importing NPU code."""
    repo = Path(repo)
    trees = {name: ast.parse((repo / name).read_text(encoding="utf-8")) for name in
             ("scripts/mid_train.py", "scripts/base_eval.py", "nanochat/dataloader.py", "nanochat/optim.py")}
    def options(tree):
        return {arg.value for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"
                for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)}
    required = {"--loader", "--eval-benchmarks", "--total-batch-size", "--max-seq-len", "--load-optimizer"}
    missing = required - options(trees["scripts/mid_train.py"])
    if missing or "--eval-benchmarks" not in options(trees["scripts/base_eval.py"]):
        raise ValueError(f"NanoChat training/evaluation interface mismatch: {sorted(missing)}; use dev-data-mix")
    loader = next((node for node in ast.walk(trees["nanochat/dataloader.py"])
                   if isinstance(node, ast.FunctionDef) and node.name == "_document_batches"), None)
    if loader is None or (not any(isinstance(node, ast.Name) and node.id == "total_row_groups"
                                  for node in ast.walk(loader))
                          and _digest(repo / "nanochat/dataloader.py") != LEGACY_ROW_GROUP_LOADER_SHA256):
        raise ValueError("NanoChat requires dev-data-mix's global row-group loader or the verified legacy loader")
    optimizer = next((node for node in ast.walk(trees["nanochat/optim.py"])
                      if isinstance(node, ast.ClassDef) and node.name == "DistMuonAdamW"), None)
    methods = {node.name for node in optimizer.body if isinstance(node, ast.FunctionDef)} if optimizer else set()
    if not {"_reduce_adamw", "_compute_adamw", "_finish_gathers"} <= methods:
        raise ValueError("NanoChat DistMuonAdamW interface mismatch; use dev-data-mix")


def training_plan(checkpoint_dir, topology, device_batch_size, tokens, *, steps=0, total_batch_size=0):
    """Fix batch identity before NanoChat can silently round it up."""
    metadata = sorted(Path(checkpoint_dir).glob("meta_*.json"))
    if not metadata:
        raise ValueError(f"Missing base checkpoint metadata: {checkpoint_dir}")
    meta = json.loads(metadata[-1].read_text(encoding="utf-8"))
    return training_plan_from_metadata(meta, topology, device_batch_size, tokens,
                                       steps=steps, total_batch_size=total_batch_size)


def training_plan_from_metadata(meta, topology, device_batch_size, tokens, *, steps=0, total_batch_size=0):
    """Use the same arithmetic on the control plane and in the training container."""
    values = {"device_batch_size": device_batch_size, "tokens": tokens,
              "steps": steps, "total_batch_size": total_batch_size}
    if any(type(v) is not int or v < (1 if k in {"device_batch_size", "tokens"} else 0)
           for k, v in values.items()):
        raise ValueError("Training budget, batch and steps must be valid integers")
    sequence_len = meta.get("max_seq_len", meta.get("model_config", {}).get("sequence_len", 2048))
    batch = total_batch_size or meta.get("total_batch_size", 524288)
    if any(type(v) is not int or v < 1 for v in (sequence_len, batch)):
        raise ValueError("Checkpoint sequence length and total batch must be positive integers")
    context = meta.get("model_config", {}).get("sequence_len", sequence_len)
    if sequence_len > context:
        raise ValueError("Training sequence length exceeds the model context")
    micro_tokens = topology.world_size * device_batch_size * sequence_len
    if batch % micro_tokens:
        recommended = ((batch + micro_tokens - 1) // micro_tokens) * micro_tokens
        raise ValueError(f"total_batch_size={batch} is not divisible by WORLD_SIZE={topology.world_size} "
                         f"× device_batch_size={device_batch_size} × sequence_len={sequence_len} ({micro_tokens}). "
                         f"Set training.total_batch_size / TRAIN_TOTAL_BATCH_SIZE explicitly (e.g. {recommended}); "
                         "use the same global batch for comparison runs. Automatic budget inflation is disabled.")
    iterations = steps or (tokens + batch - 1) // batch
    actual = iterations * batch
    return {"nodes": topology.nodes, "devices_per_node": topology.devices, "world_size": topology.world_size,
            "device_batch_size": device_batch_size, "sequence_len": sequence_len,
            "total_batch_size": batch, "grad_accum_steps": batch // micro_tokens,
            "num_iterations": iterations, "token_budget": tokens, "actual_tokens": actual,
            "rounding_tokens": actual - tokens if not steps else None,
            "budget_mode": "steps" if steps else "tokens"}


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def setup_runtime(model_dir, runtime_dir, checkpoints_dir, eval_bundle=None):
    """Build NanoChat's writable layout without editing mounted input assets."""
    model, runtime = Path(model_dir).resolve(), Path(runtime_dir).resolve()
    if runtime == model or runtime.is_relative_to(model):
        raise ValueError("NanoChat runtime must be outside the input model directory")
    runtime.mkdir(parents=True, exist_ok=True)
    checkpoints = Path(checkpoints_dir).resolve()
    checkpoints.mkdir(parents=True, exist_ok=True)
    (runtime / "base_checkpoints").mkdir(exist_ok=True)
    assets = [("tokenizer", model / "tokenizer"), ("mid_checkpoints", checkpoints)]
    if eval_bundle:
        assets.append(("eval_bundle", Path(eval_bundle).resolve()))
    for name, source in assets:
        if not source.is_dir():
            raise ValueError(f"Missing NanoChat asset: {source}")
        link = runtime / name
        if link.exists() and not link.is_symlink():
            raise ValueError(f"Runtime asset is not a symlink: {link}")
        if link.is_symlink():
            link.unlink()
        link.symlink_to(source, target_is_directory=True)


def record_training(directory, topology, run_id, phase, plan, repo, data_dir=None):
    """Commit weights and actual training identity before evaluation starts."""
    if topology.rank != 0:
        return
    manifest = checkpoint_manifest(Path(directory), topology, run_id, phase)
    meta_path = Path(directory) / manifest["files"][1]["name"]
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if manifest["step"] != plan["num_iterations"] or meta.get("total_batch_size") != plan["total_batch_size"]:
        raise ValueError("Saved checkpoint step/batch differs from the training plan")
    actual_config = meta.get("user_config", {})
    for key, expected in (("max_seq_len", plan["sequence_len"]), ("device_batch_size", plan["device_batch_size"])):
        if key in actual_config and actual_config[key] != expected:
            raise ValueError(f"Saved checkpoint {key} differs from the training plan")
    plan = {**plan, **{key: actual_config[key] for key in ("loader", "load_optimizer") if key in actual_config}}
    repo = Path(repo)
    sources = {name: _digest(repo / name) for name in
               ("scripts/mid_train.py", "scripts/base_eval.py", "nanochat/dataloader.py", "nanochat/optim.py")
               if (repo / name).is_file()}
    try:
        revision = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=False).stdout.strip() or None
    except FileNotFoundError:
        revision = None
    record = {"version": 1, "status": "TRAINING_SUCCEEDED", "run_id": run_id, "phase": phase,
              "checkpoint": manifest, "training": plan, "framework_revision": revision,
              "framework_sources": sources,
              "tool_sources": {name: _digest(Path(__file__).with_name(name))
                               for name in ("distributed_runtime.py", "run_nanochat_mid_train.py", "global_row_groups.py")}}
    if data_dir is not None:
        import pyarrow.parquet as pq
        data = Path(data_dir)
        shards = []
        for path in sorted(data.glob("*.parquet")):
            metadata = pq.ParquetFile(path).metadata
            shards.append({"name": path.name, "size": path.stat().st_size,
                           "rows": metadata.num_rows, "row_groups": metadata.num_row_groups})
        stats = data.parent / "dataset_stats.json"
        record["dataset"] = {"shards": shards, "statistics_sha256": _digest(stats) if stats.is_file() else None}
    _write_json(Path(directory) / "training_record.json", record)
    return record


def wait_npu_settle(*, timeout=120, min_free_mib=24576):
    """Bounded, measured HBM release gate based on Climb's verified path."""
    if not math.isfinite(timeout) or timeout <= 0 or min_free_mib < 1:
        raise ValueError("NPU settle timeout and free-memory threshold must be positive")
    deadline = time.monotonic() + timeout
    while True:
        try:
            output = subprocess.run(["npu-smi", "info"], capture_output=True, text=True,
                                    timeout=min(15, _remaining(deadline)), check=True).stdout
        except FileNotFoundError:
            print("[Distributed] npu-smi unavailable; HBM gate skipped on this host", file=sys.stderr)
            return
        usages = [(int(used), int(total)) for used, total in re.findall(r"(\d+)\s*/\s*(\d+)", output)
                  if int(total) >= 16000]
        if not usages:
            raise RuntimeError("Cannot verify NPU memory from npu-smi output")
        if all(total - used >= min_free_mib for used, total in usages):
            print(f"[Distributed] HBM ready on {len(usages)} NPU(s)", file=sys.stderr)
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(f"NPU memory did not settle before evaluation: {usages}")
        time.sleep(min(5, deadline - time.monotonic()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("environment", "checkpoint", "check-data", "plan", "record", "settle", "layout"))
    parser.add_argument("--devices", type=int, default=int(os.environ.get("NUM_NPU", "8")))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--phase")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plan-file", type=Path)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--data-directory", type=Path)
    parser.add_argument("--checkpoint-dir", type=Path)
    parser.add_argument("--eval-bundle")
    parser.add_argument("--tokens", type=int)
    parser.add_argument("--steps", type=int, default=0)
    parser.add_argument("--total-batch-size", type=int, default=0)
    parser.add_argument("--device-batch-size", type=int, default=1)
    parser.add_argument("--validation", action="store_true")
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("AMT_CHECKPOINT_TIMEOUT", "300")))
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be positive and finite")
    topology = resolve_topology(args.devices)
    if args.action == "environment":
        for key, value in (("NNODES", topology.nodes), ("NODE_RANK", topology.rank),
                           ("MASTER_ADDR", topology.master_addr), ("MASTER_PORT", topology.master_port),
                           ("RANK_SIZE", topology.world_size)):
            print(f"export {key}={shlex.quote(str(value))}")
        for name, evaluation in (("TORCHRUN_ARGS", False), ("EVAL_TORCHRUN_ARGS", True)):
            print(f"{name}=({shlex.join(topology.torchrun_args(evaluation=evaluation, timeout=args.timeout))})")
    elif args.action == "checkpoint":
        if not args.directory or not args.phase:
            parser.error("checkpoint requires --directory and --phase")
        step = sync_checkpoint(args.directory, topology, os.environ.get("AMT_RUN_ID", ""), args.phase, timeout=args.timeout)
        print(f"[Distributed] node-{topology.rank}/{topology.nodes}: checkpoint step={step} verified", file=sys.stderr, flush=True)
        print(step)
    elif args.action == "check-data":
        if not args.directory:
            parser.error("check-data requires --directory")
        validate_training_data(args.directory, topology.world_size, validation=args.validation)
    elif args.action == "plan":
        if not args.directory or not args.output or args.tokens is None:
            parser.error("plan requires --directory, --output and --tokens")
        if args.repo:
            validate_framework(args.repo)
        plan = training_plan(args.directory, topology, args.device_batch_size, args.tokens,
                             steps=args.steps, total_batch_size=args.total_batch_size)
        _write_json(args.output, plan)
        for name, key in (("TOTAL_BATCH_SIZE", "total_batch_size"), ("MAX_SEQ_LEN", "sequence_len"),
                          ("NUM_ITERATIONS", "num_iterations")):
            print(f"{name}={plan[key]}")
        print(f"[Distributed] Training plan: {json.dumps(plan)}", file=sys.stderr, flush=True)
    elif args.action == "record":
        if not args.directory or not args.phase or not args.plan_file or not args.repo:
            parser.error("record requires --directory, --phase, --plan-file and --repo")
        record_training(args.directory, topology, os.environ.get("AMT_RUN_ID", ""), args.phase,
                        json.loads(args.plan_file.read_text(encoding="utf-8")), args.repo, args.data_directory)
    elif args.action == "settle":
        wait_npu_settle(timeout=float(os.environ.get("AMT_EVAL_SETTLE_TIMEOUT", "120")),
                        min_free_mib=int(os.environ.get("AMT_EVAL_MIN_FREE_MIB", "24576")))
    else:
        if not args.directory or not args.output or not args.checkpoint_dir:
            parser.error("layout requires --directory, --output and --checkpoint-dir")
        setup_runtime(args.directory, args.output, args.checkpoint_dir, args.eval_bundle)


if __name__ == "__main__":
    main()
