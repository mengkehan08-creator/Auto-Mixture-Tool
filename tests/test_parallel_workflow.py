import copy
import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from auto_mixture_tool.modelarts.workflow import ModelArtsWorkflowManager
from auto_mixture_tool.modelarts import parallel_workflow as graph
from auto_mixture_tool.modelarts.config_transport import read_config
from test_modelarts_workflow import config, FakeClient


@pytest.fixture
def manager(tmp_path):
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'modelarts_training_job.py', tmp_path / 'modelarts_training_job.py')
    manager = ModelArtsWorkflowManager(tmp_path, FakeClient())
    manager._start = lambda _: None
    return manager


def parallel_config():
    value = config()
    value['execution_mode'] = 'parallel'
    value['strategies'].append({'id': 'random', 'type': 'random', 'name': 'Random'})
    for index, s in enumerate(value['strategies']):
        s.update(mixing_nodes=index + 1, training_nodes=index + 2, model_name=f'model-{index}')
    value['training']['token_budget'] = 1048576
    return value


def create(manager, value=None):
    result = manager.create(value or parallel_config())
    return manager.records[result['id']]


def finish(manager, record):
    for _ in range(12):
        graph.tick(manager, record)
        if record['status'] in {'SUCCEEDED', 'FAILED', 'NEEDS_ATTENTION'}:
            return
    raise AssertionError(record)


def test_independent_nodes_dependency_and_barrier(manager):
    record = create(manager)
    assert len(record['jobs']) == 7
    assert [j['nodes'] for j in record['jobs']] == [1, 2, 2, 3, 3, 4, 1]
    graph.tick(manager, record)
    assert len(manager.client.submissions) == 3  # All mixing submitted before waiting.
    first = record['jobs'][0]['id']
    original_get = manager.client.get
    manager.client.get = lambda id: original_get(id) if id == first else {'status': 'RUNNING'}
    graph.tick(manager, record)
    assert len(manager.client.submissions) == 4  # Own training starts while other mixing runs.
    assert record['jobs'][-1]['id'] is None
    manager.client.get = original_get
    finish(manager, record)
    assert record['status'] == 'SUCCEEDED'
    assert len(manager.client.submissions) == 7
    for s in record['config']['strategies']:
        job = next(j for j in record['jobs'] if j['key'] == 'training-' + s['id'])
        body = graph.payload(manager, record, job)
        inputs = {i['name']: i['remote']['obs']['obs_url'] for i in body['algorithm']['inputs']}
        assert inputs['comparison_data_dir'] == record['branches'][s['id']]['outputs']['sampled']
        runtime = read_config(body['algorithm']['environments'])
        assert [i['id'] for i in runtime['strategies']] == [s['id']]
    outputs = [b['outputs']['models'] for b in record['branches'].values()]
    assert len(set(outputs)) == 3


def many_strategies():
    value = parallel_config()
    templates = {s['type']: s for s in value['strategies']}
    value['strategies'] = []
    for index, kind in enumerate(['quadmix', 'quadmix', 'quadmix', 'manual', 'manual', 'random', 'random']):
        s = copy.deepcopy(templates[kind])
        s.update(id=f'{kind}_{index}', name='', model_name='', seed=42 + index,
                 mixing_nodes=2 if kind == 'quadmix' else 1, training_nodes=index + 1,
                 training={'token_budget': (index + 1) * 1048576})
        if kind == 'quadmix':
            s.update(proxy_experiments=16 + index, proxy_steps=15 + index)
        if kind == 'manual':
            s['ratios'] = {'数学': index + 1, '物理': 1}
        if kind == 'random':
            s.update(script_obs_uri=f'obs://bucket/strategies/random-{index}.py', script_config={'mode': index})
        value['strategies'].append(s)
    return value


