"""Execute all three production launch scripts with a fake NPU subprocess."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


@pytest.mark.parametrize('script', ['run_stem_experiment.sh', 'run_experiment.sh', 'run_quadmix_only.sh'])
def test_launchers_preserve_budget_and_publish_before_eval(tmp_path, script):
    root = Path(__file__).resolve().parents[1]
    repo = tmp_path / 'framework'
    (repo / 'scripts').mkdir(parents=True)
    (repo / 'nanochat').mkdir()
    (repo / 'scripts/mid_train.py').write_text('import argparse\nparser = argparse.ArgumentParser()\n' +
        '\n'.join(f'parser.add_argument({flag!r})' for flag in
                  ('--loader', '--eval-benchmarks', '--total-batch-size', '--max-seq-len', '--load-optimizer')))
    (repo / 'scripts/base_eval.py').write_text('import argparse\nparser = argparse.ArgumentParser()\nparser.add_argument("--eval-benchmarks")\n')
    (repo / 'nanochat/dataloader.py').write_text('def _document_batches():\n    total_row_groups = 32\n    return total_row_groups\n')
    (repo / 'nanochat/optim.py').write_text('class DistMuonAdamW:\n' +
        '\n'.join(f'    def {name}(self): pass' for name in ('_reduce_adamw', '_compute_adamw', '_finish_gathers')))
    model = tmp_path / 'model'
    base = model / 'base_checkpoints/d20'
    base.mkdir(parents=True)
    meta = {'max_seq_len': 8, 'total_batch_size': 128,
            'model_config': {'sequence_len': 8, 'n_layer': 1, 'n_embd': 16, 'n_head': 1, 'vocab_size': 64}}
    (base / 'meta_000001.json').write_text(json.dumps(meta))
    (base / 'model_000001.pt').write_bytes(b'base')
    (model / 'tokenizer').mkdir()
    (model / 'tokenizer/tokenizer.pkl').write_bytes(b'tokenizer')
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    (bundle / 'resource.txt').write_text('offline test resource')
    data = tmp_path / 'data'
    stats = {'config': {'training_budget': 257, 'budget_cap': 257}}
    for method in ('quadmix', 'random'):
        folder = data / f'{method}_data'
        folder.mkdir(parents=True)
        pq.write_table(pa.table({'text': ['sample'] * 32}), folder / 'shard_00000.parquet', row_group_size=1)
        pq.write_table(pa.table({'text': ['val']}), folder / 'shard_99999.parquet')
        stats[method] = {'tokens': 256, 'train_docs': 32, 'val_docs': 1, 'shards': 1}
    stats_path = data / 'dataset_stats.json'
    stats_path.write_text(json.dumps(stats))
    original_stats = stats_path.read_bytes()
    binary = tmp_path / 'bin'
    binary.mkdir()
    python = binary / 'python3'
    python.write_text(f'#!{sys.executable}\n' + (root / 'tests/fixtures/nanochat_shell_python.py').read_text())
    python.chmod(0o755)
    df = binary / 'df'
    df.write_text('#!/bin/sh\nprintf "Filesystem 1024-blocks Used Available Capacity Mounted\\nfixture 1073741824 0 1073741824 0%% /\\n"\n')
    df.chmod(0o755)
    # Production runs on Linux; emulate GNU ln's -T flag on the macOS test host.
    ln = binary / 'ln'
    ln.write_text(f'#!{sys.executable}\nimport os,sys\ntarget,link=sys.argv[-2:]\n'
                  'if os.path.islink(link): os.unlink(link)\nos.symlink(target,link)\n')
    ln.chmod(0o755)
    capture = tmp_path / 'commands.jsonl'
    env = dict(os.environ, PATH=f'{binary}:{os.environ["PATH"]}', AMT_REAL_PYTHON=sys.executable,
               AMT_PYTHON_EXECUTABLE=str(python), AMT_CAPTURE_COMMANDS=str(capture),
               AMT_RUN_ID='shell-test', NNODES='1', NODE_RANK='0', MASTER_ADDR='127.0.0.1',
               NANOCHAT_REPO=str(repo), NANOCHAT_MODEL_DIR=str(model), BASE_MODEL_TAG='d20',
               NANOCHAT_RUNTIME_DIR=str(tmp_path / 'runtime'), NANOCHAT_EVAL_BUNDLE_DIR=str(bundle),
               NANOCHAT_SKIP_EVAL_DOWNLOAD='1', NANOCHAT_DISABLE_WANDB='1',
               PREPARED_COMPARISON_DATA_DIR=str(data), PREPROCESSED_DATA_DIR=str(data), STEM_DATA_DIR=str(data),
               RESULT_DIR=str(tmp_path / 'result'), MID_CHECKPOINTS_OUTPUT_DIR=str(tmp_path / 'checkpoints'),
               AMT_TRAIN_ONLY='1', EVALUATION_ENABLED='0', MIX_GENERAL_DATA='0', COMPARISON_METHODS='random',
               TRAIN_TOKEN_BUDGET='257', TRAIN_TOTAL_BATCH_SIZE='128', DEVICE_BATCH_SIZE='1', TRAIN_NUM_ITERATIONS='0')
    command = ['bash', '-c', 'source() { return 0; }; export -f source; exec bash "$@"', 'launcher',
               str(root / 'nanochat_mid_compare' / script)]
    if script == 'run_quadmix_only.sh':
        command += ['--data-dir', str(data)]
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in capture.read_text().splitlines()]
    assert len(calls) == 1
    assert '--nnodes=1' in calls[0] and '--num-iterations=3' in calls[0]
    assert '--load-optimizer=0' in calls[0] and '--loader=flat' in calls[0]
    records = list((tmp_path / 'checkpoints').glob('*/training_record.json'))
    assert len(records) == 1
    record = json.loads(records[0].read_text())
    assert record['training']['actual_tokens'] == 384
    assert record['status'] == 'TRAINING_SUCCEEDED'
    assert record['dataset']['statistics_sha256']
    assert record['dataset']['shards'][0]['row_groups'] == 32
    assert stats_path.read_bytes() == original_stats
    assert not (model / 'mid_checkpoints').exists()
