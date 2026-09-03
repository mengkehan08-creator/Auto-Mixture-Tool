"""Run NanoChat mid-training with arbitrary-world-size AdamW sharding.

The mounted NanoChat NPU fork shards large AdamW tensors only when their first
dimension is exactly divisible by ``WORLD_SIZE``. ModelArts node counts such as
3, 5, or 7 violate that assumption for a 32768-token vocabulary. This wrapper
patches only the distributed AdamW communication to pad before reduce-scatter
and trim after all-gather, then executes NanoChat's original training module.
"""

from __future__ import annotations

import math
import os
import runpy
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class ShardLayout:
    rank_size: int
    padded_size: int
    start: int
    stop: int

    @property
    def valid_size(self) -> int:
        return self.stop - self.start


def shard_layout(size: int, world_size: int, rank: int) -> ShardLayout:
    """Return an equal collective shard plus this rank's valid source range."""
    if size <= 0 or world_size <= 0 or not 0 <= rank < world_size:
        raise ValueError("invalid distributed shard dimensions")
    rank_size = math.ceil(size / world_size)
    start = min(rank * rank_size, size)
    stop = min(start + rank_size, size)
    return ShardLayout(rank_size, rank_size * world_size, start, stop)


def patch_distributed_adamw() -> None:
    import torch
    import torch.distributed as dist
    from nanochat import optim as nanochat_optim

    optimizer_class = nanochat_optim.DistMuonAdamW

    def reduce_adamw(self, group: dict, world_size: int) -> dict:
        param_infos = {}
        rank = dist.get_rank()
        for parameter in group["params"]:
            grad = parameter.grad
            if parameter.numel() < 1024:
                future = dist.all_reduce(
                    grad, op=dist.ReduceOp.AVG, async_op=True
                ).get_future()
                param_infos[parameter] = {
                    "future": future,
                    "grad_slice": grad,
                    "is_small": True,
                    "layout": None,
                    "reduce_input": grad,
                }
                continue

            layout = shard_layout(grad.shape[0], world_size, rank)
            if layout.padded_size == grad.shape[0]:
                reduce_input = grad
            else:
                padded_shape = (layout.padded_size, *grad.shape[1:])
                reduce_input = torch.zeros(
                    padded_shape, dtype=grad.dtype, device=grad.device
                )
                reduce_input[: grad.shape[0]].copy_(grad)
            grad_slice = torch.empty(
                (layout.rank_size, *grad.shape[1:]),
                dtype=grad.dtype,
                device=grad.device,
            )
            future = dist.reduce_scatter_tensor(
                grad_slice, reduce_input, op=dist.ReduceOp.AVG, async_op=True
            ).get_future()
            param_infos[parameter] = {
                "future": future,
                "grad_slice": grad_slice,
                "is_small": False,
                "layout": layout,
                # Keep the asynchronous collective input alive until wait().
                "reduce_input": reduce_input,
            }
        return {"param_infos": param_infos}

    def compute_adamw(
        self,
        group: dict,
        info: dict,
        gather_list: list,
        rank: int,
        world_size: int,
    ) -> None:
        del world_size
        for parameter in group["params"]:
            param_info = info["param_infos"][parameter]
            param_info["future"].wait()
            grad_slice = param_info["grad_slice"]
            state = self.state[parameter]
            layout = param_info["layout"]

            if param_info["is_small"]:
                param_slice = parameter
            elif layout.padded_size == parameter.shape[0]:
                param_slice = parameter[layout.start : layout.stop]
            else:
                param_slice = torch.zeros_like(grad_slice)
                if layout.valid_size:
                    param_slice[: layout.valid_size].copy_(
                        parameter[layout.start : layout.stop]
                    )

            expected_shape = tuple(param_slice.shape)
            for state_name in ("exp_avg", "exp_avg_sq"):
                if state_name in state and tuple(state[state_name].shape) != expected_shape:
                    raise RuntimeError(
                        "optimizer checkpoint shard is incompatible with the current "
                        f"WORLD_SIZE on rank {rank}: {state_name} has shape "
                        f"{tuple(state[state_name].shape)}, expected {expected_shape}. "
                        "Set trainer_config.load_optimizer=false when changing node count."
                    )

            if not state:
                state["step"] = 0
                state["exp_avg"] = torch.zeros_like(param_slice)
                state["exp_avg_sq"] = torch.zeros_like(param_slice)
            state["step"] += 1

            self._adamw_step_t.fill_(state["step"])
            self._adamw_lr_t.fill_(group["lr"])
            self._adamw_beta1_t.fill_(group["betas"][0])
            self._adamw_beta2_t.fill_(group["betas"][1])
            self._adamw_eps_t.fill_(group["eps"])
            self._adamw_wd_t.fill_(group["weight_decay"])
            nanochat_optim.adamw_step_fused(
                param_slice,
                grad_slice,
                state["exp_avg"],
                state["exp_avg_sq"],
                self._adamw_step_t,
                self._adamw_lr_t,
                self._adamw_beta1_t,
                self._adamw_beta2_t,
                self._adamw_eps_t,
                self._adamw_wd_t,
            )

            if param_info["is_small"]:
                continue
            if layout.padded_size == parameter.shape[0]:
                future = dist.all_gather_into_tensor(
                    parameter, param_slice, async_op=True
                ).get_future()
                gather_list.append({"future": future, "params": None})
            else:
                gathered = torch.empty(
                    (layout.padded_size, *parameter.shape[1:]),
                    dtype=parameter.dtype,
                    device=parameter.device,
                )
                future = dist.all_gather_into_tensor(
                    gathered, param_slice, async_op=True
                ).get_future()
                gather_list.append(
                    {
                        "future": future,
                        "params": None,
                        "adamw_target": parameter,
                        "gathered": gathered,
                        "source": param_slice,
                    }
                )

    def finish_gathers(self, gather_list: list) -> None:
        for info in gather_list:
            info["future"].wait()
            if "adamw_target" in info:
                target = info["adamw_target"]
                target.copy_(info["gathered"][: target.shape[0]])
            elif info["params"] is not None:
                torch._foreach_copy_(
                    info["params"],
                    list(info["stacked_params"][: len(info["params"])].unbind(0)),
                )

    optimizer_class._reduce_adamw = reduce_adamw
    optimizer_class._compute_adamw = compute_adamw
    optimizer_class._finish_gathers = finish_gathers


def main() -> None:
    # The wrapper is launched while cwd is the mounted NanoChat repository.
    sys.path.insert(0, os.getcwd())
    patch_distributed_adamw()
    runpy.run_module("scripts.mid_train", run_name="__main__")


if __name__ == "__main__":
    main()
