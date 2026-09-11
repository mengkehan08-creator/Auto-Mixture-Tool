"""Small OBS metadata reads and conservative model-comparison decisions."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

MAX_METADATA_BYTES = 1024 * 1024
STRUCTURE_KEYS = {'n_layer', 'n_embd', 'n_head', 'vocab_size', 'sequence_len'}


def file_digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def directory_digest(root, files):
    entries = [(p.relative_to(root).as_posix(), file_digest(p)) for p in sorted(files)]
    return hashlib.sha256(json.dumps(entries, separators=(',', ':')).encode()).hexdigest() if entries else None


def identity_filename(tag):
    if not isinstance(tag, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', tag):
        raise ValueError('基础模型标签须为字母、数字、下划线或连字符')
    return f'model_identity_{tag}.json'


def build_identity(model_dir, tag):
    """Hash local mounted files only; never download model weights on the UI server."""
    identity_filename(tag)
    model_dir = Path(model_dir)
    base = model_dir / 'base_checkpoints' / tag
    weights = sorted(base.glob('model_*.pt'))
    metadata = base / weights[-1].name.replace('model_', 'meta_').replace('.pt', '.json') if weights else None
    tokenizer = model_dir / 'tokenizer'
    return {'framework': 'nanochat', 'format': 'nanochat-checkpoint-v1',
            'model_config': json.loads(metadata.read_text(encoding='utf-8')).get('model_config', {}) if metadata and metadata.is_file() else {},
            'tokenizer_sha256': directory_digest(tokenizer, [p for p in tokenizer.rglob('*') if p.is_file()]),
            'base_weights_sha256': directory_digest(base, weights)}


def read_metadata(uri):
    """Read a single bounded JSON object using the environment's own OBS access."""
    parsed = urlsplit(uri)
    name = parsed.path.rsplit('/', 1)[-1]
    if (parsed.scheme != 'obs' or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,62}', parsed.netloc)
            or parsed.query or parsed.fragment or '\\' in uri or any(c.isspace() for c in uri)
            or '..' in unquote(parsed.path).split('/')
            or not (name == 'models_manifest.json' or re.fullmatch(r'model_identity_[A-Za-z0-9_-]{1,128}\.json', name))):
        raise ValueError('只允许读取 OBS 模型清单，不接受权重文件或网页地址')
    try:
        import moxing as mox
    except ImportError:
        raise ValueError('开发环境未安装 MoXing；请在具备 OBS 只读权限的环境运行工具') from None
    try:
        if mox.file.get_size(uri) > MAX_METADATA_BYTES:
            raise ValueError('模型清单超过 1 MiB，拒绝读取')
        with mox.file.File(uri, 'rb') as stream:
            raw = stream.read(MAX_METADATA_BYTES + 1)
        if len(raw) > MAX_METADATA_BYTES:
            raise ValueError('模型清单超过 1 MiB，拒绝读取')
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get('version') != 1:
            raise ValueError('模型清单版本或格式无效')
        return result
    except Exception:
        # SDK exceptions can contain signed requests and credentials.
        raise ValueError('OBS 模型清单读取失败：请检查文件是否存在、大小不超过 1 MiB，以及 OBS 只读权限和网络') from None


def compare_identity(reference, candidate):
    reasons, missing = [], []
    for key, label in [('framework', '训练框架'), ('format', '模型格式'), ('model_config', '模型结构'),
                       ('tokenizer_sha256', 'Tokenizer 指纹'), ('base_weights_sha256', '基础权重集合指纹')]:
        left, right = reference.get(key), candidate.get(key)
        if key == 'model_config':
            valid = all(isinstance(v, dict) and STRUCTURE_KEYS <= v.keys()
                        and all(type(v[k]) is int and v[k] > 0 for k in STRUCTURE_KEYS) for v in (left, right))
        elif key.endswith('_sha256'):
            valid = all(isinstance(v, str) and re.fullmatch('[a-f0-9]{64}', v) for v in (left, right))
        else:
            valid = all(isinstance(v, str) and bool(v) for v in (left, right))
        if not valid:
            missing.append(f'{label}缺失或不完整')
        elif left != right:
            reasons.append(f'{label}不同')
    if candidate.get('framework', 'nanochat') != 'nanochat' or candidate.get('format', 'nanochat-checkpoint-v1') != 'nanochat-checkpoint-v1':
        reasons.append('当前评测器不支持此模型格式或框架')
    return {'status': 'incompatible' if reasons else 'unknown' if missing else 'compatible', 'reasons': reasons + missing}


def training_differences(reference, candidate):
    labels = {'token_budget': '训练 Token 预算', 'device_batch_size': '单卡批量', 'sequence_len': '序列长度',
              'learning_rate': '学习率', 'optimizer': '优化器', 'global_batch_size': '全局批量'}
    return [f'{label}不同' if key in reference and key in candidate else f'{label}记录不完整'
            for key, label in labels.items() if key not in reference or key not in candidate or reference[key] != candidate[key]]