def test_seven_strategies_create_isolated_pairs_and_evaluate_all_models(manager):
    record = create(manager, many_strategies())
    assert len(record['jobs']) == 15
    assert len(record['branches']) == 7
    assert len({j['name'] for j in record['jobs']}) == 15
    assert len(set(record['strategy_names'].values())) == 7
    assert len({b['outputs']['sampled'] for b in record['branches'].values()}) == 7
    assert len({b['outputs']['models'] for b in record['branches'].values()}) == 7
    for s in record['config']['strategies']:
        mix = next(j for j in record['jobs'] if j['key'] == 'mixing-' + s['id'])
        train = next(j for j in record['jobs'] if j['key'] == 'training-' + s['id'])
        assert mix['priority'] == 2
        assert train['depends_on'] == [mix['key']]
        assert train['strategy_name'] == mix['strategy_name']
        for job in (mix, train):
            payload = graph.payload(manager, record, job)
            runtime = read_config(payload['algorithm']['environments'])
            assert len(runtime['strategies']) == 1
            selected = runtime['strategies'][0]
            assert selected['id'] == s['id'] and selected['seed'] == s['seed']
            assert runtime['training']['token_budget'] == s['training']['token_budget']
            if s['type'] == 'quadmix':
                assert selected['search_count'] == 5000
                assert selected['proxy_experiments'] == s['proxy_experiments']
            if s['type'] == 'random':
                assert selected['script_config'] == s['script_config']
            assert payload['spec']['schedule_policy']['priority'] == job['priority']
        assert train['input_obs_uri'] == mix['outputs']['sampled']
    graph.tick(manager, record)
    assert len(manager.client.submissions) == 7
    finish(manager, record)
    assert len(manager.client.submissions) == 15
    assert record['status'] == 'SUCCEEDED'
    assert len(graph.models(manager)) == 7
    runtime = read_config(manager.client.submissions[-1]['algorithm']['environments'])
    assert len(runtime['evaluation_sources']) == 7
    assert len({s['strategy_id'] for s in runtime['evaluation_sources']}) == 7


def test_parameter_names_preserve_custom_names_and_idempotency(manager):
    value = many_strategies()
    value['request_id'] = 'multi-strategy-idempotent'
    value['strategies'][1].update(name='自定义策略', mixing_job_name='custom-mixing', training_job_name='custom-training', mixing_priority=3)
    result = create(manager, value)
    first, train = result['jobs'][:2]
    assert first['name'].startswith('ex-16-15-')
    assert train['name'].startswith('train-ex-16-15-t1048576-')
    assert result['jobs'][2]['name'] == 'custom-mixing'
    assert result['jobs'][3]['name'] == 'custom-training'
    assert result['jobs'][2]['strategy_name'] == '自定义策略'
    assert result['jobs'][2]['priority'] == 3
    assert create(manager, value)['id'] == result['id']


def test_hundreds_of_strategies_plan_isolated_jobs_and_bound_submission(manager):
    value = parallel_config()
    templates = value['strategies']
    value['strategies'] = [dict(copy.deepcopy(templates[i % len(templates)]),
                                id=f'strategy_{i}', name='') for i in range(200)]
    record = create(manager, value)
    assert len(record['jobs']) == 401
    assert len({j['name'] for j in record['jobs']}) == 401
    assert len({b['outputs']['sampled'] for b in record['branches'].values()}) == 200
    for strategy in value['strategies']:
        train = next(j for j in record['jobs'] if j['key'] == 'training-' + strategy['id'])
        assert train['depends_on'] == ['mixing-' + strategy['id']]
    evaluation = graph.payload(manager, record, record['jobs'][-1])
    runtime = read_config(evaluation['algorithm']['environments'])
    assert len(runtime['evaluation_sources']) == 200
    assert all('mixing_command' not in s and 'training_command' not in s for s in runtime['strategies'])
    manager.client.get = lambda _: {'status': 'RUNNING'}
    graph.tick(manager, record)
    assert len(manager.client.submissions) == 8
    graph.tick(manager, record)
    assert len(manager.client.submissions) == 8


def test_active_window_refills_after_success_and_survives_uncertain_submit(manager):
    value = parallel_config()
    value['max_active_jobs'] = 1
    record = create(manager, value)
    graph.tick(manager, record)
    assert len(manager.client.submissions) == 1
    graph.tick(manager, record)
    assert len(manager.client.submissions) == 2
    assert record['jobs'][1]['id']  # Own training gets the released slot.
    record['jobs'][1].update(id=None, status='SUBMITTING')
    graph.tick(manager, record)
    assert record['jobs'][1]['status'] == 'NEEDS_ATTENTION'
    assert len(manager.client.submissions) == 2


