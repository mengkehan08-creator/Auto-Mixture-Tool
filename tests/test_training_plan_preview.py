import copy
import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from auto_mixture_tool.api.server import app
from auto_mixture_tool.modelarts.config_transport import read_config
from auto_mixture_tool.modelarts.training_plan import plan_training_jobs, workflow_training_plan
from auto_mixture_tool.modelarts.workflow import ModelArtsWorkflowManager
from auto_mixture_tool.modelarts import parallel_workflow
from nanochat_mid_compare.distributed_runtime import Topology, training_plan
from test_modelarts_workflow import config, FakeClient


@pytest.fixture
def model(tmp_path, monkeypatch):
    monkeypatch.setenv('AMT_OBS_MOUNT_ROOT', str(tmp_path))
    monkeypatch.setenv('AMT_OBS_MOUNT_PREFIX', 'obs://bucket/')
    base = tmp_path / 'model/base_checkpoints/d24'
    base.mkdir(parents=True)
    metadata = base / 'meta_000001.json'
    metadata.write_text(json.dumps({'max_seq_len': 2048, 'total_batch_size': 1048576,
                                    'model_config': {'sequence_len': 2048}}))
    return metadata


def job(nodes=3, **training):
    return {'nodes': nodes, 'training': {'base_model_tag': 'd24', 'token_budget': 401395843, **training}}


@pytest.mark.parametrize('nodes,batch,accumulation', [(1, 1048576, 64), (2, 1048576, 32),
                                                   (3, 1081344, 22), (4, 1048576, 16)])
def test_auto_uses_real_checkpoint_and_matches_cloud_plan(model, nodes, batch, accumulation):
    original = model.read_bytes()
    result = plan_training_jobs('obs://bucket/model/', [job(nodes)])
    assert result['ready'] and result['recommended_batch_size'] == batch
    actual = result['plans'][0]
    assert actual['grad_accum_steps'] == accumulation
    expected = training_plan(model.parent, Topology(nodes, 0, 8, 'localhost', 29500), 1,
                             401395843, total_batch_size=batch)
    assert all(actual[key] == value for key, value in expected.items())
    assert model.read_bytes() == original


def test_different_strategy_nodes_keep_one_common_batch(model):
    result = plan_training_jobs('obs://bucket/model/', [job(n) for n in (2, 3, 4)])
    assert result['recommended_batch_size'] == 1179648
    assert {p['total_batch_size'] for p in result['plans']} == {1179648}
    assert [p['grad_accum_steps'] for p in result['plans']] == [36, 24, 18]


def test_manual_fixed_is_never_rounded_and_auto_ignores_old_resolved_value(model):
    invalid = plan_training_jobs('obs://bucket/model/', [job(batch_size_mode='fixed', total_batch_size=1048576)])
    assert not invalid['ready'] and '49152' in invalid['errors'][0]
    assert invalid['plans'][0]['num_iterations'] is None
    assert invalid['recommended_batch_size'] == 1081344
    empty = plan_training_jobs('obs://bucket/model/', [job(batch_size_mode='fixed')])
    assert not empty['ready'] and empty['recommended_batch_size'] == 1081344
    fixed = plan_training_jobs('obs://bucket/model/', [job(total_batch_size=98304)])
    assert fixed['ready'] and fixed['plans'][0]['total_batch_size'] == 98304
    auto = plan_training_jobs('obs://bucket/model/', [job(batch_size_mode='auto', total_batch_size=1048576)])
    assert auto['ready'] and auto['plans'][0]['total_batch_size'] == 1081344


def test_short_budget_sequence_device_batch_and_legacy_steps(model):
    model.write_text(json.dumps({'max_seq_len': 1024, 'total_batch_size': 1048576,
                                'model_config': {'sequence_len': 4096}}))
    result = plan_training_jobs('obs://bucket/model/', [job(device_batch_size=2, token_budget=5406720)])
    plan = result['plans'][0]
    assert (plan['total_batch_size'], plan['num_iterations'], plan['actual_tokens']) == (1081344, 5, 5406720)
    legacy = job(num_iterations=5)
    legacy['training'].pop('token_budget')
    assert plan_training_jobs('obs://bucket/model/', [legacy])['plans'][0]['num_iterations'] == 5
    legacy['training']['num_iterations'] = 0
    plan = plan_training_jobs('obs://bucket/model/', [legacy])['plans'][0]
    assert plan['num_iterations'] is None and plan['actual_tokens'] is None
    assert plan['grad_accum_steps'] is not None


@pytest.mark.parametrize('field,value', [('token_budget', True), ('token_budget', 0),
    ('device_batch_size', 0), ('device_batch_size', 1.5), ('batch_size_mode', 'unknown'),
    ('base_model_tag', '../other'), ('base_model_tag', []), ('num_iterations', -1)])
def test_invalid_inputs_do_not_get_guessed(model, field, value):
    with pytest.raises(ValueError):
        plan_training_jobs('obs://bucket/model/', [job(**{field: value})])


