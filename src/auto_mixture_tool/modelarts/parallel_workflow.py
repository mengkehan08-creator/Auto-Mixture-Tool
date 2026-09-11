"""Per-strategy job graph. Scheduling state is persisted before every POST."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime

import requests

TERMINAL = {'SUCCEEDED', 'FAILED', 'BLOCKED', 'NEEDS_ATTENTION'}


def job_name(value):
    value = str(value or '').strip()
    if value and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', value):
        raise ValueError('作业名称须以英文字母开头，包含 1–64 位字母、数字、下划线或连字符')
    return value


def validate(manager, config):
    if config.get('reuse'):
        raise ValueError('并行实验请在作业详情使用单作业重试接口')
    active_limit = config.get('max_active_jobs', 8)
    if type(active_limit) is not int or not 1 <= active_limit <= 1000:
        raise ValueError('max_active_jobs 必须为 1–1000 的整数')
    config['max_active_jobs'] = active_limit
    if config.get('job_reuse'):
        retry_source(manager, config['job_reuse'])
    for strategy in config['strategies']:
        devices = strategy.get('devices_per_node', 8)
        if type(devices) is not int or not 1 <= devices <= 8:
            raise ValueError('每节点设备数必须为 1–8')
        strategy['devices_per_node'] = devices
        for stage in ('mixing', 'training'):
            key = stage + '_nodes'
            nodes = strategy.get(key, config[key])
            if type(nodes) is not int or not 1 <= nodes <= 16:
                raise ValueError(f'{strategy.get("name", strategy["id"])} 的 {key} 必须为 1–16')
            strategy[key] = nodes
            strategy[stage + '_job_name'] = job_name(strategy.get(stage + '_job_name'))
            priority = strategy.get(stage + '_priority', 2 if stage == 'mixing' else config['priority'])
            if type(priority) is not int or priority not in (1, 2, 3):
                raise ValueError('作业优先级必须为 1、2 或 3')
            strategy[stage + '_priority'] = priority
            command = strategy.get(stage + '_command', '')
            if not isinstance(command, str) or '\x00' in command or len(command) > 32768:
                raise ValueError('独立作业 command 必须为不超过 32768 字符的文本')
        name = strategy.get('model_name', '')
        if not isinstance(name, str) or len(name) > 128 or any(ord(c) < 32 for c in name):
            raise ValueError('模型名称最多 128 字符，不能包含控制字符')
        strategy['model_name'] = name.strip()
        overrides = strategy.get('training', {})
        if not isinstance(overrides, dict) or set(overrides) - (set(config['training']) | {'token_budget', 'output_obs_uri'}):
            raise ValueError('策略训练参数须使用公共训练配置中的字段')
        # Use the same validator for shared and per-job training settings.
        single = dict(config)
        single['training'] = copy.deepcopy(config['training'])
        single.pop('execution_mode', None)
        single['strategies'] = [copy.deepcopy(strategy)]
        single['commands'] = {
            stage: strategy.get(stage + '_command') or config.get('commands', {}).get(stage, manager._command(stage))
            for stage in ('mixing', 'training', 'evaluation')
        }
        single['training'].update(overrides)
        strategy['training'] = manager._validate(single)['training']
    config['evaluation']['job_name'] = job_name(config['evaluation'].get('job_name'))
    priority = config['evaluation'].get('priority', config['priority'])
    if type(priority) is not int or priority not in (1, 2, 3):
        raise ValueError('评测优先级必须为 1、2 或 3')
    config['evaluation']['priority'] = priority
    ids = config['evaluation'].get('model_ids', [])
    if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) or len(ids) > 64:
        raise ValueError('历史模型选择必须为模型 ID 列表，最多 64 项')
    config['evaluation']['model_ids'] = list(dict.fromkeys(ids))
    catalog = {m['id']: m for m in models(manager)}
    for model_id in ids:
        if model_id not in catalog:
            raise ValueError(f'历史模型不可用或训练尚未成功：{model_id}')
        if catalog[model_id]['framework'] != 'nanochat':
            raise ValueError('当前评测仅支持 NanoChat 兼容模型')
    from .model_comparison import validate_selection
    validate_selection(config, catalog)


def planned_jobs(config):
    jobs = []
    for strategy in config['strategies']:
        for stage in ('mixing', 'training'):
            jobs.append({'key': f'{stage}-{strategy["id"]}', 'module': stage,
                         'strategy_id': strategy['id'], 'strategy_name': strategy.get('name', strategy['id']),
                         'name': strategy.get(stage + '_job_name', ''),
                         'nodes': strategy[stage + '_nodes'],
                         'priority': strategy[stage + '_priority']})
    if config['evaluation']['datasets'] or config['evaluation'].get('obs_packages'):
        jobs.append({'key': 'evaluation', 'module': 'evaluation', 'name': config['evaluation']['job_name'],
                     'nodes': config['evaluation_nodes'], 'priority': config['evaluation']['priority']})
    return jobs


def strategy_stem(strategy):
    if strategy['type'] == 'quadmix':
        return f'ex-{strategy["proxy_experiments"]}-{strategy["proxy_steps"]}'
    stem = f'{strategy["type"]}-s{strategy["seed"]}'
    if strategy['type'] == 'manual' or strategy.get('script_obs_uri') or strategy.get('script_upload'):
        parameters = {k: strategy.get(k) for k in ('ratios', 'script_obs_uri', 'script_upload', 'script_config')}
        digest = hashlib.sha256(json.dumps(parameters, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:6]
        stem += '-' + digest
    return stem


def assign_names(manager, record, stamp):
    """Resolve names once without mutating submitted config (idempotency and copies)."""
    used = {j['name'].casefold() for r in manager.records.values() for j in r['jobs']}
    used.update(j['name'].casefold() for j in record['jobs'] if j['name'])
    record['strategy_names'] = {}
    by_id = {s['id']: s for s in record['config']['strategies']}
    for index, job in enumerate(record['jobs']):
        strategy = by_id.get(job.get('strategy_id'))
        if strategy:
            stem = strategy_stem(strategy)
            if job['module'] == 'training':
                training = strategy['training']
                budget = (f't{training["token_budget"]}' if training.get('token_budget') else
                          f'step{training["num_iterations"]}' if training.get('num_iterations') else 'auto')
                stem = f'train-{stem}-{budget}'
        else:
            stem = 'evaluation'
        if not job['name']:
            # Reserve space for timestamp and collision suffix under ModelArts' 64-char limit.
            if len(stem) > 28:
                stem = stem[:19] + '-' + hashlib.sha256(stem.encode()).hexdigest()[:8]
            name = f'{stem}-{stamp}'
            counter = 0
            while name.casefold() in used:
                counter += 1
                name = f'{stem}-{stamp}-{record["id"][:6]}-{index}-{counter}'
            job['name'] = job_name(name)
            used.add(name.casefold())
        if strategy and job['module'] == 'mixing':
            record['strategy_names'][strategy['id']] = strategy.get('name', '').strip() or job['name']
    for job in record['jobs']:
        if job.get('strategy_id'):
            job['strategy_name'] = record['strategy_names'][job['strategy_id']]


def check_names(manager, jobs):
    manager._load_disk()
    existing = {j['name'] for r in manager.records.values() for j in r['jobs']}
    batch = set()
    for job in jobs:
        name = job.get('name')
        if not name or job.get('reused'):
            continue
        if name.casefold() in batch or name.casefold() in {n.casefold() for n in existing}:
            raise ValueError(f'作业名称重复，不能提交：{name}')
        batch.add(name.casefold())


def retry_source(manager, reuse):
    if not isinstance(reuse, dict) or set(reuse) != {'workflow_id', 'key'}:
        raise ValueError('单作业复用必须指定 workflow_id 和 key')
    manager.get(reuse['workflow_id'])
    source = manager.records[reuse['workflow_id']]
    if source.get('pipeline_version') != 4 or source.get('delete_requested') or source['status'] not in {'FAILED', 'SUCCEEDED'}:
        raise ValueError('仅可重试已结束、结果明确的并行实验')
    job = next((j for j in source['jobs'] if j['key'] == reuse['key']), None)
    if not job or any(j['status'] != 'SUCCEEDED' for j in source['jobs'] if j['key'] in job['depends_on']):
        raise ValueError('此作业前序输出尚未全部成功，不能直接复用')
    return source


def retry(manager, workflow_id, key, edits):
    source = retry_source(manager, {'workflow_id': workflow_id, 'key': key})
    if set(edits) - {'name', 'nodes', 'priority', 'training', 'evaluation', 'authorization', 'command', 'request_id'}:
        raise ValueError('重试参数包含不支持的字段')
    config = copy.deepcopy(source['config'])
    config.pop('request_id', None)
    config['job_reuse'] = {'workflow_id': workflow_id, 'key': key}
    if edits.get('request_id'):
        config['request_id'] = edits['request_id']
    for s in config['strategies']:
        s['mixing_job_name'] = s['training_job_name'] = ''
    config['evaluation']['job_name'] = ''
    job = next(j for j in source['jobs'] if j['key'] == key)
    stage = job['module']
    if stage == 'evaluation':
        config['evaluation'].update(edits.get('evaluation', {}))
        config['evaluation'].update(job_name=edits.get('name', ''), priority=edits.get('priority', job['priority']))
        config['evaluation_nodes'] = edits.get('nodes', job['nodes'])
    else:
        strategy = next(s for s in config['strategies'] if s['id'] == job['strategy_id'])
        strategy[stage + '_job_name'] = edits.get('name', '')
        strategy[stage + '_nodes'] = edits.get('nodes', job['nodes'])
        strategy[stage + '_priority'] = edits.get('priority', job['priority'])
        if stage == 'training':
            updates = edits.get('training', {})
            # Changing the base model invalidates the tokenizer-dependent sampling output.
            if set(updates) - {'token_budget', 'num_iterations', 'device_batch_size', 'devices_per_node', 'eval_every', 'core_metric_every'}:
                raise ValueError('训练阶段重试只能修改训练预算、批量、设备数和间隔；更换基础模型须重跑配比')
            strategy['training'].update(updates)
        if edits.get('command'):
            strategy[stage + '_command'] = edits['command']
    if edits.get('authorization'):
        config.setdefault('modelarts', {})['authorization'] = edits['authorization']
    if edits.get('command'):
        config.setdefault('commands', {s: manager._command(s) for s in ('mixing', 'training', 'evaluation')})[stage] = edits['command']
    return manager.create(config)


def initialize(manager, record, stamp):
    config = record['config']
    record['pipeline_version'] = 4
    record['branches'] = {}
    record['jobs'] = planned_jobs(config)
    assign_names(manager, record, stamp)
    for strategy in config['strategies']:
        sid = strategy['id']
        root = record['run_root_obs_uri'] + '/strategies/' + sid
        output = {'mixing': root + '/mixing/', 'sampled': root + '/sampled/',
                  'training': root + '/training/',
                  'models': record['outputs']['models'] + sid + '/',
                  'reports': record['outputs']['reports']}
        if strategy['training'].get('output_obs_uri'):
            output['models'] = strategy['training']['output_obs_uri'].rstrip('/') + '/runs/' + record['name'] + '/' + sid + '/'
        record['branches'][sid] = {'run_root_obs_uri': root, 'outputs': output}
    for index, job in enumerate(record['jobs']):
        job.update(status='WAITING', id=None)
        job['depends_on'] = ([] if job['module'] == 'mixing' else
                             [f'mixing-{job["strategy_id"]}'] if job['module'] == 'training' else
                             [j['key'] for j in record['jobs'] if j['module'] == 'training'])
        if job['module'] != 'evaluation':
            job['outputs'] = record['branches'][job['strategy_id']]['outputs']
            job['input_obs_uri'] = (config['input_data_obs_uri'] if job['module'] == 'mixing'
                                    else job['outputs']['sampled'])
        else:
            job['outputs'] = {'reports': record['outputs']['reports']}
    catalog = {m['id']: m for m in models(manager)}
    record['historical_models'] = [catalog[i] for i in config['evaluation'].get('model_ids', [])]
    if config.get('job_reuse'):
        source = retry_source(manager, config['job_reuse'])
        target = config['job_reuse']['key']
        reset = {target}
        for job in record['jobs']:
            if any(k in reset for k in job['depends_on']):
                reset.add(job['key'])
        original = {j['key']: j for j in source['jobs']}
        if set(original) != {j['key'] for j in record['jobs']}:
            raise ValueError('重试不能增删策略或评测作业')
        for sid, branch in record['branches'].items():
            previous = source['branches'][sid]['outputs']
            if f'mixing-{sid}' not in reset:
                record['strategy_names'][sid] = original[f'mixing-{sid}']['strategy_name']
            for stage, keys in (('mixing', ('sampled', 'mixing')), ('training', ('models', 'training'))):
                if f'{stage}-{sid}' not in reset:
                    for output in keys:
                        branch['outputs'][output] = previous[output]
        for job in record['jobs']:
            if job.get('strategy_id'):
                job['strategy_name'] = record['strategy_names'][job['strategy_id']]
            if job['module'] == 'training':
                job['input_obs_uri'] = record['branches'][job['strategy_id']]['outputs']['sampled']
            if job['key'] not in reset:
                previous = original[job['key']]
                job.update(name=previous['name'], id=None, reused=True, source_workflow_id=source['id'],
                           status=previous['status'], message=previous.get('message', ''))
        record['reused_from'] = source['id']
    check_names(manager, record['jobs'])


def model_record(record, strategy, output, job):
    training = strategy.get('training') or record['config']['training']
    name = record.get('strategy_names', {}).get(strategy['id']) or strategy.get('name') or strategy['id']
    return {'id': f'{record["id"]}:{strategy["id"]}',
            'name': strategy.get('model_name') or f'{name} · {record["name"]}',
            'workflow_id': record['id'], 'workflow_name': record['name'],
            'strategy_id': strategy['id'], 'strategy_name': name,
            'framework': training.get('framework', 'nanochat').lower(),
            'obs_uri': output, 'tokenizer_obs_uri': record['config']['resources']['nanochat_model_obs_uri'] + '/tokenizer/',
            'training_config': copy.deepcopy(training),
            'input_data_obs_uri': record['config']['input_data_obs_uri'],
            'base_model_obs_uri': record['config']['resources']['nanochat_model_obs_uri'],
            'strategy_config': {k: v for k, v in strategy.items() if k not in {'script_upload', 'training'}},
            'nodes': job['nodes'], 'job_name': job['name'], 'created_at': record['created_at'],
            'metadata_source': '提交配置；实际步数及模型结构见 OBS models_manifest.json'}


def models(manager):
    manager._load_disk()
    result = []
    for record in list(manager.records.values()):
        if (record.get('delete_requested') and record['status'] != 'DELETED') or record.get('pipeline_version') not in (3, 4):
            continue
        for strategy in record['config']['strategies']:
            job = next((j for j in record['jobs'] if j['module'] == 'training' and
                        (record['pipeline_version'] == 3 or j.get('strategy_id') == strategy['id'])), None)
            if not job or job['status'] not in {'SUCCEEDED', 'COMPLETED', 'SUCCESS'} or job.get('reused'):
                continue
            output = (record['branches'][strategy['id']]['outputs']['models']
                      if record['pipeline_version'] == 4 else record['outputs']['models'])
            result.append(model_record(record, strategy, output, job))
    return sorted(result, key=lambda m: m['created_at'], reverse=True)


def payload(manager, record, job):
    """Adapt a branch to the existing single-chain payload builder."""
    view = copy.deepcopy(record)
    config = view['config']
    config.pop('execution_mode', None)
    config.pop('job_reuse', None)
    config['priority'] = job['priority']
    stage = job['module']
    view['pipeline_version'] = 3
    view['jobs'] = [job, job, job]
    if stage != 'evaluation':
        strategy = next(s for s in config['strategies'] if s['id'] == job['strategy_id'])
        config['strategies'] = [strategy]
        strategy['name'] = job['strategy_name']
        strategy['model_name'] = strategy.get('model_name') or job['strategy_name']
        config['training'] = strategy['training']
        if strategy.get(stage + '_command', '').strip():
            config.setdefault('commands', {})[stage] = strategy[stage + '_command']
        config['training_nodes'] = strategy['training_nodes']
        config['mixing_nodes'] = strategy['mixing_nodes']
        view.update(copy.deepcopy(record['branches'][strategy['id']]))
        # Always mount the isolated model output, regardless of the user's root override.
        config['training']['output_obs_uri'] = view['outputs']['models']
    else:
        sources = []
        for strategy in record['config']['strategies']:
            training = next(j for j in record['jobs'] if j['key'] == f'training-{strategy["id"]}')
            sources.append(model_record(record, strategy, record['branches'][strategy['id']]['outputs']['models'], training))
        sources += record['historical_models']
        config['evaluation_sources'] = []
        for index, source in enumerate(sources):
            config['evaluation_sources'].append({**source, 'mount': f'evaluation_model_{index}',
                                                  'tokenizer_mount': f'evaluation_tokenizer_{index}'})
    result = manager._payload(view, stage)
    if stage == 'evaluation':
        inputs = result['algorithm']['inputs']
        inputs[:] = [i for i in inputs if i['name'] != 'trained_models']
        for source in config['evaluation_sources']:
            for mount, uri in ((source['mount'], source['obs_uri']), (source['tokenizer_mount'], source['tokenizer_obs_uri'])):
                inputs.append({'name': mount, 'local_dir': '/home/ma-user/modelarts/inputs/' + mount,
                               'access_method': 'env', 'remote': {'obs': {'obs_url': uri.rstrip('/') + '/'}}})
    return result


def tick(manager, record):
    """Poll jobs and admit ready work into this experiment's bounded active window."""
    from .workflow import ModelArtsRejected, SUCCESS_STATES, FAILURE_STATES, _state, _remote_error, _console_url, training_console_url
    jobs = {j['key']: j for j in record['jobs']}
    active_limit = record['config'].get('max_active_jobs', 8)
    for job in record['jobs']:
        if manager._stopping.is_set() or record.get('delete_requested'):
            return
        if job['status'] in TERMINAL:
            continue
        dependencies = [jobs[k] for k in job['depends_on']]
        if any(j['status'] in TERMINAL - {'SUCCEEDED'} for j in dependencies):
            job.update(status='BLOCKED', message='前序作业未成功，未提交此作业')
            manager._store(record)
            continue
        if any(j['status'] != 'SUCCEEDED' for j in dependencies):
            continue
        if not job.get('id'):
            if job['status'] == 'SUBMITTING':
                job.update(status='NEEDS_ATTENTION', message='上次提交结果不明确，请在 ModelArts 核对，禁止自动重复提交')
                manager._store(record)
                continue
            # Uncertain submissions also reserve a slot until manually resolved.
            active = sum(j['status'] not in {'WAITING', 'SUCCEEDED', 'FAILED', 'BLOCKED'} for j in record['jobs'])
            if active >= active_limit:
                continue
            try:
                body = payload(manager, record, job)
                job['status'] = 'SUBMITTING'
                manager._store(record)
                response = manager._client(record).submit(body)
                if _remote_error(response):
                    raise ModelArtsRejected(_remote_error(response))
                job_id = response.get('metadata', {}).get('id') or response.get('id')
                if not job_id:
                    raise RuntimeError('创建响应未包含作业 ID，请在 ModelArts 核对')
                settings = record['config'].get('modelarts') or {}
                region = settings.get('region') or manager._template().headers.get('region', '')
                job.update(id=str(job_id), status='SUBMITTED',
                           url=_console_url(response) or training_console_url(str(job_id), region, settings.get('workspace_name', '')))
            except ModelArtsRejected as exc:
                job.update(status='FAILED', message=str(exc))
            except Exception as exc:
                job.update(status='NEEDS_ATTENTION' if job['status'] == 'SUBMITTING' else 'FAILED', message=str(exc))
            manager._store(record)
            continue
        try:
            response = manager._client(record).get(job['id'])
            state = _state(response).strip().lower()
            if state in SUCCESS_STATES:
                job.update(status='SUCCEEDED', message='', completed_at=datetime.now().astimezone().isoformat())
            elif state in FAILURE_STATES:
                job.update(status='FAILED', message=_remote_error(response) or f'远程状态 {state}，请查看 ModelArts 作业日志')
            else:
                job.update(status=state.upper() or 'RUNNING', message='')
        except requests.RequestException:
            job['message'] = '状态查询暂不可用，将继续查询，不重复提交'
        except Exception as exc:
            # Known IDs remain resumable; credential errors must not lose running jobs.
            job['message'] = f'状态查询失败：{exc}'
        manager._store(record)
    finished = all(j['status'] in TERMINAL for j in record['jobs'])
    failed = [j for j in record['jobs'] if j['status'] in {'FAILED', 'NEEDS_ATTENTION'}]
    record['status'] = (('NEEDS_ATTENTION' if any(j['status'] == 'NEEDS_ATTENTION' for j in failed) else 'FAILED')
                        if finished and failed else 'SUCCEEDED' if finished else 'RUNNING')
    count = sum(j['status'] == 'SUCCEEDED' for j in record['jobs'])
    record['progress'] = round(100 * count / len(record['jobs']))
    record['stage'] = '全部作业完成' if record['status'] == 'SUCCEEDED' else f'独立作业已完成 {count}/{len(record["jobs"])}'
    record['message'] = '；'.join(f'{j["name"]}：{j.get("message", "")}' for j in failed)
    manager._store(record)


def run(manager, record):
    try:
        while not manager._stopping.is_set() and not record.get('delete_requested'):
            tick(manager, record)
            if record['status'] in {'SUCCEEDED', 'FAILED', 'NEEDS_ATTENTION'}:
                break
            if manager._stopping.wait(float(record['config'].get('poll_interval_seconds', 15))):
                break
    except Exception as exc:
        # Preserve known job IDs so recovery cannot duplicate already submitted work.
        record.update(status='WAITING_AUTH', stage='调度已暂停，请检查错误后恢复监控', message=str(exc))
        manager._store(record)
    finally:
        with manager._lock:
            manager._active.discard(record['id'])
