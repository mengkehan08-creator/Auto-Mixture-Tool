"""Global row-group sharding integrated from the validated NanoChat repair."""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from nanochat_mid_compare.distributed_runtime import LEGACY_ROW_GROUP_LOADER_SHA256

logger = logging.getLogger(__name__)


def global_document_batches(split, resume_state_dict, tokenizer_batch_size, data_dir=None):
    """
    Infinite iterator over document batches (list of text strings) from parquet files.

    Handles DDP sharding and approximate resume. Each yield is (text_batch, (pq_idx, rg_idx, epoch))
    where text_batch is a list of document strings, indices track position for resumption,
    and epoch counts how many times we've cycled through the dataset (starts at 1).

    DDP sharding flattens every (file, row_group) pair into ONE global sequence
    (files in list order, row groups ascending within each file) and deals them
    round-robin: global index k goes to rank k % world_size. When every file's
    row-group count is divisible by world_size this is IDENTICAL to the old
    per-file scheme (rg_idx = rank, stride world_size) — same ranks, same row
    groups, same order, same resume states — so existing single-node runs
    (ws=8 vs 16-row-group shards) are unaffected. Unlike the per-file scheme it
    cannot STARVE top ranks when a file has fewer row groups than world_size
    (multi-node 2026-09-09: ws=24/32 vs 16-row-group mixture shards spun
    forever reopening files without ever yielding).
    """
    import pyarrow.parquet as pq
    from nanochat.common import get_dist_info
    from nanochat.dataset import list_parquet_files

    import bisect

    ddp, ddp_rank, ddp_local_rank, ddp_world_size = get_dist_info()

    warn_on_legacy = ddp_rank == 0 and split == "train" # rank 0 on train split will warn on legacy
    parquet_paths = list_parquet_files(data_dir=data_dir, warn_on_legacy=warn_on_legacy)
    assert len(parquet_paths) != 0, f"No dataset parquet files found in {data_dir}, did you run dataset.py?"
    parquet_paths = parquet_paths[:-1] if split == "train" else parquet_paths[-1:]
    assert len(parquet_paths) != 0, f"split '{split}' got 0 parquet files from {data_dir}, did you run dataset.py?"

    # Pre-scan row-group counts (footer reads only, no data). Corrupt shards
    # are logged + dropped once here so EVERY rank computes the same global
    # layout (the old lazy scheme made a corrupt shard visible only to ranks
    # that had row groups in it). Empty files contribute 0 and vanish from
    # the layout naturally.
    layout = []  # (original pq_idx, path, num_row_groups)
    for pq_idx, filepath in enumerate(parquet_paths):
        try:
            n = pq.ParquetFile(filepath).metadata.num_row_groups
        except Exception as e:
            logger.warning(f"Skipping corrupted shard {filepath}: {e}")
            continue
        layout.append((pq_idx, filepath, n))
    total_row_groups = sum(n for _, _, n in layout)
    if total_row_groups < ddp_world_size:
        raise RuntimeError(
            f"row-group starvation: world_size={ddp_world_size} but the "
            f"'{split}' split has only {total_row_groups} row groups across "
            f"{len(layout)} readable shards — ranks {total_row_groups}.."
            f"{ddp_world_size - 1} would read no data and the loader would "
            f"spin forever; add data or reduce world size")

    # k_base[f] = global index of layout slot f's first row group
    k_base = [0]
    for _, _, n in layout:
        k_base.append(k_base[-1] + n)

    def slot_for_k(k):
        # layout slot containing global row-group index k
        return bisect.bisect_right(k_base, k) - 1

    resume_pq_idx = resume_state_dict["pq_idx"] if resume_state_dict is not None else 0
    resume_rg_idx = resume_state_dict["rg_idx"] if resume_state_dict is not None else None
    resume_epoch = resume_state_dict.get("epoch", 1) if resume_state_dict is not None else 1
    first_pass = True
    epoch = resume_epoch

    while True:  # iterate infinitely (multi-epoch)
        if first_pass:
            first_pass = False
            # First pass starts at the resume position (if any); later
            # passes always restart from the beginning of the sequence.
            k_start = 0
            if resume_rg_idx is not None:
                # map the saved (pq_idx, rg_idx) back to its global index
                # and advance past it to this rank's NEXT row group
                k_resume = None
                for slot, (orig_idx, _, n) in enumerate(layout):
                    if orig_idx == resume_pq_idx:
                        k_resume = k_base[slot] + resume_rg_idx
                        break
                if k_resume is not None:
                    # smallest k > k_resume with k % world_size == rank
                    k_start = k_resume + 1 + (ddp_rank - (k_resume + 1)) % ddp_world_size
                else:
                    # the resume shard is unreadable NOW (was readable when
                    # the state was saved): skip to the next readable file,
                    # matching the old scheme's corrupt-shard skip
                    for slot, (orig_idx, _, _) in enumerate(layout):
                        if orig_idx > resume_pq_idx:
                            k_start = k_base[slot]
                            break
                    else:
                        k_start = total_row_groups  # nothing left this pass
            elif resume_state_dict is not None:
                # state without rg_idx: start of the saved file (old scheme
                # resumed at rg_idx = ddp_rank of that file)
                for slot, (orig_idx, _, _) in enumerate(layout):
                    if orig_idx == resume_pq_idx:
                        k_start = k_base[slot]
                        break
        else:
            k_start = 0

        k = k_start
        cur_slot, cur_pf = -1, None
        while k < total_row_groups:
            if k % ddp_world_size != ddp_rank:
                k += 1
                continue
            slot = slot_for_k(k)
            orig_idx, filepath, _ = layout[slot]
            if slot != cur_slot:
                try:
                    cur_pf = pq.ParquetFile(filepath)
                    cur_slot = slot
                except Exception as e:
                    # readable at pre-scan but not now; every rank that
                    # reaches this file sees the same and skips its share
                    logger.warning(f"Skipping corrupted shard {filepath}: {e}")
                    k = k_base[slot + 1]
                    cur_slot, cur_pf = -1, None
                    continue
            rg_idx = k - k_base[slot]
            try:
                rg = cur_pf.read_row_group(rg_idx)
                batch = rg.column('text').to_pylist()
            except Exception as e:
                logger.warning(f"Skipping corrupted row_group {rg_idx} in {filepath}: {e}")
                k += 1
                continue
            for i in range(0, len(batch), tokenizer_batch_size):
                yield batch[i:i+tokenizer_batch_size], (orig_idx, rg_idx, epoch)
            k += 1
        epoch += 1


def patch_legacy_row_group_loader() -> bool:
    """Adapt the verified legacy loader in memory, preserving mounted code files."""
    from nanochat import dataloader

    source = Path(dataloader.__file__)
    if hashlib.sha256(source.read_bytes()).hexdigest() != LEGACY_ROW_GROUP_LOADER_SHA256:
        return False
    dataloader._document_batches = global_document_batches
    return True
