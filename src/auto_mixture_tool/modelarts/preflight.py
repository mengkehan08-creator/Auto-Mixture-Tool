"""Cheap mounted-file checks before proxy experiments or model training."""
from pathlib import Path


def check_mounted_assets(config, stage, inputs=Path('/home/ma-user/modelarts/inputs')):
    model = inputs / 'nanochat_model_dir_1'
    repo = inputs / 'nanochat_npu_dir_3'
    errors = []
    files = [model / 'tokenizer/tokenizer.pkl', model / 'tokenizer/token_bytes.pt']
    directories = [model / 'base_checkpoints' / config['training'].get('base_model_tag', 'd24')]
    if stage == 'mixing':
        if any(s['type'] == 'quadmix' for s in config.get('strategies', [{'type': 'quadmix'}])):
            files += [inputs / 'quadmix_tokenizer_dir_4/tokenizer.json',
                      inputs / 'proxy_validation_dir_5/stem_v2_tokenized.pt']
        data = inputs / 'data_dir_0'
        if not data.is_dir() or next(data.rglob('*.parquet'), None) is None:
            errors.append(f'缺少 Parquet 输入数据：{data}')
    elif stage == 'training':
        files += [repo / 'scripts/mid_train.py', repo / 'scripts/base_eval.py']
        directories += [inputs / 'comparison_data_dir_8']
        if config['evaluation'].get('datasets') or config['training'].get('core_metric_every', -1) != -1:
            directories += [inputs / 'eval_bundle_dir_6']
    else:
        directories = [inputs / 'eval_bundle_dir_6', inputs / 'trained_models']
        files += [repo / 'scripts/base_eval.py', inputs / 'trained_models/models_manifest.json']
        if config.get('evaluation_sources'):
            directories = [inputs / 'eval_bundle_dir_6']
            files = [repo / 'scripts/base_eval.py']
            for source in config['evaluation_sources']:
                files += [inputs / source['mount'] / 'models_manifest.json',
                          inputs / source['tokenizer_mount'] / 'tokenizer.pkl',
                          inputs / source['tokenizer_mount'] / 'token_bytes.pt']
    for path in files:
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f'文件缺失或为空：{path}')
    for path in directories:
        if not path.is_dir() or next(path.iterdir(), None) is None:
            errors.append(f'目录缺失或为空：{path}')
    if errors:
        raise ValueError('离线挂载检查失败，请补齐 OBS 资源后重新提交：\n- ' + '\n- '.join(errors))
