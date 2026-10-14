"""Retry scoring batches on OOM without skipping examples or changing scoring."""
from __future__ import annotations

import gc
import json
import os
from pathlib import Path


def is_memory_error(error):
    import torch
    # Do not retry generic HCCL failures, timeouts or invalid input as OOM.
    return isinstance(error, (MemoryError, torch.OutOfMemoryError)) or (
        isinstance(error, RuntimeError)
        and any(text in str(error).lower() for text in (
            'out of memory', 'not enough memory', "can't allocate memory",
        ))
    )


def _score_batch(core, indices, model, tokenizer, data, device, task_meta):
    """Keep device temporaries in a short-lived scope, including on exceptions."""
    tokens, metadata, boundaries = [], [], [0]
    for index in indices:
        sequences, starts, ends, kind, gold = core.prepare_example(
            index, data, tokenizer, task_meta, getattr(model, 'max_seq_len', None))
        tokens.extend(sequences)
        metadata.append((starts, ends, kind, gold))
        boundaries.append(len(tokens))
    inputs = core.stack_sequences(tokens, tokenizer.get_bos_token_id()).to(device)
    losses, predictions = core.forward_model(model, inputs)
    return [bool(core.judge_example(
        losses[boundaries[i]:boundaries[i + 1]],
        predictions[boundaries[i]:boundaries[i + 1]],
        inputs[boundaries[i]:boundaries[i + 1]], *meta,
    )) for i, meta in enumerate(metadata)]


def _record(event, rank):
    if rank != 0:
        return
    base = os.environ.get('NANOCHAT_BASE_DIR')
    if base:
        path = Path(base) / 'base_eval' / 'adaptive_batch.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + '\n')


def evaluate_task(model, tokenizer, data, device, task_meta, eval_batch_size=1):
    import torch
    import torch.distributed as dist
    from nanochat import core_eval as core

    required = ('prepare_example', 'stack_sequences', 'forward_model', 'judge_example')
    missing = [name for name in required if not callable(getattr(core, name, None))]
    if missing:
        raise RuntimeError('挂载的 NanoChat 版本不支持批量自适应，缺少接口：' + ', '.join(missing))
    if not data or eval_batch_size < 1:
        raise ValueError('评测数据不能为空，评测批量必须大于 0')
    distributed = dist.is_initialized()
    rank = dist.get_rank() if distributed else 0
    world = dist.get_world_size() if distributed else 1
    indices = list(range(rank, len(data), world))
    batch_size = int(eval_batch_size)
    offset = correct = 0
    label = task_meta.get('label', '评测集')
    # Allocate before scoring; collectives use only two integers, not a full
    # dataset-sized device tensor. All ranks, including idle ranks, participate.
    status = torch.zeros(2, dtype=torch.int64, device=device)
    totals = torch.zeros(2, dtype=torch.int64, device=device)
    if distributed:
        # Initialize communication buffers before forward-pass caches occupy
        # device memory. Communication failures themselves are not batch OOMs.
        dist.all_reduce(status, op=dist.ReduceOp.MAX)
    retries = 0
    with torch.no_grad():
        while True:
            chunk = indices[offset:offset + batch_size]
            answers, code, reason = [], 0, ''
            try:
                if chunk:
                    answers = _score_batch(core, chunk, model, tokenizer, data, device, task_meta)
            except Exception as error:
                code = 1 if is_memory_error(error) else 2
                reason = f'{type(error).__name__}: {error}'
            # Recovery happens OUTSIDE except: its traceback otherwise retains
            # the failed forward's tensors and prevents releasing their memory.
            if code:
                gc.collect()
                if device.type in ('cuda', 'npu'):
                    getattr(torch, device.type).empty_cache()
                print(f'[评测][rank {rank}][{label}] {reason}', flush=True)
            status[0], status[1] = code, int(bool(chunk))
            if distributed:
                dist.all_reduce(status, op=dist.ReduceOp.MAX)
            global_code, active = status.tolist()
            if global_code == 2:
                raise RuntimeError(f'{label} 评测失败（非内存不足，不重试）：{reason or "其他进程报错，请查看对应 rank 日志"}')
            if global_code == 1:
                if batch_size == 1:
                    _record({'task': label, 'status': 'failed', 'batch_size': 1, 'reason': 'oom'}, rank)
                    raise RuntimeError(f'{label} 评测批量已降至 1，仍内存不足；未跳过样本。'
                                       '请检查单题长度、选项数量、模型大小或设备剩余内存。'
                                       + (f' 原因：{reason}' if reason else ' 详见其他 rank 的 OOM 日志。'))
                next_size = max(1, batch_size - 2)
                event = {'task': label, 'status': 'retry', 'from': batch_size, 'to': next_size}
                retries += 1
                _record(event, rank)
                if rank == 0:
                    print(f'[评测自动降批量][{label}] 内存不足：{batch_size} → {next_size}；'
                          '所有进程重试当前批次，已完成样本保留，不跳过样本。', flush=True)
                batch_size = next_size
                continue
            if not active:
                break
            correct += sum(answers)
            offset += len(chunk)
    totals[0], totals[1] = correct, offset
    if distributed:
        dist.all_reduce(totals, op=dist.ReduceOp.SUM)
    total_correct, total_seen = totals.tolist()
    if total_seen != len(data):
        raise RuntimeError(f'{label} 评测样本计数异常：{total_seen} / {len(data)}')
    _record({'task': label, 'status': 'completed', 'initial_batch_size': eval_batch_size,
             'final_batch_size': batch_size, 'samples': total_seen, 'retries': retries}, rank)
    return total_correct / total_seen
