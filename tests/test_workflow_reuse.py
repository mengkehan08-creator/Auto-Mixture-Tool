import copy
from pathlib import Path
from unittest.mock import patch

import pytest

from auto_mixture_tool.modelarts.workflow import ModelArtsWorkflowManager
from test_modelarts_workflow import config, FakeClient


def setup_source(tmp_path):
    client = FakeClient()
    manager = ModelArtsWorkflowManager(Path(__file__).resolve().parents[1], client)
    manager.directory = tmp_path
    with patch.object(manager, '_start'):
        record = manager.create(config())
    source = manager.records[record['id']]
    source['status'] = 'FAILED'
    for job in source['jobs'][:2]:
        job.update(status='SUCCEEDED', id='original-job')
    source['jobs'][2]['status'] = 'FAILED'
    manager._store(source)
    return manager, client, source


@pytest.mark.parametrize('stage,count', [('training', 2), ('evaluation', 1)])
def test_restart_submits_only_remaining_jobs(tmp_path, stage, count):
    manager, client, source = setup_source(tmp_path)
    before = copy.deepcopy(source)
    body = config()
    body['reuse'] = {'workflow_id': source['id'], 'stage': stage}
    body['strategies'][1]['id'] = 'changed-id'
    body['training']['token_budget'] = 5000000
    body['resources']['code_obs_uri'] = 'obs://bucket/fixed-code/'
    with patch.object(manager, '_start'):
        created = manager.create(body)
        assert manager.create(body | {'request_id': 'retry-key'})['id'] == manager.create(body | {'request_id': 'retry-key'})['id']
    record = manager.records[created['id']]
    assert record['config']['strategies'] == source['config']['strategies']
    assert record['outputs']['sampled'] == source['outputs']['sampled']
    assert record['outputs']['reports'] != source['outputs']['reports']
    assert all(job['id'] is None for job in record['jobs'] if job.get('reused'))
    with patch('auto_mixture_tool.modelarts.workflow.time.sleep'):
        manager._run(record['id'])
    assert record['status'] == 'SUCCEEDED'
    assert len(client.submissions) == count
    inputs = {i['name']: i['remote']['obs']['obs_url'] for i in client.submissions[0]['algorithm']['inputs']}
    if stage == 'training':
        assert inputs['comparison_data_dir'] == source['outputs']['sampled']
        assert record['outputs']['models'] != source['outputs']['models']
        assert record['config']['training']['token_budget'] == 5000000
    else:
        assert inputs['trained_models'] == source['outputs']['models']
        assert record['config']['training'] == source['config']['training']
    assert manager.records[source['id']] == before
    assert 'reuse' not in manager.copy_configuration(created['id'])


@pytest.mark.parametrize('status', ['RUNNING', 'NEEDS_ATTENTION', 'WAITING_AUTH'])
def test_uncertain_or_active_source_rejected(tmp_path, status):
    manager, client, source = setup_source(tmp_path)
    source['status'] = status
    manager._store(source)
    with pytest.raises(ValueError, match='已结束'):
        manager.create(config() | {'reuse': {'workflow_id': source['id'], 'stage': 'evaluation'}})
    assert not client.submissions


def test_failed_training_cannot_be_reused_for_evaluation(tmp_path):
    manager, _, source = setup_source(tmp_path)
    source['jobs'][1]['status'] = 'FAILED'
    manager._store(source)
    with pytest.raises(ValueError, match='前序作业'):
        manager.create(config() | {'reuse': {'workflow_id': source['id'], 'stage': 'evaluation'}})


def test_evaluation_restart_requires_tasks(tmp_path):
    manager, _, source = setup_source(tmp_path)
    body = config() | {'reuse': {'workflow_id': source['id'], 'stage': 'evaluation'}}
    body['evaluation']['datasets'] = []
    with pytest.raises(ValueError, match='必须选择'):
        manager.create(body)


def test_deleting_retry_does_not_query_or_stop_original_jobs(tmp_path):
    manager, client, source = setup_source(tmp_path)
    with patch.object(manager, '_start'):
        created = manager.create(config() | {'reuse': {'workflow_id': source['id'], 'stage': 'evaluation'}})
    with patch.object(manager, '_start_delete'):
        manager.delete(created['id'])
    manager._delete_run(created['id'])
    assert not client.events
    assert manager.records[source['id']]['status'] == 'FAILED'
    assert manager.records[created['id']]['status'] == 'DELETED'


def test_api_preserves_reuse_request(tmp_path):
    from fastapi.testclient import TestClient
    from auto_mixture_tool.api import server
    manager, client, source = setup_source(tmp_path)
    body = config() | {'reuse': {'workflow_id': source['id'], 'stage': 'evaluation'}}
    with patch.object(server, '_workflow_manager', return_value=manager), patch.object(manager, '_start'):
        response = TestClient(server.app).post('/api/v1/workflows', json=body)
    assert response.status_code == 202
    assert response.json()['reused_from'] == source['id']
    assert response.json()['outputs']['models'] == source['outputs']['models']
    assert not client.submissions
