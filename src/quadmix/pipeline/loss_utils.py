"""Chunked loss utilities for memory-efficient training and adaptive val_bs."""

from typing import Tuple

import torch
import torch.nn.functional as F


def chunked_loss_from_hidden(model, hidden, targets, chunk_size=2048):
    """Compute CE loss chunk-by-chunk from hidden states, never materializing full logits.

    hidden: (B, T, C) from model.forward(return_hidden=True)
    Only chunk_logits (B, chunk, V) exists at any time — full (B, T, V) is never created.
    """
    B, T, _ = hidden.shape
    V = model.config.vocab_size
    total_loss = torch.tensor(0.0, device=hidden.device, dtype=torch.float32)
    n_tokens = 0
    for i in range(0, T, chunk_size):
        chunk_logits = model.lm_head(hidden[:, i:i + chunk_size])
        chunk_tgt = targets[:, i:i + chunk_size]
        n = chunk_tgt.numel()
        total_loss = total_loss + F.cross_entropy(
            chunk_logits.reshape(-1, V), chunk_tgt.reshape(-1)
        ) * n
        n_tokens += n
        del chunk_logits
    return total_loss / n_tokens


def chunked_loss_per_token_from_hidden(model, hidden, targets, chunk_size=2048):
    """Same as chunked_loss_from_hidden but returns per-token losses (reduction='none')."""
    B, T, _ = hidden.shape
    V = model.config.vocab_size
    per_token = torch.empty(B, T, device=hidden.device, dtype=torch.float32)
    i = 0
    current_chunk = max(32, int(chunk_size))
    while i < T:
        width = min(current_chunk, T - i)
        try:
            chunk_logits = model.lm_head(hidden[:, i:i + width])
            chunk_tgt = targets[:, i:i + width]
            per_token[:, i:i + width] = F.cross_entropy(
                chunk_logits.reshape(-1, V), chunk_tgt.reshape(-1), reduction="none"
            ).view(chunk_tgt.shape)
            del chunk_logits
            i += width
        except RuntimeError as exc:
            if "out of memory" not in str(exc).lower() or current_chunk <= 32:
                raise
            current_chunk = max(32, current_chunk // 2)
            if hidden.device.type == "npu":
                torch.npu.empty_cache()
            elif hidden.device.type == "cuda":
                torch.cuda.empty_cache()
    return per_token


def compute_val_batch_size(
    device: torch.device,
    vocab_size: int,
    seq_len: int,
    max_val_bs: int = 96,
) -> Tuple[int, int]:
    """Compute safe (val_bs, chunk_size) based on available device memory.

    Strategy: try large chunk_size first; if val_bs < 8, reduce chunk_size
    to lower per-sample peak memory, then recompute val_bs.

    Returns:
        (val_bs, chunk_size) — both guaranteed >= 1.
    """
    if device.type not in ("npu", "cuda"):
        return min(max_val_bs, 8), 2048

    api = torch.npu if device.type == "npu" else torch.cuda
    try:
        free_mem, _ = api.mem_get_info(device)
    except (AttributeError, RuntimeError, TypeError):
        total_mem = api.get_device_properties(device).total_memory
        free_mem = total_mem - api.memory_reserved(device)
    # Use only half of genuinely free memory and retain a 2 GiB reserve for
    # activations/runtime workspaces.  The previous total-allocated estimate
    # substantially overestimated free NPU memory.
    safe_available = int(max(0, free_mem - 2 * 1024 ** 3) * 0.5)

    if safe_available <= 0:
        return 4, 256

    for cs in (512, 256, 128, 64, 32):
        per_sample_peak = 8 * cs * vocab_size
        bs = max(4, min(max_val_bs, int(safe_available / per_sample_peak)))
        if bs >= 8:
            return bs, cs

    return 1, 32
