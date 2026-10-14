"""CPU fixture; the production launcher/relay/evaluator are exercised by pytest."""
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import torch
import torch.distributed as dist

from nanochat_mid_compare.adaptive_eval import evaluate_task


mode, directory = sys.argv[1:]
root = Path(directory)
root.mkdir(parents=True, exist_ok=True)
dist.init_process_group("gloo", timeout=timedelta(seconds=30))
rank, world = dist.get_rank(), dist.get_world_size()
torch.manual_seed(123)
model = torch.nn.Linear(1, 1)
try:
    if mode == "train":
        distributed = torch.nn.parallel.DistributedDataParallel(model)
        inputs = torch.linspace(-1, 1, 16).reshape(-1, 1)[rank::world]
        targets = .75 * inputs - .1
        optimizer = torch.optim.SGD(model.parameters(), lr=.1)
        for _ in range(5):
            optimizer.zero_grad()
            torch.nn.functional.mse_loss(distributed(inputs), targets).backward()
            optimizer.step()
        if rank == 0:
            torch.save(model.state_dict(), root / "model_000005.pt")
            (root / "meta_000005.json").write_text('{"step":5}')
        dist.barrier()
    else:
        model.load_state_dict(torch.load(root / "model_000005.pt", weights_only=True))
        seen = []
        core = ModuleType("nanochat.core_eval")
        core.prepare_example = lambda index, *args: ([[index + 1]], [0], [1], "multiple_choice", index >= 7)
        core.stack_sequences = lambda tokens, pad: torch.tensor(tokens)

        def forward(model, inputs):
            seen.extend((inputs[:, 0] - 1).tolist())
            scores = model((inputs.float() - 7) / 7)
            return torch.zeros_like(scores), scores > 0

        core.forward_model = forward
        core.judge_example = lambda loss, pred, inputs, start, end, kind, gold: bool(pred[0, 0]) == gold
        package = ModuleType("nanochat")
        package.core_eval = core
        sys.modules["nanochat"], sys.modules["nanochat.core_eval"] = package, core
        os.environ["NANOCHAT_BASE_DIR"] = str(root)
        accuracy = evaluate_task(model, SimpleNamespace(get_bos_token_id=lambda: 0),
                                 list(range(13)), torch.device("cpu"), {"label": "smoke"}, 4)
        inputs = torch.linspace(-1, 1, 13).reshape(-1, 1)[rank::world]
        squared = ((model(inputs) - (.75 * inputs - .1)) ** 2).sum().item()
        totals = torch.tensor([squared, len(inputs)], dtype=torch.float64)
        dist.all_reduce(totals)
        (root / f"eval-rank{rank}.json").write_text(json.dumps({
            "accuracy": accuracy, "mse": (totals[0] / totals[1]).item(), "seen": seen,
        }))
finally:
    dist.destroy_process_group()
