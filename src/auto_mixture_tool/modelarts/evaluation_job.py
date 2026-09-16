"""Explicit checkpoint handoff between training and evaluation jobs."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def publish_models(config, root, data, identity=None):
    """Publish the completion manifest last, only after all models are present."""
    run = os.environ['AMT_RUN_ID']
    base = config['training'].get('base_model_tag', 'd24')
    models = []
    for strategy in config['strategies']:
        kind = strategy['type']
        part = f"manual_{strategy['id']}" if kind == 'manual' else kind
        tag = f'{base}_stem_{part}_{run}'
        folder = root / tag
        weights = sorted(folder.glob('model_*.pt'))
        if not weights:
            raise ValueError(f'训练输出不完整：找不到 {folder}/model_*.pt，评测不会启动')
        weight = weights[-1]
        step = int(weight.stem.removeprefix('model_'))
        meta = folder / weight.name.replace('model_', 'meta_').replace('.pt', '.json')
        files = []
        for path in (weight, meta):
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError(f'训练输出不完整：{path}')
            files.append({'path': path.relative_to(root).as_posix(), 'size': path.stat().st_size,
                          'sha256': digest(path)})
        model_config = json.loads(meta.read_text(encoding='utf-8')).get('model_config', {})
        models.append({'id': strategy['id'], 'name': strategy.get('model_name') or strategy.get('name', kind),
                       'model_tag': tag, 'step': step, 'files': files,
                       'training_config': config['training'],
                       'strategy_config': {k: strategy[k] for k in ('type', 'seed', 'proxy_experiments', 'proxy_steps', 'search_count', 'ratios', 'sampling_bounds') if k in strategy},
                       'model_config': model_config,
                       'comparison_identity': {**(identity or {}), 'model_config': model_config},
                       'configured_ratios': strategy.get('ratios', {})})
    manifest = {'version': 1, 'run': run, 'models': models,
                'dataset_stats': json.loads((data / 'dataset_stats.json').read_text(encoding='utf-8'))}
    target = root / 'models_manifest.json'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(target)


def validate_models(root, strategy_id=None):
    manifest = json.loads((root / 'models_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version') != 1 or not manifest.get('models'):
        raise ValueError('模型清单无效或为空')
    if strategy_id is not None:
        manifest['models'] = [m for m in manifest['models'] if m['id'] == strategy_id]
        if len(manifest['models']) != 1:
            raise ValueError('模型清单与所选策略不匹配')
    for model in manifest['models']:
        tag = model['model_tag']
        if Path(tag).name != tag or '/' in tag or '\\' in tag or tag in {'.', '..'}:
            raise ValueError('模型标签不能包含路径')
        if not model.get('files'):
            raise ValueError('模型清单缺少文件')
        for item in model['files']:
            path = (root / item['path']).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                raise ValueError(f'模型文件缺失或路径无效：{item["path"]}')
            if path.stat().st_size != item['size'] or digest(path) != item['sha256']:
                raise ValueError(f'模型文件校验失败：{item["path"]}')
    return manifest


def evaluation_models(config, inputs):
    """Resolve only the selected model in each source manifest, with its own tokenizer."""
    sources = config.get('evaluation_sources')
    if not sources:
        manifest = validate_models(inputs / 'trained_models')
        for model in manifest['models']:
            model['_root'] = str(inputs / 'trained_models')
            model['_tokenizer'] = str(inputs / 'nanochat_model_dir_1/tokenizer')
        return manifest
    result = {'run': os.environ.get('AMT_RUN_ID', ''), 'models': [], 'dataset_stats': {}}
    for index, source in enumerate(sources):
        root = inputs / source['mount']
        manifest = validate_models(root, source['strategy_id'])
        matches = [m for m in manifest['models'] if m['id'] == source['strategy_id']]
        if len(matches) != 1:
            raise ValueError(f'模型清单与所选策略不匹配：{source["name"]}')
        model = matches[0]
        if not model.get('strategy_config'):
            model['strategy_config'] = {k: v for k, v in source.get('strategy_config', {}).items()
                                        if k in {'type', 'seed', 'proxy_experiments', 'proxy_steps', 'search_count', 'ratios', 'sampling_bounds'}}
        model.update(id=f'model_{index}', catalog_id=source['id'], name=source['name'],
                     source_workflow_id=source['workflow_id'], source_obs_uri=source['obs_uri'],
                     _root=str(root), _tokenizer=str(inputs / source['tokenizer_mount']))
        result['models'].append(model)
        result['dataset_stats'][source['id']] = manifest['dataset_stats']
    return result


def run_evaluation(config):
    from nanochat_mid_compare.eval_assets import validate_assets, task_definitions
    inputs = Path('/home/ma-user/modelarts/inputs')
    tasks, labels = task_definitions(inputs / 'nanochat_npu_dir_3')
    packages = []
    if config['evaluation']['datasets']:
        packages.append(('builtin', inputs / 'eval_bundle_dir_6', config['evaluation']['datasets']))
    for index, package in enumerate(config['evaluation'].get('obs_packages', [])):
        source = inputs / f'eval_package_{index}'
        validate_package(source)
        packages.append((f'package_{index}', source, ['core']))
    # Validate every selected package before any model evaluation starts.
    for name, source, selected in packages:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / 'eval_bundle').symlink_to(source, target_is_directory=True)
            from nanochat_mid_compare.prepare_offline_eval_bundle import materialize
            materialize(source, base)
            validate_assets(base, selected, tasks, labels)
    for name, source, selected in packages:
        current = {**config, 'evaluation': {**config['evaluation'], 'datasets': selected}}
        _run_evaluation(current, source, name if config['evaluation'].get('obs_packages') else None)


def validate_package(source):
    import yaml
    from nanochat_mid_compare.eval_assets import validate_task_records
    source = Path(source)
    try:
        for filename in ('core.yaml', 'eval_meta_data.csv'):
            if not (source / filename).resolve().is_relative_to(source.resolve()):
                raise ValueError(f'{filename} 不能链接到评测包外部')
        tasks = yaml.safe_load((source / 'core.yaml').read_text(encoding='utf-8'))['icl_tasks']
        if not isinstance(tasks, list) or not tasks:
            raise ValueError('icl_tasks 不能为空')
        labels = set()
        for task in tasks:
            if task['icl_task_type'] not in {'multiple_choice', 'generation'}:
                raise ValueError(f"不支持任务类型：{task['icl_task_type']}")
            if not isinstance(task['label'], str) or task['label'] in labels:
                raise ValueError('任务名称无效或重复')
            labels.add(task['label'])
            if not isinstance(task['dataset_uri'], str):
                raise ValueError('dataset_uri 必须是相对路径')
            if not isinstance(task['num_fewshot'], list) or not task['num_fewshot'] or type(task['num_fewshot'][0]) is not int or task['num_fewshot'][0] < 0:
                raise ValueError('num_fewshot 必须包含非负整数')
            if task['icl_task_type'] == 'generation' and task.get('answer_extractor', 'gsm8k') not in {'gsm8k', 'math'}:
                raise ValueError('不支持该生成题答案提取方式')
            validate_task_records(source, task)
        if not (source / 'eval_meta_data.csv').is_file():
            raise ValueError('缺少 eval_meta_data.csv')
        with (source / 'eval_meta_data.csv').open(encoding='utf-8') as stream:
            baselines = {}
            for row in csv.DictReader(stream):
                value = float(row['Random baseline'])
                if not 0 <= value < 100:
                    raise ValueError('Random baseline 必须在 [0, 100) 范围')
                baselines[row['Eval Task']] = value
            if not labels.issubset(baselines):
                raise ValueError('eval_meta_data.csv 缺少任务对应基线')
        return sorted(labels)
    except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f'评测集不符合当前 NanoChat 要求：{source}：{exc}') from None


def _run_evaluation(config, bundle, report_name):
    from .stage_runner import OUTPUT, WORKSPACE
    inputs = Path('/home/ma-user/modelarts/inputs')
    manifest = evaluation_models(config, inputs)
    settings = config['evaluation']
    if settings.get('comparison_policy') in {'same-model-type', 'allow-differences'}:
        validate_comparison_models(manifest['models'], allow_differences=settings['comparison_policy'] == 'allow-differences')
    nodes = int(os.environ.get('MA_NUM_HOSTS', '1'))
    rank = int(os.environ.get('VC_TASK_INDEX', '0'))
    if nodes != config.get('evaluation_nodes', 1):
        raise ValueError('评测节点数与配置不一致')
    master = os.environ.get('VC_WORKER_HOSTS', '127.0.0.1').split(',')[0]
    if nodes > 1 and not os.environ.get('VC_WORKER_HOSTS'):
        raise ValueError('多节点评测缺少 VC_WORKER_HOSTS')
    report = OUTPUT.parent / 'reports_output' if settings.get('output_obs_uri') else OUTPUT / 'training/results'
    if report_name:
        report = report / report_name
    report.mkdir(parents=True, exist_ok=True)
    repo = inputs / 'nanochat_npu_dir_3'
    with tempfile.TemporaryDirectory(prefix='amt-evaluation-') as directory:
        runtime = Path(directory)
        (runtime / 'eval_bundle').symlink_to(bundle, target_is_directory=True)
        from nanochat_mid_compare.prepare_offline_eval_bundle import materialize
        materialize(bundle, runtime)
        env = os.environ.copy()
        env.update(NANOCHAT_BASE_DIR=str(runtime), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                   HF_DATASETS_OFFLINE='1', PYTHONPATH=f'{WORKSPACE}:{WORKSPACE / "src"}:{repo}:' + env.get('PYTHONPATH', ''))
        env['RANK_SIZE'] = str(nodes * settings.get('devices_per_node', 8))
        env['HCCL_EXEC_TIMEOUT'] = '1200'
        results = []
        for model in manifest['models']:
            for name, path in (('mid_checkpoints', model['_root']), ('tokenizer', model['_tokenizer'])):
                link = runtime / name
                if link.is_symlink():
                    link.unlink()
                link.symlink_to(path, target_is_directory=True)
            command = [sys.executable, '-m', 'torch.distributed.run', f'--nnodes={nodes}',
                       f'--node_rank={rank}', f'--nproc_per_node={settings.get("devices_per_node", 8)}',
                       '--rdzv_backend=static', f'--rdzv_endpoint={master}:{os.environ.get("MASTER_PORT", "29500")}',
                       '-m', 'nanochat_mid_compare.offline_base_eval', '--eval=core', '--model-type=mid',
                       f'--model-tag={model["model_tag"]}', f'--step={model["step"]}',
                       '--eval-benchmarks=' + ','.join(settings['datasets']),
                       f'--core-eval-batch-size={settings.get("core_eval_batch_size", 16)}',
                       f'--max-per-task={settings.get("max_per_task", -1)}']
            subprocess.run(command, cwd=repo, env=env, check=True)
            if rank == 0:
                source = runtime / 'base_eval' / f'mid_model_{model["step"]:06d}.csv'
                target = report / f'{model["id"]}.csv'
                shutil.copyfile(source, target)
                with target.open(encoding='utf-8') as stream:
                    metrics = list(csv.DictReader(stream, skipinitialspace=True))
                results.append({**{k: v for k, v in model.items() if not k.startswith('_')}, 'metrics': metrics})
        if rank == 0:
            (report / 'comparison_report.json').write_text(json.dumps({
                'run': manifest['run'], 'models': results, 'dataset_stats': manifest['dataset_stats'],
                'evaluation': settings,
                'comparability': settings.get('model_comparison', []),
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            lines = ['# 配比模型评测对比', '', '| 策略 | 评测项 | Accuracy | Centered |', '|---|---|---|---|']
            for model in results:
                for row in model['metrics']:
                    row = {key.strip(): value.strip() for key, value in row.items()}
                    name = str(model['name']).replace('|', '\\|').replace('\n', ' ')
                    lines.append(f"| {name} | {row.get('Task', '')} | {row.get('Accuracy', '')} | {row.get('Centered', '')} |")
            lines += ['', '配比与采样统计详见 comparison_report.json 的 dataset_stats。']
            for check in settings.get('model_comparison', []):
                for warning in check.get('reasons', []) + check.get('warnings', []):
                    lines.append(f'- 对比条件提示：{check["id"]}：{warning}')
            (report / 'comparison_report.md').write_text('\n'.join(lines), encoding='utf-8')


def validate_comparison_models(models, allow_differences=False):
    from .model_comparison import compare_identity, directory_digest
    reference = None
    for model in models:
        identity = dict(model.get('comparison_identity') or {})
        meta_path = f'{model["model_tag"]}/meta_{model["step"]:06d}.json'
        if meta_path not in {item['path'] for item in model['files']}:
            raise ValueError(f'评测模型 {model["name"]} 缺少已校验的结构文件')
        actual_config = json.loads((Path(model['_root']) / meta_path).read_text(encoding='utf-8')).get('model_config', {})
        recorded_configs = [value for value in (model.get('model_config'), identity.get('model_config')) if value]
        if any(actual_config != value for value in recorded_configs) or (not allow_differences and len(recorded_configs) != 2):
            raise ValueError(f'评测模型 {model["name"]} 的实际结构与清单不同')
        tokenizer = Path(model['_tokenizer'])
        actual = directory_digest(tokenizer, [p for p in tokenizer.rglob('*') if p.is_file()])
        recorded_tokenizer = identity.get('tokenizer_sha256')
        if not actual or (recorded_tokenizer and actual != recorded_tokenizer) or (not allow_differences and not recorded_tokenizer):
            raise ValueError(f'评测模型 {model["name"]} 的 Tokenizer 与训练记录不同或记录缺失')
        identity['model_config'] = actual_config
        model['model_config'] = actual_config
        if allow_differences:
            if identity.get('framework', 'nanochat') != 'nanochat' or identity.get('format', 'nanochat-checkpoint-v1') != 'nanochat-checkpoint-v1':
                raise ValueError(f'评测器不支持模型 {model["name"]} 的框架或格式')
            continue
        reference = reference or identity
        result = compare_identity(reference, identity)
        if result['status'] != 'compatible':
            raise ValueError(f'评测模型 {model["name"]} 不满足同类型对比要求：' + '；'.join(result['reasons']))
