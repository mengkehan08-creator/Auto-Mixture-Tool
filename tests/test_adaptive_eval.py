"""OOM injection tests: retries preserve sample coverage and metric semantics."""
import json
import multiprocessing
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

torch = pytest.importorskip('torch')
from nanochat_mid_compare.adaptive_eval import evaluate_task, is_memory_error


def core_module(calls, limit, failure=None):
    core = ModuleType('nanochat.core_eval')
    core.prepare_example = lambda index, *args: ([[index + 1]], [0], [1], 'multiple_choice', index % 2)
    core.stack_sequences = lambda tokens, pad: torch.tensor(tokens)

    def forward(model, inputs):
        calls.append(len(inputs))
        if failure:
            raise failure
        if len(inputs) > limit:
            raise RuntimeError('NPU out of memory. Tried to allocate 6 GiB')
        return torch.zeros_like(inputs), torch.zeros_like(inputs)

    core.forward_model = forward
    core.judge_example = lambda loss, pred, inputs, start, end, kind, gold: gold == 0
    return core


def run_task(core, count=35, batch=16):
    package = ModuleType('nanochat')
    package.core_eval = core
    with patch.dict(sys.modules, {'nanochat': package, 'nanochat.core_eval': core}):
        return evaluate_task(object(), SimpleNamespace(get_bos_token_id=lambda: 0),
                             list(range(count)), torch.device('cpu'), {'label': 'test'}, batch)


def test_decreases_by_two_and_counts_every_sample_once(tmp_path, monkeypatch):
    monkeypatch.setenv('NANOCHAT_BASE_DIR', str(tmp_path))
    calls = []
    assert run_task(core_module(calls, 12)) == 18 / 35
    assert calls == [16, 14, 12, 12, 11]
    events = [json.loads(line) for line in (tmp_path / 'base_eval/adaptive_batch.jsonl').read_text().splitlines()]
    assert [event['to'] for event in events if event['status'] == 'retry'] == [14, 12]
    assert events[-1]['final_batch_size'] == 12
    assert events[-1]['samples'] == 35


@pytest.mark.parametrize('start,sequence', [(16, [16, 14, 12, 10, 8, 6, 4, 2, 1]), (3, [3, 1]), (1, [1])])
def test_retries_down_to_one_then_stops(start, sequence, tmp_path, monkeypatch):
    monkeypatch.setenv('NANOCHAT_BASE_DIR', str(tmp_path))
    calls = []
    with pytest.raises(RuntimeError, match='已降至 1，仍内存不足'):
        run_task(core_module(calls, 0), batch=start)
    assert calls == sequence


def test_size_one_can_succeed_and_non_oom_never_retries(tmp_path, monkeypatch):
    monkeypatch.setenv('NANOCHAT_BASE_DIR', str(tmp_path))
    calls = []
    assert run_task(core_module(calls, 1), count=20, batch=4) == .5
    assert calls[:3] == [4, 2, 1] and calls.count(1) == 20
    calls = []
    with pytest.raises(RuntimeError, match='非内存不足.*bad shape'):
        run_task(core_module(calls, 16, ValueError('bad shape')))
    assert calls == [16]


def test_late_oom_keeps_finished_batches(tmp_path, monkeypatch):
    monkeypatch.setenv('NANOCHAT_BASE_DIR', str(tmp_path))
    core = core_module([], 100)
    calls = []
    forward = core.forward_model
    def fail_long_batch(model, inputs):
        first = int(inputs[0, 0])
        calls.append((first, len(inputs)))
        if first > 4 and len(inputs) > 2:
            raise torch.OutOfMemoryError('out of memory')
        return forward(model, inputs)
    core.forward_model = fail_long_batch
    assert run_task(core, count=9, batch=4) == 5 / 9
    assert calls == [(1, 4), (5, 4), (5, 2), (7, 2), (9, 1)]


def test_oom_during_input_transfer_also_retries(tmp_path, monkeypatch):
    monkeypatch.setenv('NANOCHAT_BASE_DIR', str(tmp_path))
    core = core_module([], 100)
    sizes = []
    def stack(tokens, pad):
        def transfer(device):
            sizes.append(len(tokens))
            if len(tokens) > 2:
                raise MemoryError('input allocation failed')
            return torch.tensor(tokens)
        return SimpleNamespace(to=transfer)
    core.stack_sequences = stack
    assert run_task(core, count=5, batch=4) == 3 / 5
    assert sizes == [4, 2, 2, 1]


