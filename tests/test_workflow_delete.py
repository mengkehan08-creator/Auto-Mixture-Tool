from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from auto_mixture_tool.modelarts.workflow import ModelArtsClient, ModelArtsWorkflowManager
from test_modelarts_workflow import config
from test_workflow_execution import manager


def record(manager):
    with patch.object(manager, '_start'):
        value = manager.create(config())
    return manager.records[value['id']]


def remove_sync(manager, row):
    with patch.object(manager, '_start_delete'):
        manager.delete(row['id'])
    manager._delete_run(row['id'])


def test_queued_delete_never_submits_and_survives_restart(manager):
    row = record(manager)
    remove_sync(manager, row)
    assert row['status'] == 'DELETED'
    assert manager.list() == []
    manager._run(row['id'])
    assert manager.client.submissions == []
    # Deleted records remain as internal tombstones, not visible experiments.
    assert row['status'] == 'DELETED'
    restarted = ModelArtsWorkflowManager(manager.workspace, manager.client)
    with patch.object(restarted, '_start'), patch.object(restarted, '_start_delete') as start:
        restarted.resume()
        start.assert_not_called()
    assert restarted.list() == []


def test_running_job_stopped_and_confirmed_before_hiding(manager):
    row = record(manager)
    row['jobs'][0].update(id='remote-job', status='RUNNING')
    manager.client = Mock()
    manager.client.get.side_effect = [{'status': 'Running'}, {'status': 'Terminated'}]
    remove_sync(manager, row)
    manager.client.stop.assert_called_once_with('remote-job')
    assert manager.client.get.call_count == 2
    assert row['status'] == 'DELETED'
    assert manager.list() == []


def test_completed_remote_job_does_not_need_stop(manager):
    row = record(manager)
    row['jobs'][0].update(id='finished-job', status='RUNNING')
    manager.client = Mock()
    manager.client.get.return_value = {'status': 'Completed'}
    remove_sync(manager, row)
    manager.client.stop.assert_not_called()
    assert row['status'] == 'DELETED'


@pytest.mark.parametrize('mode', ['rejected', 'timeout', 'unknown-id'])
def test_failed_stop_preserves_record_and_blocks_training(manager, mode):
    row = record(manager)
    row['jobs'][0].update(id=None if mode == 'unknown-id' else 'remote', status='SUBMITTING')
    manager.client = Mock()
    manager.client.get.return_value = {'status': 'Running'}
    if mode == 'rejected':
        manager.client.stop.side_effect = ValueError('没有终止权限')
    with patch.object(manager._stopping, 'wait', return_value=False):
        remove_sync(manager, row)
    assert row['status'] == 'DELETE_FAILED'
    assert manager.list()[0]['message']
    assert not manager._submit_and_wait(row, 1, 'training', 60, 95)
    manager.client.submit.assert_not_called()


def test_delete_waits_for_inflight_creation_id(manager):
    row = record(manager)
    manager._active.add(row['id'])
    row['jobs'][0]['status'] = 'SUBMITTING'
    manager.client = Mock()
    manager.client.get.side_effect = [{'status': 'Running'}, {'status': 'Terminated'}]
    with patch.object(manager, '_start_delete'):
        manager.delete(row['id'])
    def complete_submission(_):
        row['jobs'][0].update(id='inflight-job', status='SUBMITTED')
        manager._active.discard(row['id'])
        return False
    with patch.object(manager._stopping, 'wait', side_effect=complete_submission):
        manager._delete_run(row['id'])
    manager.client.stop.assert_called_once_with('inflight-job')
    manager.client.submit.assert_not_called()


def test_stop_request_uses_terminate_action_and_private_tls_option():
    provider = Mock(config={'modelarts_verify_ssl': False})
    provider.authorization.return_value = 'test-token'
    with patch('auto_mixture_tool.modelarts.workflow.get_provider', return_value=provider):
        client = ModelArtsClient(SimpleNamespace(url='https://example.test/jobs', headers={}))
    with patch('requests.post', return_value=SimpleNamespace(status_code=204)) as post:
        assert client.stop('job-id') == {}
    assert post.call_args.args[0] == 'https://example.test/jobs/job-id/actions'
    assert post.call_args.kwargs['json'] == {'action_type': 'terminate'}
    assert post.call_args.kwargs['verify'] is False
    assert post.call_args.kwargs['allow_redirects'] is False


def test_delete_route_accepts_and_unknown_id_does_not_delete(manager):
    from fastapi.testclient import TestClient
    from auto_mixture_tool.api.server import app
    row = record(manager)
    with patch('auto_mixture_tool.api.server._workflow_manager', return_value=manager), patch.object(manager, '_start_delete'):
        client = TestClient(app)
        assert client.delete('/api/v1/workflows/' + row['id']).status_code == 202
        assert client.delete('/api/v1/workflows/ffffffffffff').status_code == 404
    assert row['delete_requested'] is True


def test_verified_absent_remote_job_is_deleted_without_cloud_calls(manager):
    row = record(manager)
    row.update(status='NEEDS_ATTENTION')
    row['jobs'][0].update(id=None, status='SUBMITTING')
    manager.client = Mock()
    with patch.object(manager, '_start_delete'):
        manager.delete(row['id'], confirmed_not_created=True)
    manager._delete_run(row['id'])
    assert row['status'] == 'DELETED'
    assert row['absence_confirmed_at']
    manager.client.get.assert_not_called()
    manager.client.stop.assert_not_called()
    manager.client.submit.assert_not_called()


@pytest.mark.parametrize('case', ['active', 'known-id'])
def test_absence_confirmation_cannot_skip_inflight_or_known_job(manager, case):
    row = record(manager)
    row.update(status='NEEDS_ATTENTION')
    row['jobs'][0]['status'] = 'SUBMITTING'
    if case == 'active':
        manager._active.add(row['id'])
    else:
        row['jobs'][0]['id'] = 'remote-job'
    with pytest.raises(ValueError, match='已创建作业仍须终止'):
        manager.delete(row['id'], confirmed_not_created=True)
    assert not row.get('delete_requested')
    manager._active.discard(row['id'])


def test_absence_confirmation_api(manager):
    from fastapi.testclient import TestClient
    from auto_mixture_tool.api.server import app
    row = record(manager)
    row.update(status='NEEDS_ATTENTION')
    row['jobs'][0].update(id=None, status='SUBMITTING')
    with patch('auto_mixture_tool.api.server._workflow_manager', return_value=manager), patch.object(manager, '_start_delete'):
        client = TestClient(app)
        result = client.delete('/api/v1/workflows/' + row['id'] + '?confirmed_not_created=true')
        assert result.status_code == 202
        assert result.json()['jobs'][0]['status'] == 'NOT_CREATED'
