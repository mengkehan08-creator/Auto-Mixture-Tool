"""Training identity, budget and checkpoint handoff, without NPU imports."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nanochat_mid_compare.distributed_runtime import (
    Topology, record_training, setup_runtime, training_plan, validate_framework, wait_npu_settle,
)


def base_meta(path, *, batch=524288, sequence=2048):
    path.mkdir(parents=True)
    (path / 'meta_000001.json').write_text(json.dumps({
        'max_seq_len': sequence, 'total_batch_size': batch, 'model_config': {'sequence_len': sequence},
    }))
    return path


def topology(nodes, rank=0):
    return Topology(nodes, rank, 8, '127.0.0.1', 29500)


def test_node_count_preserves_global_batch_and_actual_training_tokens(tmp_path):
    base = base_meta(tmp_path / 'base')
    plans = [training_plan(base, topology(nodes), 1, 401395843) for nodes in (1, 2, 4)]
    assert {plan['actual_tokens'] for plan in plans} == {766 * 524288}
    assert [plan['grad_accum_steps'] for plan in plans] == [32, 16, 8]
    assert all(0 <= plan['rounding_tokens'] < plan['total_batch_size'] for plan in plans)
    with pytest.raises(ValueError, match='Automatic budget inflation'):
        training_plan(base, topology(3), 1, 401395843)
    explicit = training_plan(base, topology(3), 1, 401395843, total_batch_size=540672)
    assert explicit['grad_accum_steps'] == 11
    assert explicit['actual_tokens'] == explicit['num_iterations'] * 540672
    fixed = training_plan(base, topology(2), 1, 1, steps=15)
    assert fixed['actual_tokens'] == 15 * 524288 and fixed['budget_mode'] == 'steps'


def test_record_is_published_before_eval_and_rejects_unexpected_batch(tmp_path):
    base = base_meta(tmp_path / 'base', batch=32, sequence=2)
    plan = training_plan(base, topology(2), 1, 60)
    trained = tmp_path / 'trained'
    trained.mkdir()
    (trained / 'model_000002.pt').write_bytes(b'new weights')
    meta = trained / 'meta_000002.json'
    meta.write_text(json.dumps({'step': 2, 'total_batch_size': 32, 'user_config': {'loader': 'flat', 'load_optimizer': 0}}))
    record = record_training(trained, topology(2), 'job', 'mid:model', plan, tmp_path)
    assert record['status'] == 'TRAINING_SUCCEEDED'
    assert record['training']['actual_tokens'] == 64
    assert record['training']['load_optimizer'] == 0
    assert record['checkpoint']['files'][0]['sha256']
    assert json.loads((trained / 'training_record.json').read_text()) == record
    meta.write_text('{"step":2,"total_batch_size":64}')
    with pytest.raises(ValueError, match='step/batch'):
        record_training(trained, topology(2), 'job', 'mid:model', plan, tmp_path)
    assert record_training(trained, topology(2, 1), 'job', 'mid:model', plan, tmp_path) is None


def test_runtime_keeps_input_assets_immutable(tmp_path):
    model = tmp_path / 'model'
    (model / 'tokenizer').mkdir(parents=True)
    base_meta(model / 'base_checkpoints/d20')
    runtime, output = tmp_path / 'runtime', tmp_path / 'output'
    for _ in range(2):
        setup_runtime(model, runtime, output)
    assert (runtime / 'tokenizer').resolve() == model / 'tokenizer'
    assert (runtime / 'mid_checkpoints').resolve() == output
    assert not (model / 'mid_checkpoints').exists()
    with pytest.raises(ValueError, match='outside'):
        setup_runtime(model, model / 'nested', output)


def test_actual_training_record_reaches_model_manifest_and_rejects_tampering(tmp_path, monkeypatch):
    from auto_mixture_tool.modelarts.evaluation_job import publish_models, validate_models
    monkeypatch.setenv('AMT_RUN_ID', 'job')
    base = base_meta(tmp_path / 'base', batch=32, sequence=2)
    plan = training_plan(base, topology(2), 1, 60)
    tag = 'd20_stem_random_job'
    folder = tmp_path / tag
    folder.mkdir()
    (folder / 'model_000002.pt').write_bytes(b'weights')
    (folder / 'meta_000002.json').write_text('{"step":2,"total_batch_size":32,"model_config":{"sequence_len":2}}')
    record_training(folder, topology(2), 'job', f'mid:{tag}', plan, tmp_path)
    (tmp_path / 'dataset_stats.json').write_text('{}')
    config = {'training': {'base_model_tag': 'd20', 'token_budget': 60},
              'strategies': [{'id': 'random', 'type': 'random'}]}
    publish_models(config, tmp_path, tmp_path)
    manifest = validate_models(tmp_path)
    assert manifest['models'][0]['training_config']['actual_tokens'] == 64
    assert manifest['models'][0]['training_config']['world_size'] == 16
    assert len(manifest['models'][0]['files']) == 3
    (folder / 'model_000002.pt').write_bytes(b'changed weights')
    with pytest.raises(ValueError, match='训练完成记录'):
        publish_models(config, tmp_path, tmp_path)


def test_hbm_gate_waits_for_release_and_does_not_proceed_on_timeout():
    busy = SimpleNamespace(stdout='HBM 15000 / 32768')
    clean = SimpleNamespace(stdout='HBM 1000 / 32768')
    with patch('nanochat_mid_compare.distributed_runtime.subprocess.run', side_effect=[busy, clean]), \
            patch('nanochat_mid_compare.distributed_runtime.time.sleep') as sleep:
        wait_npu_settle(timeout=10)
        sleep.assert_called_once()
    with patch('nanochat_mid_compare.distributed_runtime.subprocess.run', return_value=busy), \
            patch('nanochat_mid_compare.distributed_runtime.time.monotonic', side_effect=[0, 0, 11]):
        with pytest.raises(TimeoutError, match='memory did not settle'):
            wait_npu_settle(timeout=10)
    with patch('nanochat_mid_compare.distributed_runtime.subprocess.run', return_value=SimpleNamespace(stdout='unparseable')):
        with pytest.raises(RuntimeError, match='Cannot verify'):
            wait_npu_settle()


def test_pinned_framework_interfaces_and_actual_optimizer_updates(tmp_path):
    repo = os.environ.get('NANOCHAT_TEST_REPO')
    if not repo:
        pytest.skip('Set NANOCHAT_TEST_REPO to the pinned dev-data-mix checkout')
    validate_framework(repo)
    root = Path(__file__).resolve().parents[1]
    fixture = root / 'tests/fixtures/nanochat_adamw_smoke.py'
    env = dict(os.environ, PYTHONPATH=str(root), OMP_NUM_THREADS='1',
               GLOO_SOCKET_IFNAME='lo0' if sys.platform == 'darwin' else 'lo')
    for world in (2, 3):
        from test_nanochat_distributed import free_port_triplet
        node = Topology(1, 0, world, '127.0.0.1', free_port_triplet())
        process = subprocess.run([sys.executable, '-m', 'torch.distributed.run',
                                  *node.torchrun_args(timeout=30), str(fixture), repo],
                                 env=env, capture_output=True, text=True, timeout=60)
        assert process.returncode == 0, process.stdout + process.stderr
        assert process.stdout.count('optimizer equivalence passed') == world
