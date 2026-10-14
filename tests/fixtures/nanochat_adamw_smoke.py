"""Exercise the real NanoChat optimizer plus AMT padding against its reference."""
from datetime import timedelta
import sys

import torch
import torch.distributed as dist

sys.path.insert(0, sys.argv[1])
from nanochat import optim
from nanochat_mid_compare.run_nanochat_mid_train import patch_distributed_adamw, shard_layout

dist.init_process_group('gloo', timeout=timedelta(seconds=30))
rank, world = dist.get_rank(), dist.get_world_size()


class Completed:
    def get_future(self):
        future = torch.futures.Future()
        future.set_result(True)
        return future


def synchronous(fn):
    def call(*args, **kwargs):
        average = kwargs.get('op') == dist.ReduceOp.AVG
        if average:
            kwargs['op'] = dist.ReduceOp.SUM
        kwargs['async_op'] = False
        fn(*args, **kwargs)
        if average:
            args[0].div_(world)
        return Completed()
    return call


# Gloo lacks HCCL's AVG/get_future; retain numerical semantics in this CPU test.
for name in ('all_reduce', 'reduce_scatter_tensor', 'all_gather_into_tensor', 'broadcast'):
    setattr(dist, name, synchronous(getattr(dist, name)))
patch_distributed_adamw()


def groups():
    torch.manual_seed(42)
    return [dict(kind='adamw', lr=.01, betas=(.9, .95), eps=1e-8, weight_decay=.01,
                 params=[torch.nn.Parameter(torch.randn(*shape)) for shape in ((6, 256), (7, 256), (1, 1200), (4,))]),
            dict(kind='muon', lr=.02, momentum=.95, ns_steps=5, beta2=.99, weight_decay=.01,
                 params=[torch.nn.Parameter(torch.randn(8, 8)) for _ in range(2)])]


actual, reference = groups(), groups()
distributed = optim.DistMuonAdamW(actual)
single = optim.MuonAdamW(reference)
try:
    for step in range(5):
        for left, right in zip(actual, reference):
            for param, anchor in zip(left['params'], right['params']):
                torch.manual_seed(100 + step)
                gradient = torch.randn_like(param)
                param.grad = gradient + rank * .25
                anchor.grad = gradient + (world - 1) * .125
        distributed.step()
        single.step()
        for left, right in zip(actual, reference):
            for param, anchor in zip(left['params'], right['params']):
                torch.testing.assert_close(param, anchor, rtol=2e-5, atol=2e-6)
        for param, anchor in zip(actual[0]['params'], reference[0]['params']):
            state = distributed.state[param]
            assert state['step'] == step + 1
            for name in ('exp_avg', 'exp_avg_sq'):
                expected = single.state[anchor][name]
                if param.numel() >= 1024:
                    layout = shard_layout(param.shape[0], world, rank)
                    torch.testing.assert_close(state[name][:layout.valid_size], expected[layout.start:layout.stop], rtol=2e-5, atol=2e-6)
                    assert torch.count_nonzero(state[name][layout.valid_size:]) == 0
                else:
                    torch.testing.assert_close(state[name], expected, rtol=2e-5, atol=2e-6)
    distributed.state[actual[0]['params'][0]]['exp_avg'] = torch.zeros(1)
    try:
        distributed.step()
    except RuntimeError as error:
        assert 'incompatible' in str(error)
    else:
        raise AssertionError('incompatible optimizer state was accepted')
    print(f'rank {rank}: optimizer equivalence passed', flush=True)
finally:
    dist.destroy_process_group()
