"""Fake accelerator execution; all budget/data/record commands run unchanged."""
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
if args[:2] == ['-m', 'torch.distributed.run']:
    flags = dict(arg[2:].split('=', 1) for arg in args if arg.startswith('--') and '=' in arg)
    tag = flags['model-tag']
    base = Path(os.environ['NANOCHAT_BASE_DIR'])
    folder = base / 'mid_checkpoints' / tag
    folder.mkdir(parents=True, exist_ok=True)
    step = int(flags['num-iterations'])
    (folder / f'model_{step:06d}.pt').write_bytes(b'completed test model')
    (folder / f'meta_{step:06d}.json').write_text(json.dumps({
        'step': step, 'total_batch_size': int(flags['total-batch-size']),
        'model_config': {'sequence_len': int(flags['max-seq-len'])},
        'user_config': {'max_seq_len': int(flags['max-seq-len']), 'device_batch_size': int(flags['device-batch-size']),
                        'loader': flags['loader'], 'load_optimizer': int(flags['load-optimizer'])},
    }))
    with Path(os.environ['AMT_CAPTURE_COMMANDS']).open('a') as stream:
        stream.write(json.dumps(args) + '\n')
elif args[:1] == ['-c'] and 'from nanochat.tokenizer import get_tokenizer' in args[1]:
    pass
else:
    os.execv(os.environ['AMT_REAL_PYTHON'], [os.environ['AMT_REAL_PYTHON'], *args])