def parameter_rows(reference, candidate, training_configs, candidate_training):
    rows = []
    def add(key, label, left, right):
        known = left is not None and right is not None
        rows.append({'key': key, 'label': label, 'reference': left, 'candidate': right,
                     'same': known and left == right, 'missing': not known})
    for key, label in [('framework', '训练框架'), ('format', '模型格式'),
                       ('tokenizer_sha256', 'Tokenizer 指纹'), ('base_weights_sha256', '基础权重指纹')]:
        add(key, label, reference.get(key), candidate.get(key))
    left = reference.get('model_config') or {}
    right = candidate.get('model_config') or {}
    left = left if isinstance(left, dict) else {}
    right = right if isinstance(right, dict) else {}
    for key in sorted(left.keys() | right.keys() | STRUCTURE_KEYS):
        add('model_config.' + key, '模型结构 · ' + key, left.get(key), right.get(key))
    ignored = {'nodes', 'node_count', 'training_nodes', 'mixing_nodes', 'evaluation_nodes', 'output_obs_uri'}
    for index, training in enumerate(training_configs):
        for key in sorted((training.keys() | candidate_training.keys()) - ignored):
            add(f'training.{index}.{key}', f'训练配置 {index + 1} · {key}', training.get(key), candidate_training.get(key))
    return rows


def compare_catalog(catalog, reference, reader=None):
    """Use records' stored output URIs, never a caller-supplied candidate path."""
    if not catalog:
        return []
    reader = reader or read_metadata
    cache = {}
    def read(uri):
        if uri not in cache:
            try:
                cache[uri] = (reader(uri), '')
            except ValueError as exc:
                cache[uri] = ({}, str(exc))
        return cache[uri]
    try:
        uri = reference['model_obs_uri'].rstrip('/') + '/' + identity_filename(reference['base_model_tag'])
        base, base_error = read(uri)
    except (KeyError, TypeError, AttributeError, ValueError):
        base, base_error = {}, '本次基础模型地址或标签无效'
    result = []
    for model in catalog:
        manifest, error = read(model['obs_uri'].rstrip('/') + '/models_manifest.json')
        items = manifest.get('models', [])
        matches = [m for m in items if isinstance(m, dict) and m.get('id') == model['strategy_id']] if isinstance(items, list) else []
        identity = matches[0].get('comparison_identity', {}) if len(matches) == 1 else {}
        if not isinstance(identity, dict):
            identity = {}
        check = compare_identity(base.get('identity', {}) if isinstance(base.get('identity'), dict) else {}, identity)
        if model.get('framework') != 'nanochat':
            check = {'status': 'incompatible', 'reasons': ['当前评测器不支持此训练框架']}
        check['reasons'] += [e for e in (base_error, error) if e]
        if not error and len(matches) != 1:
            check['reasons'].append('模型清单中未找到唯一的所选策略')
        check['parameters'] = parameter_rows(
            base.get('identity') if isinstance(base.get('identity'), dict) else {}, identity,
            reference.get('training_configs', []), model.get('training_config', {}))
        check['status'] = 'compatible' if check['status'] == 'compatible' and all(row['same'] for row in check['parameters']) else 'different'
        check['warnings'] = []
        for training in reference.get('training_configs', []):
            check['warnings'] += training_differences(training, model.get('training_config', {}))
        if reference.get('input_data_obs_uri') != model.get('input_data_obs_uri'):
            check['warnings'].append('候选数据集地址不同')
        check['warnings'] += ['同一 OBS 地址不保证数据版本一致；实际训练 Token 数及随机种子需在报告中核对']
        check['warnings'] = list(dict.fromkeys(check['warnings']))
        result.append({**model, 'comparison': check})
    return result


def validate_selection(config, catalog):
    config['evaluation'].pop('model_comparison', None)
    selected = set(config['evaluation'].get('model_ids', []))
    if not selected:
        return
    config['evaluation']['comparison_policy'] = 'allow-differences'
    if selected - catalog.keys():
        raise ValueError('历史模型不可用或训练尚未成功')
    reference = {'model_obs_uri': config['resources']['nanochat_model_obs_uri'],
                 'base_model_tag': config['training'].get('base_model_tag', 'd24'),
                 'training_configs': [s['training'] for s in config['strategies']],
                 'input_data_obs_uri': config['input_data_obs_uri']}
    checks = compare_catalog([m for m in catalog.values() if m['id'] in selected], reference)
    # Detailed rows belong to the UI response, not the size-limited job environment.
    config['evaluation']['model_comparison'] = [
        {'id': m['id'], **{k: v for k, v in m['comparison'].items() if k != 'parameters'}} for m in checks]


def main():
    import argparse
    parser = argparse.ArgumentParser(description='生成基础模型元数据；仅在本地读取权重，不上传文件')
    parser.add_argument('--model-dir', required=True)
    parser.add_argument('--tag', default='d24')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    identity = build_identity(args.model_dir, args.tag)
    check = compare_identity(identity, identity)
    if check['status'] != 'compatible':
        parser.error('；'.join(check['reasons']))
    with Path(args.output).open('x', encoding='utf-8') as stream:
        json.dump({'version': 1, 'identity': identity}, stream, ensure_ascii=False, indent=2)
    print(f'已生成 {args.output}，请上传到模型 OBS 根目录，文件名为 {identity_filename(args.tag)}')


if __name__ == '__main__':
    main()