@pytest.mark.parametrize('limit', [0, -1, True, '8', 1.5, 1001])
def test_invalid_active_window_rejected(manager, limit):
    value = parallel_config()
    value['max_active_jobs'] = limit
    with pytest.raises(ValueError, match='max_active_jobs'):
        create(manager, value)


def test_per_strategy_framework_mounts_and_priority_defaults(manager):
    value = parallel_config()
    value['strategies'][0].update(training_framework_source='obs', training_framework_obs_uri='obs://bucket/framework-a/')
    value['strategies'][1].update(training_framework_source='obs', training_framework_obs_uri='obs://bucket/framework-b/')
    record = create(manager, value)
    assert all(j['priority'] == 2 for j in record['jobs'])
    for index, strategy in enumerate(record['config']['strategies']):
        expected = ['obs://bucket/framework-a/', 'obs://bucket/framework-b/', 'obs://bucket/nanochat/'][index]
        for stage in ('mixing', 'training'):
            job = next(j for j in record['jobs'] if j['key'] == stage + '-' + strategy['id'])
            body = graph.payload(manager, record, job)
            mount = next(i for i in body['algorithm']['inputs'] if i['name'] == 'nanochat_npu_dir')
            assert mount['remote']['obs']['obs_url'] == expected
            assert read_config(body['algorithm']['environments'])['resources']['nanochat_repo_obs_uri'].rstrip('/') == expected.rstrip('/')
    evaluation = graph.payload(manager, record, record['jobs'][-1])
    assert next(i for i in evaluation['algorithm']['inputs'] if i['name'] == 'nanochat_npu_dir')['remote']['obs']['obs_url'] == 'obs://bucket/nanochat/'
    assert record['config']['resources']['nanochat_repo_obs_uri'].rstrip('/') == 'obs://bucket/nanochat'
    finish(manager, record)
    retry = graph.retry(manager, record['id'], 'training-quadmix', {})
    retried = manager.records[retry['id']]
    assert retried['config']['strategies'][0]['training_framework_obs_uri'].rstrip('/') == 'obs://bucket/framework-a'


@pytest.mark.parametrize('source,uri', [('unknown', ''), ('obs', ''), ('obs', '/local/framework')])
def test_invalid_framework_mount_rejected(manager, source, uri):
    value = parallel_config()
    value['strategies'][0].update(training_framework_source=source, training_framework_obs_uri=uri)
    with pytest.raises(ValueError):
        create(manager, value)
    assert manager.client.submissions == []


def test_identical_parameters_still_have_unique_auto_names(manager):
    value = many_strategies()
    value['strategies'] = [copy.deepcopy(value['strategies'][0]) for _ in range(3)]
    for index, strategy in enumerate(value['strategies']):
        strategy['id'] = f'quadmix_{index}'
    record = create(manager, value)
    assert len({job['name'].lower() for job in record['jobs']}) == 7
    assert all(len(job['name']) <= 64 for job in record['jobs'])
    value['strategies'][1]['id'] = value['strategies'][0]['id']
    with pytest.raises(ValueError, match='唯一 id'):
        create(manager, value)


def test_repeated_strategy_training_retry_reuses_only_its_inputs(manager):
    source = create(manager, many_strategies())
    finish(manager, source)
    result = graph.retry(manager, source['id'], 'training-quadmix_1', {'training': {'token_budget': 999999}})
    retried = manager.records[result['id']]
    assert retried['strategy_names'] == source['strategy_names']
    assert retried['branches']['quadmix_1']['outputs']['sampled'] == source['branches']['quadmix_1']['outputs']['sampled']
    assert retried['branches']['quadmix_0']['outputs']['models'] == source['branches']['quadmix_0']['outputs']['models']
    before = len(manager.client.submissions)
    finish(manager, retried)
    assert len(manager.client.submissions) - before == 2


