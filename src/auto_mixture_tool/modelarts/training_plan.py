"""Read mounted checkpoint metadata and resolve batches before cloud submission."""
from __future__ import annotations

import copy
import json
import math
import re

from nanochat_mid_compare.distributed_runtime import Topology, training_plan_from_metadata
from .model_comparison import MAX_METADATA_BYTES

MAX_INTEGER = 9007199254740991


def positive_integer(value, label, maximum=MAX_INTEGER):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f"{label}必须为 1–{maximum} 的整数")
    return value


def read_checkpoint_metadata(model_uri, tag):
    from .input_validation import mounted_directory
    if not isinstance(tag, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', tag):
        raise ValueError('基础模型标签无效')
    model = mounted_directory(model_uri).resolve()
    base = (model / 'base_checkpoints' / tag).resolve()
    if not base.is_relative_to(model):
        raise ValueError('基础检查点不能链接到模型目录外部')
    files = sorted(base.glob('meta_*.json'))
    if not files:
        raise ValueError(f'未找到基础模型 {tag} 的 meta_*.json，无法计算训练计划')
    path = files[-1]
    if not path.resolve().is_relative_to(base):
        raise ValueError('基础模型元数据不能链接到检查点目录外部')
    try:
        with path.open('rb') as stream:
            raw = stream.read(MAX_METADATA_BYTES + 1)
        if len(raw) > MAX_METADATA_BYTES:
            raise ValueError('基础模型元数据超过 1 MiB')
        metadata = json.loads(raw)
        if not isinstance(metadata, dict) or not isinstance(metadata.get('model_config', {}), dict):
            raise ValueError('基础模型元数据须为 JSON 对象')
        return metadata
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError('无法读取基础模型元数据，请检查挂载、权限及 JSON 格式') from error


def plan_training_jobs(model_uri, jobs):
    """Keep one automatic batch compatible with every selected training topology."""
    if not isinstance(jobs, list) or not 1 <= len(jobs) <= 1000:
        raise ValueError('训练计划需要 1–1000 项节点配置')
    cache, entries = {}, []
    for job in jobs:
        training = job['training']
        nodes = positive_integer(job['nodes'], '训练节点数', 16)
        devices = positive_integer(training.get('devices_per_node', 8), '每节点卡数', 8)
        if devices != 8:
            raise ValueError('训练每节点仅支持 8 张 NPU')
        device_batch = positive_integer(training.get('device_batch_size', 1), '单卡 batch')
        tag = training.get('base_model_tag', 'd24')
        if not isinstance(tag, str):
            raise ValueError('基础模型标签无效')
        if tag not in cache:
            cache[tag] = read_checkpoint_metadata(model_uri, tag)
        metadata = cache[tag]
        sequence = positive_integer(metadata.get('max_seq_len', metadata.get('model_config', {}).get('sequence_len', 2048)), '序列长度')
        context = positive_integer(metadata.get('model_config', {}).get('sequence_len', sequence), '模型上下文长度')
        if sequence > context:
            raise ValueError('训练序列长度超过模型上下文长度')
        baseline = positive_integer(metadata.get('total_batch_size', 524288), '基础模型全局 batch')
        micro = positive_integer(nodes * devices * device_batch * sequence, '单次全局前向 Token 数')
        mode = training.get('batch_size_mode', 'fixed' if training.get('total_batch_size') is not None else 'auto')
        if mode not in ('auto', 'fixed'):
            raise ValueError('全局 batch 模式必须为 auto 或 fixed')
        steps = training.get('num_iterations', 0)
        if type(steps) is not int or not 0 <= steps <= MAX_INTEGER:
            raise ValueError('固定训练步数必须为非负整数')
        budget = training.get('token_budget')
        if budget is not None:
            positive_integer(budget, '训练 Token 预算')
            if steps:
                raise ValueError('训练 Token 预算与固定训练步数不能同时设置')
        entries.append(dict(job, metadata=metadata, mode=mode, micro_tokens=micro,
                            checkpoint_batch_size=baseline, sequence_len=sequence))
    multiple = math.lcm(*(item['micro_tokens'] for item in entries))
    baseline = max(item['checkpoint_batch_size'] for item in entries)
    recommended = positive_integer(((baseline + multiple - 1) // multiple) * multiple, '推荐全局 batch')
    plans, errors = [], []
    for item in entries:
        training = item['training']
        try:
            batch = recommended if item['mode'] == 'auto' else positive_integer(training.get('total_batch_size'), '手动全局 batch')
        except ValueError as error:
            batch = None
            errors.append(str(error))
        plan = {key: item[key] for key in ('nodes', 'sequence_len', 'micro_tokens', 'checkpoint_batch_size')}
        plan.update(strategy_id=item.get('strategy_id'), batch_size_mode=item['mode'],
                    total_batch_size=batch, grad_accum_steps=None, num_iterations=None,
                    actual_tokens=None, rounding_tokens=None)
        if batch is None:
            pass
        elif batch % item['micro_tokens']:
            errors.append(f"{item['nodes']} 节点的全局 batch {batch} 必须是 {item['micro_tokens']} 的整数倍；可使用推荐值 {recommended}")
        else:
            budget, steps = training.get('token_budget'), training.get('num_iterations', 0)
            plan.update(training_plan_from_metadata(item['metadata'], Topology(item['nodes'], 0, 8, '127.0.0.1', 29500),
                                                   training.get('device_batch_size', 1), budget if budget is not None else 1,
                                                   steps=steps, total_batch_size=batch))
            positive_integer(plan['actual_tokens'], '实际训练 Token 数')
            # Historical jobs may derive their token budget from sampled data later.
            if budget is None and not steps:
                plan.update(token_budget=None, num_iterations=None, actual_tokens=None,
                            rounding_tokens=None, budget_mode='dataset')
        plans.append(plan)
    return {'ready': not errors, 'recommended_batch_size': recommended,
            'common_multiple': multiple, 'plans': plans, 'errors': errors}


def workflow_training_plan(config):
    if config.get('reuse', {}).get('stage') == 'evaluation' or config.get('job_reuse', {}).get('key') == 'evaluation':
        return None
    if config.get('execution_mode') == 'parallel':
        retry = config.get('job_reuse', {}).get('key', '')
        jobs = [{'strategy_id': strategy['id'], 'nodes': strategy['training_nodes'],
                 'training': {**config['training'], **strategy.get('training', {})}}
                for strategy in config['strategies'] if not retry or retry in
                (f"training-{strategy['id']}", f"mixing-{strategy['id']}")]
    else:
        jobs = [{'strategy_id': None, 'nodes': config['training_nodes'], 'training': config['training']}]
    result = plan_training_jobs(config['resources']['nanochat_model_obs_uri'], jobs)
    if not result['ready']:
        raise ValueError('；'.join(result['errors']))
    return result


def apply_training_plan(config, result):
    """Apply saved results to payload copies without changing the request identity."""
    if not result:
        return
    plans = {item['strategy_id']: item for item in result['plans']}
    active = [item for item in config['strategies'] if item['id'] in plans]
    selected = plans.get(None) or (plans[active[0]['id']] if len(active) == 1 else None)
    if selected:
        config['training'].update(total_batch_size=selected['total_batch_size'], batch_size_mode=selected['batch_size_mode'])
    for strategy in active:
        plan = plans[strategy['id']]
        strategy['training'] = copy.deepcopy(strategy.get('training', config['training']))
        strategy['training'].update(total_batch_size=plan['total_batch_size'], batch_size_mode=plan['batch_size_mode'])