@pytest.mark.parametrize('error,expected', [
    (torch.OutOfMemoryError(), True), (MemoryError(), True),
    (RuntimeError("DefaultCPUAllocator: can't allocate memory"), True),
    (RuntimeError('HCCL barrier failed'), False), (RuntimeError('timeout'), False),
    (ValueError('out of memory field is missing'), False),
])
def test_memory_error_detection(error, expected):
    assert is_memory_error(error) == expected


def test_install_wraps_adaptive_evaluator_once():
    from nanochat_mid_compare.offline_base_eval import install_offline_eval
    scripts = ModuleType('scripts')
    scripts.base_eval = SimpleNamespace(evaluate_task=lambda *args: None)
    with patch.dict(sys.modules, {'scripts': scripts}), patch('nanochat_mid_compare.offline_base_eval.prepare_tokenizer_runtime'):
        install_offline_eval()
        first = scripts.base_eval.evaluate_task
        install_offline_eval()
    assert first.__wrapped__ is evaluate_task
    assert scripts.base_eval.evaluate_task is first


def distributed_worker(rank, world, rendezvous, output, count, failure, shared=None, barrier=None):
    from contextlib import ExitStack
    from datetime import timedelta
    import os
    from pathlib import Path
    import torch.distributed as dist
    os.environ['NANOCHAT_BASE_DIR'] = output
    context = ExitStack()
    if shared is None:
        dist.init_process_group('gloo', init_method=rendezvous, rank=rank, world_size=world,
                                timeout=timedelta(seconds=30))
    else:
        # Exercise the same rank protocol via real processes even in CPU builds
        # whose Gloo transport is unavailable. This is not an HCCL test.
        def reduce(tensor, op):
            for i, value in enumerate(tensor.tolist()):
                shared[rank * 2 + i] = value
            barrier.wait(timeout=20)
            operation = max if op == dist.ReduceOp.MAX else sum
            values = [operation(shared[r * 2 + i] for r in range(world)) for i in range(2)]
            barrier.wait(timeout=20)
            tensor[:] = torch.tensor(values)
        for name, value in (('is_initialized', lambda: True), ('get_rank', lambda: rank),
                            ('get_world_size', lambda: world), ('all_reduce', reduce)):
            context.enter_context(patch.object(dist, name, value))
    calls = []
    try:
        # Only rank 1 OOMs: every rank must roll back that batch and reduce.
        limit = 0 if failure == 'oom' else 2
        error = ValueError('invalid sample') if failure == 'other' else None
        core = core_module(calls, limit if rank == 1 else 100, error if rank == 1 else None)
        try:
            result = {'accuracy': run_task(core, count=count, batch=4)}
        except RuntimeError as exc:
            result = {'error': str(exc)}
        result['calls'] = calls
        (Path(output) / f'rank-{rank}.json').write_text(json.dumps(result), encoding='utf-8')
    finally:
        context.close()
        if shared is None:
            dist.destroy_process_group()


@pytest.mark.parametrize('count,failure', [(19, ''), (1, ''), (19, 'oom'), (19, 'other')])
@pytest.mark.parametrize('backend', ['simulated', 'gloo'])
def test_distributed_ranks_retry_together_without_skips_or_hang(tmp_path, count, failure, backend):
    if backend == 'gloo':
        if not torch.distributed.is_gloo_available():
            pytest.skip('Gloo unavailable in this runtime')
        try:
            torch.distributed.ProcessGroupGloo.create_device(hostname='127.0.0.1')
        except RuntimeError as exc:
            if 'unsupported gloo device' not in str(exc):
                raise
            pytest.skip('This PyTorch build has no working Gloo transport')
    ctx = multiprocessing.get_context('spawn')
    shared = ctx.Array('q', 4) if backend == 'simulated' else None
    barrier = ctx.Barrier(2) if shared is not None else None
    rendezvous = (tmp_path / 'rendezvous').as_uri()
    processes = [ctx.Process(target=distributed_worker,
                             args=(rank, 2, rendezvous, str(tmp_path), count, failure, shared, barrier)) for rank in range(2)]
    for process in processes:
        process.start()
    try:
        for process in processes:
            process.join(timeout=50)
        assert all(not process.is_alive() for process in processes), 'distributed evaluation hung'
        assert all(process.exitcode == 0 for process in processes)
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
    results = [json.loads((tmp_path / f'rank-{rank}.json').read_text(encoding='utf-8')) for rank in range(2)]
    if not failure:
        assert all(result['accuracy'] == ((count + 1) // 2) / count for result in results)
        if count > 1:
            assert all(result['calls'][:2] == [4, 2] for result in results)
    else:
        assert all('error' in result for result in results)
        if failure == 'oom':
            assert all('已降至 1' in result['error'] for result in results)
        else:
            assert all(result['calls'] == [4] for result in results)