def test_failure_only_blocks_own_descendants(manager):
    record = create(manager)
    graph.tick(manager, record)
    bad = record['jobs'][0]['id']
    manager.client.get = lambda id: {'status': 'Failed' if id == bad else 'Completed'}
    finish(manager, record)
    assert record['jobs'][1]['status'] == 'BLOCKED'
    assert record['jobs'][3]['status'] == record['jobs'][5]['status'] == 'SUCCEEDED'
    assert record['jobs'][-1]['status'] == 'BLOCKED'
    assert record['jobs'][-1]['id'] is None
    assert len(manager.client.submissions) == 5
    assert len(graph.models(manager)) == 2


def test_names_duplicate_history_and_idempotency(manager):
    value = parallel_config()
    value['strategies'][0]['mixing_job_name'] = 'same-name'
    value['strategies'][1]['training_job_name'] = 'SAME-name'
    with pytest.raises(ValueError, match='名称重复'):
        create(manager, value)
    assert not manager.records
    value['strategies'][1]['training_job_name'] = ''
    value['request_id'] = 'idempotent-001'
    record = create(manager, value)
    assert create(manager, value)['id'] == record['id']
    value['request_id'] = 'idempotent-002'
    with pytest.raises(ValueError, match='名称重复'):
        create(manager, value)


def test_history_models_and_separate_tokenizer_mounts(manager, monkeypatch):
    from test_model_comparison import identity
    from auto_mixture_tool.modelarts import model_comparison
    monkeypatch.setattr(model_comparison, 'read_metadata', lambda uri: {
        'version': 1, 'identity': identity(),
        'models': [{'id': key, 'comparison_identity': identity()} for key in ('quadmix', 'manual', 'random')],
    })
    first = create(manager)
    finish(manager, first)
    catalog = graph.models(manager)
    assert len(catalog) == 3 and catalog[0]['training_config']['token_budget'] == 1048576
    value = parallel_config()
    value['evaluation']['model_ids'] = [catalog[0]['id'], catalog[0]['id']]
    second = create(manager, value)
    body = graph.payload(manager, second, second['jobs'][-1])
    sources = read_config(body['algorithm']['environments'])['evaluation_sources']
    assert len(sources) == 4
    assert sources[-1]['obs_uri'] == catalog[0]['obs_uri']
    inputs = body['algorithm']['inputs']
    assert not any(i['name'] == 'trained_models' for i in inputs)
    assert len([i for i in inputs if i['name'].startswith('evaluation_model_')]) == 4
    assert len([i for i in inputs if i['name'].startswith('evaluation_tokenizer_')]) == 4
    value['evaluation']['model_ids'] = ['not-successful:model']
    with pytest.raises(ValueError, match='历史模型不可用'):
        create(manager, value)


def test_retry_training_reuses_exact_prior_data_and_other_models(manager):
    source = create(manager)
    finish(manager, source)
    original = copy.deepcopy(source)
    result = graph.retry(manager, source['id'], 'training-quadmix', {'nodes': 5, 'training': {'token_budget': 2097152}})
    record = manager.records[result['id']]
    assert record['branches']['quadmix']['outputs']['sampled'] == source['branches']['quadmix']['outputs']['sampled']
    assert record['branches']['quadmix']['outputs']['models'] != source['branches']['quadmix']['outputs']['models']
    assert record['branches']['random']['outputs']['models'] == source['branches']['random']['outputs']['models']
    assert next(j for j in record['jobs'] if j['key'] == 'training-quadmix')['nodes'] == 5
    assert sum(j.get('reused', False) for j in record['jobs']) == 5
    before = len(manager.client.submissions)
    finish(manager, record)
    assert len(manager.client.submissions) - before == 2
    assert source == original
    assert record['status'] == 'SUCCEEDED'


def test_ambiguous_post_is_not_repeated_after_restart(manager):
    record = create(manager)
    def uncertain(_):
        raise TimeoutError('unknown result')
    manager.client.submit = uncertain
    finish(manager, record)
    assert record['status'] == 'NEEDS_ATTENTION'
    assert sum(j['status'] == 'NEEDS_ATTENTION' for j in record['jobs']) == 3
    assert record['jobs'][-1]['status'] == 'BLOCKED'


