"""The standalone framework repair also works through the production entrypoint."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from nanochat_mid_compare import distributed_runtime, global_row_groups, run_nanochat_mid_train
from scripts.check_nanochat_inputs import row_coverage


def modules(monkeypatch, data, world_size):
    package = ModuleType("nanochat")
    package.__path__ = []
    common, dataset, dataloader = (ModuleType("nanochat." + name) for name in ("common", "dataset", "dataloader"))
    common.get_dist_info = lambda: (True, 0, 0, world_size)
    dataset.list_parquet_files = lambda **kwargs: sorted(str(path) for path in data.glob("*.parquet"))
    package.dataloader = dataloader
    for name, module in (("nanochat", package), ("nanochat.common", common),
                         ("nanochat.dataset", dataset), ("nanochat.dataloader", dataloader)):
        monkeypatch.setitem(sys.modules, name, module)
    return common, dataloader


@pytest.mark.parametrize("world_size", [16, 24, 32])
def test_every_rank_reads_its_global_groups_and_resumes(tmp_path, monkeypatch, world_size):
    expected = []
    for index, count in enumerate((16, 17, 20)):
        texts = [f"file-{index}-group-{group}" for group in range(count)]
        expected.extend(texts)
        pq.write_table(pa.table({"text": texts}), tmp_path / f"shard_{index:05d}.parquet", row_group_size=1)
    pq.write_table(pa.table({"text": ["validation"]}), tmp_path / "shard_99999.parquet")
    common, _ = modules(monkeypatch, tmp_path, world_size)
    seen = []
    for rank in range(world_size):
        common.get_dist_info = lambda rank=rank: (True, rank, rank % 8, world_size)
        batches = global_row_groups.global_document_batches("train", None, 1, str(tmp_path))
        owned = expected[rank::world_size]
        first, first_state = next(batches)
        actual = first + [next(batches)[0][0] for _ in owned[1:]]
        assert actual == owned
        assert next(batches)[0] == first  # next epoch
        resumed = global_row_groups.global_document_batches("train", dict(zip(("pq_idx", "rg_idx", "epoch"), first_state)), 1, str(tmp_path))
        texts, state = next(resumed)
        assert texts == [owned[1] if len(owned) > 1 else owned[0]]
        assert state[2] == (1 if len(owned) > 1 else 2)
        seen.extend(actual)
    assert sorted(seen) == sorted(expected)


def test_too_few_groups_fail_instead_of_waiting_for_hccl(tmp_path, monkeypatch):
    pq.write_table(pa.table({"text": ["train"] * 20}), tmp_path / "shard_00000.parquet", row_group_size=1)
    pq.write_table(pa.table({"text": ["validation"]}), tmp_path / "shard_99999.parquet")
    modules(monkeypatch, tmp_path, 24)
    with pytest.raises(RuntimeError, match="row-group starvation"):
        next(global_row_groups.global_document_batches("train", None, 1, str(tmp_path)))
    old, current = row_coverage([[1] * 20, [1] * 20], 24)
    assert [rank for rank, count in enumerate(old) if not count] == [20, 21, 22, 23]
    assert all(current)


def test_only_verified_legacy_loader_is_adapted_without_writing_inputs(tmp_path, monkeypatch):
    _, dataloader = modules(monkeypatch, tmp_path, 24)
    source = tmp_path / "dataloader.py"
    raw = b"def _document_batches(): pass\n"
    source.write_bytes(raw)
    dataloader.__file__ = str(source)
    original = lambda: None
    dataloader._document_batches = original
    assert global_row_groups.patch_legacy_row_group_loader() is False
    assert dataloader._document_batches is original
    monkeypatch.setattr(global_row_groups, "LEGACY_ROW_GROUP_LOADER_SHA256", hashlib.sha256(raw).hexdigest())
    assert global_row_groups.patch_legacy_row_group_loader() is True
    assert dataloader._document_batches is global_row_groups.global_document_batches
    assert source.read_bytes() == raw


def test_preflight_accepts_verified_legacy_and_rejects_unknown_loader(tmp_path, monkeypatch):
    files = {
        "nanochat/dataloader.py": "def _document_batches():\n    pass\n",
        "nanochat/optim.py": "class DistMuonAdamW:\n" + "".join(f"    def {name}(self): pass\n" for name in
            ("_reduce_adamw", "_compute_adamw", "_finish_gathers")),
        "scripts/base_eval.py": 'parser.add_argument("--eval-benchmarks")\n',
        "scripts/mid_train.py": "".join(f"parser.add_argument({flag!r})\n" for flag in
            ("--loader", "--eval-benchmarks", "--total-batch-size", "--max-seq-len", "--load-optimizer")),
    }
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    with pytest.raises(ValueError, match="global row-group loader"):
        distributed_runtime.validate_framework(tmp_path)
    digest = hashlib.sha256((tmp_path / "nanochat/dataloader.py").read_bytes()).hexdigest()
    monkeypatch.setattr(distributed_runtime, "LEGACY_ROW_GROUP_LOADER_SHA256", digest)
    distributed_runtime.validate_framework(tmp_path)


def test_training_installs_loader_before_importing_mid_train(monkeypatch):
    calls = []
    monkeypatch.delenv("NANOCHAT_SKIP_EVAL_DOWNLOAD", raising=False)
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.setattr(global_row_groups, "patch_legacy_row_group_loader", lambda: calls.append("loader") or True)
    monkeypatch.setattr(run_nanochat_mid_train, "patch_distributed_adamw", lambda: calls.append("optimizer"))
    monkeypatch.setattr(run_nanochat_mid_train.runpy, "run_module", lambda *args, **kwargs: calls.append(args[0]))
    run_nanochat_mid_train.main()
    assert calls == ["loader", "optimizer", "scripts.mid_train"]


def test_formal_and_short_three_node_budgets_use_explicit_batch(tmp_path):
    (tmp_path / "meta_000001.json").write_text(json.dumps({
        "max_seq_len": 2048, "total_batch_size": 1048576, "model_config": {"sequence_len": 2048},
    }))
    topology = distributed_runtime.Topology(3, 0, 8, "127.0.0.1", 29500)
    for budget, steps, actual in ((5406720, 5, 5406720), (401395843, 372, 402259968)):
        plan = distributed_runtime.training_plan(tmp_path, topology, 1, budget, total_batch_size=1081344)
        assert (plan["num_iterations"], plan["actual_tokens"], plan["grad_accum_steps"]) == (steps, actual, 22)


def test_readonly_diagnostic_checks_actual_paths_and_rank_coverage(tmp_path):
    repo, data = tmp_path / "framework", tmp_path / "data"
    (repo / "nanochat").mkdir(parents=True)
    data.mkdir()
    source = repo / "nanochat/dataloader.py"
    source.write_text("def _document_batches():\n    total_row_groups = 40\n")
    for index in range(3):
        pq.write_table(pa.table({"text": ["text"] * 20}), data / f"shard_{index:05d}.parquet", row_group_size=1)
    paths = [source, *sorted(data.glob("*.parquet"))]
    original = [path.read_bytes() for path in paths]
    script = Path(__file__).resolve().parents[1] / "scripts/check_nanochat_inputs.py"

    def check(world_size):
        return subprocess.run([sys.executable, str(script), "--repo", str(repo), "--data", str(data),
                               "--world-size", str(world_size)], capture_output=True, text=True, check=False)

    result = check(24)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "旧式逐文件分配下没有行的 rank： [20, 21, 22, 23]" in result.stdout
    assert "全局行组分配下没有行的 rank： []" in result.stdout
    assert "训练行组总数： 40" in result.stdout
    assert check(64).returncode == 2
    assert [path.read_bytes() for path in paths] == original
    source.write_text("def _document_batches():\n    pass\n")
    assert check(24).returncode == 2