def test_missing_corrupt_oversized_and_symlink_metadata_fail_closed(model, tmp_path):
    with pytest.raises(ValueError):
        plan_training_jobs('obs://other/model/', [job()])
    with pytest.raises(ValueError):
        plan_training_jobs('obs://bucket/model/?token=secret', [job()])
    model.unlink()
    with pytest.raises(ValueError, match='未找到'):
        plan_training_jobs('obs://bucket/model/', [job()])
    model.write_text('{invalid')
    with pytest.raises(ValueError, match='JSON'):
        plan_training_jobs('obs://bucket/model/', [job()])
    model.write_text(' ' * (1024 * 1024 + 1))
    with pytest.raises(ValueError, match='1 MiB'):
        plan_training_jobs('obs://bucket/model/', [job()])
    model.unlink()
    outside = tmp_path / 'outside.json'
    outside.write_text('{}')
    model.symlink_to(outside)
    with pytest.raises(ValueError, match='链接'):
        plan_training_jobs('obs://bucket/model/', [job()])


def test_preview_endpoint_reports_manual_error_without_creating_jobs(model):
    client = TestClient(app)
    body = {'model_obs_uri': 'obs://bucket/model/', 'nodes': [3], 'training': job()['training']}
    result = client.post('/api/v1/training-plan', json=body)
    assert result.status_code == 200 and result.json()['plans'][0]['num_iterations'] == 372
    body['training'].update(batch_size_mode='fixed', total_batch_size=1048576)
    result = client.post('/api/v1/training-plan', json=body)
    assert result.status_code == 200 and result.json()['ready'] is False
    body['nodes'] = [True]
    assert client.post('/api/v1/training-plan', json=body).status_code == 422


@pytest.fixture
def manager(tmp_path, model):
    root = tmp_path / 'workspace'
    root.mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'modelarts_training_job.py', root / 'modelarts_training_job.py')
    manager = ModelArtsWorkflowManager(root, FakeClient())
    manager._start = lambda _: None
    # Keep scheduling isolated while exercising real mounted-metadata planning.
    with patch('auto_mixture_tool.modelarts.input_validation.validate_workflow_resources', side_effect=workflow_training_plan):
        yield manager
    manager.close()


@pytest.mark.parametrize('parallel', [False, True])
def test_saved_plan_reaches_cloud_and_keeps_idempotency(manager, parallel):
    body = config()
    body.update(request_id='same-request', training_nodes=3)
    body['training'].update(batch_size_mode='auto', token_budget=5406720)
    if parallel:
        body['execution_mode'] = 'parallel'
    original = copy.deepcopy(body)
    created = manager.create(body)
    assert manager.create(body)['id'] == created['id']
    assert body == original
    record = manager.records[created['id']]
    assert 'total_batch_size' not in record['config']['training']
    if parallel:
        task = next(j for j in record['jobs'] if j['module'] == 'training')
        payload = parallel_workflow.payload(manager, record, task)
    else:
        payload = manager._payload(record, 'training')
    runtime = read_config(payload['algorithm']['environments'])
    assert runtime['training']['total_batch_size'] == 1081344
    assert record['training_plan']['plans'][0]['num_iterations'] == 5
    assert manager.client.submissions == []


def test_invalid_manual_stops_before_any_cloud_job(manager):
    body = config()
    body['training'].update(batch_size_mode='fixed', total_batch_size=1048576)
    with pytest.raises(ValueError, match='49152'):
        manager.create(body)
    assert manager.client.submissions == [] and not manager.records


def test_common_batch_reaches_each_parallel_job_and_model_record(manager):
    body = config()
    body['execution_mode'] = 'parallel'
    body['training'].update(batch_size_mode='auto', token_budget=401395843)
    template = body['strategies'][0]
    body['strategies'] = [dict(template, id=f'n{n}', training_nodes=n) for n in (2, 3, 4)]
    created = manager.create(body)
    record = manager.records[created['id']]
    for task in record['jobs']:
        if task['module'] != 'training':
            continue
        payload = parallel_workflow.payload(manager, record, task)
        runtime = read_config(payload['algorithm']['environments'])
        assert runtime['training']['total_batch_size'] == 1179648
        strategy = next(s for s in record['config']['strategies'] if s['id'] == task['strategy_id'])
        catalog = parallel_workflow.model_record(record, strategy, 'obs://bucket/output/', task)
        assert catalog['training_config']['total_batch_size'] == 1179648
    assert 'total_batch_size' not in record['config']['training']


def test_training_retry_only_plans_its_active_branch(model):
    body = config()
    body['execution_mode'] = 'parallel'
    body['strategies'] = [dict(id=str(n), training_nodes=n) for n in (2, 3, 4)]
    body['job_reuse'] = {'key': 'training-3'}
    result = workflow_training_plan(body)
    assert len(result['plans']) == 1 and result['recommended_batch_size'] == 1081344
    body['job_reuse']['key'] = 'evaluation'
    assert workflow_training_plan(body) is None