def test_random_only_no_quad_required_and_custom_command(manager):
    value = parallel_config()
    value['strategies'] = [value['strategies'][-1]]
    value['strategies'][0]['mixing_command'] = 'custom-sampling-command'
    record = create(manager, value)
    assert len(record['jobs']) == 3
    body = graph.payload(manager, record, record['jobs'][0])
    assert body['algorithm']['command'] == 'custom-sampling-command'
    assert read_config(body['algorithm']['environments'])['strategies'][0]['type'] == 'random'


def test_each_job_payload_uses_its_own_command_and_retry_keeps_others(manager):
    value = parallel_config()
    value['commands'] = {stage: manager._command(stage) for stage in ('mixing', 'training', 'evaluation')}
    value['commands']['evaluation'] = 'evaluate-all-models'
    expected = {'evaluation': 'evaluate-all-models'}
    for strategy in value['strategies']:
        for stage in ('mixing', 'training'):
            command = f'run-{stage}-{strategy["id"]}'
            strategy[stage + '_command'] = command
            expected[f'{stage}-{strategy["id"]}'] = command
    record = create(manager, value)
    for job in record['jobs']:
        assert graph.payload(manager, record, job)['algorithm']['command'] == expected[job['key']]
    finish(manager, record)
    retried = graph.retry(manager, record['id'], 'training-quadmix', {'command': 'retry-quadmix-training'})
    retry_record = manager.records[retried['id']]
    for job in retry_record['jobs']:
        command = 'retry-quadmix-training' if job['key'] == 'training-quadmix' else expected[job['key']]
        assert graph.payload(manager, retry_record, job)['algorithm']['command'] == command


def test_removed_resources_validate_actual_individual_commands(manager):
    value = parallel_config()
    value['offline_resources'] = []
    value['commands'] = {stage: manager._command(stage) for stage in ('mixing', 'training', 'evaluation')}
    for strategy in value['strategies']:
        strategy.update(mixing_command='custom-mixing', training_command='custom-training')
    assert create(manager, value)['pipeline_version'] == 4
    value['strategies'][1]['training_command'] = manager._command('training')
    with pytest.raises(ValueError, match='默认运行资源'):
        create(manager, value)


def test_api_accepts_parallel_mode(manager):
    from fastapi.testclient import TestClient
    from auto_mixture_tool.api.server import app
    with patch('auto_mixture_tool.api.server._workflow_manager', return_value=manager):
        client = TestClient(app)
        response = client.post('/api/v1/workflows', json=parallel_config())
        assert response.status_code == 202
        assert response.json()['pipeline_version'] == 4
        assert len(response.json()['jobs']) == 7


def test_per_job_parameters_validated_before_any_submission(manager):
    value = parallel_config()
    value['strategies'][1]['training'] = {'devices_per_node': 0}
    with pytest.raises(ValueError):
        create(manager, value)
    assert not manager.records and not manager.client.submissions


def test_eval_retry_only_submits_one_job(manager):
    source = create(manager)
    finish(manager, source)
    result = graph.retry(manager, source['id'], 'evaluation', {'nodes': 4})
    record = manager.records[result['id']]
    before = len(manager.client.submissions)
    finish(manager, record)
    assert len(manager.client.submissions) == before + 1
    assert record['jobs'][-1]['nodes'] == 4
    assert all(record['branches'][sid]['outputs']['models'] == b['outputs']['models'] for sid, b in source['branches'].items())


def test_recovery_does_not_repost_known_ids(manager):
    record = create(manager)
    graph.tick(manager, record)
    recovered = ModelArtsWorkflowManager(manager.workspace, manager.client)
    recovered._load_disk()
    finish(recovered, recovered.records[record['id']])
    assert len(manager.client.submissions) == 7


def test_deleted_record_keeps_model_catalog(manager):
    source = create(manager)
    finish(manager, source)
    source.update(delete_requested=True, status='DELETED')
    for job in source['jobs']:
        job['status'] = 'COMPLETED'
    manager._store(source)
    assert len(graph.models(manager)) == 3


def test_selected_manifest_model_and_tokenizer_resolved_separately(tmp_path, monkeypatch):
    from auto_mixture_tool.modelarts.evaluation_job import evaluation_models, publish_models
    monkeypatch.setenv('AMT_RUN_ID', 'same-run')
    sources = []
    for index in range(2):
        root = tmp_path / f'models_{index}'
        folder = root / 'd24_stem_random_same-run'
        folder.mkdir(parents=True)
        (folder / 'model_000015.pt').write_bytes(bytes([index + 1]))
        (folder / 'meta_000015.json').write_text(json.dumps({'model_config': {'n_layer': 24}}))
        (root / 'dataset_stats.json').write_text('{}')
        value = parallel_config()
        value['strategies'] = [value['strategies'][-1]]
        value['strategies'][0]['model_name'] = f'named-{index}'
        publish_models(value, root, root)
        sources.append({'id': f'source-{index}:random', 'strategy_id': 'random', 'mount': root.name,
                        'tokenizer_mount': f'tokenizer-{index}', 'name': f'named-{index}',
                        'workflow_id': f'source-{index}', 'obs_uri': f'obs://bucket/models-{index}/'})
    result = evaluation_models({'evaluation_sources': sources}, tmp_path)
    assert [m['id'] for m in result['models']] == ['model_0', 'model_1']
    assert len({m['_root'] for m in result['models']}) == 2
    assert len({m['_tokenizer'] for m in result['models']}) == 2
    assert result['models'][0]['model_config'] == {'n_layer': 24}
    sources[0]['strategy_id'] = 'missing'
    with pytest.raises(ValueError, match='不匹配'):
        evaluation_models({'evaluation_sources': sources}, tmp_path)


def test_baseline_calls_existing_sampling_and_validates_first(monkeypatch):
    import sys
    from types import SimpleNamespace
    from auto_mixture_tool.modelarts import stage_runner
    value = parallel_config()
    value['strategies'] = [value['strategies'][1]]
    value['strategies'][0]['local_script_path'] = '/mounted/my_strategy.py'
    monkeypatch.setenv('VC_TASK_INDEX', '0')
    mock_manager = SimpleNamespace(validate=lambda *a, **k: {'valid': True})
    monkeypatch.setitem(sys.modules, 'auto_mixture_tool.pipeline', SimpleNamespace(PipelineManager=lambda *_: mock_manager))
    with patch.object(stage_runner.subprocess, 'run') as run:
        stage_runner.run_mixing(value)
        env = run.call_args.kwargs['env']
        assert env['COMPARISON_METHODS'] == 'manual' and env['PREPARE_ONLY'] == '1'
        assert env['MANUAL_STRATEGY_PATH'] == '/mounted/my_strategy.py'
        assert json.loads(env['MANUAL_PLANS_JSON'])[0]['id'] == 'manual_a'
    mock_manager.validate = lambda *a, **k: {'valid': False, 'errors': ['bad schema']}
    with patch.object(stage_runner.subprocess, 'run') as run, pytest.raises(ValueError, match='数据格式不符合算法要求'):
        stage_runner.run_mixing(value)
    run.assert_not_called()


def test_job_errors_do_not_persist_authorization(manager):
    record = create(manager)
    manager._authorizations[record['id']] = 'private-token-value'
    manager.client.submit = lambda _: (_ for _ in ()).throw(TimeoutError('private-token-value'))
    finish(manager, record)
    stored = (manager.directory / f'{record["id"]}.json').read_text(encoding='utf-8')
    assert 'private-token-value' not in stored


def test_ambiguous_jobs_cannot_be_silently_deleted(manager):
    record = create(manager)
    record.update(status='NEEDS_ATTENTION', delete_requested=True)
    record['jobs'][0]['status'] = 'NEEDS_ATTENTION'
    manager._delete_run(record['id'])
    assert record['status'] == 'DELETE_FAILED'
    assert '核对' in record['message']


def test_uncreated_ambiguous_jobs_require_explicit_absence_confirmation(manager):
    record = create(manager)
    record['status'] = 'NEEDS_ATTENTION'
    record['jobs'][0]['status'] = 'NEEDS_ATTENTION'
    with patch.object(manager, '_start_delete'):
        manager.delete(record['id'], confirmed_not_created=True)
    assert record['jobs'][0]['status'] == 'NOT_CREATED'
    manager._delete_run(record['id'])
    assert record['status'] == 'DELETED'
