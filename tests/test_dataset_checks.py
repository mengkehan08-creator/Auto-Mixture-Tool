from threading import Event
from unittest.mock import patch

import pytest

from auto_mixture_tool.modelarts import dataset_checks as checks
from auto_mixture_tool.modelarts.input_validation import validate_workflow_resources


@pytest.fixture(autouse=True)
def isolated_checks(monkeypatch):
    monkeypatch.setattr(checks, '_checks', {})
    monkeypatch.setattr(checks, '_latest', {})


def complete(uri='obs://bucket/data/', **kwargs):
    # Deterministic executor: capture work rather than rely on sleeps.
    with patch.object(checks._pool, 'submit') as submit:
        result = checks.start_dataset_check(uri, **kwargs)
    if submit.called:
        checks._run(result['check_id'])
    return checks.get_dataset_check(result['check_id'])


def test_success_is_reused_without_reading_input_at_submission():
    with patch.object(checks, 'validate_resource', return_value={'ready': True, 'message': 'OK', 'estimated_tokens': 100}) as read:
        result = complete()
        assert result['ready'] and result['estimated_tokens'] == 100
        assert checks.start_dataset_check('obs://bucket/data')['check_id'] == result['check_id']
        with patch('auto_mixture_tool.modelarts.input_validation.validate_resource', side_effect=AssertionError('must not read')):
            validate_workflow_resources({'input_data_obs_uri': 'obs://bucket/data/'})
        read.assert_called_once()


def test_unknown_changed_pending_failed_and_expired_checks_block():
    with pytest.raises(ValueError, match='不能提交'):
        checks.require_dataset_check('obs://bucket/data/')
    with patch.object(checks._pool, 'submit'):
        pending = checks.start_dataset_check('obs://bucket/data/')
    with pytest.raises(ValueError, match='不能提交'):
        checks.require_dataset_check('obs://bucket/data/')
    with patch.object(checks, 'validate_resource', side_effect=ValueError('bad data')):
        checks._run(pending['check_id'])
    assert checks.get_dataset_check(pending['check_id'])['message'] == 'bad data'
    with pytest.raises(ValueError, match='不能提交'):
        checks.require_dataset_check('obs://bucket/data/')
    with patch.object(checks, 'validate_resource', return_value={'ready': True, 'message': 'OK'}):
        result = complete(force=True)
    with pytest.raises(ValueError, match='不能提交'):
        checks.require_dataset_check('obs://bucket/other/')
    checks._checks[result['check_id']]['finished'] -= checks.CHECK_TTL
    with pytest.raises(ValueError, match='过期'):
        checks.require_dataset_check('obs://bucket/data/')


def test_start_returns_without_waiting_for_read_and_deduplicates():
    entered, release, finished = Event(), Event(), Event()
    def read(*args):
        entered.set()
        assert release.wait(5)
        return {'ready': True, 'message': 'OK'}
    original = checks._run
    def run(check_id):
        try:
            original(check_id)
        finally:
            finished.set()
    with patch.object(checks, 'validate_resource', side_effect=read), patch.object(checks, '_run', side_effect=run):
        result = checks.start_dataset_check('obs://bucket/data/')
        try:
            assert result['status'] == 'RUNNING'
            assert entered.wait(5)
            assert checks.start_dataset_check('obs://bucket/data/', force=True)['check_id'] == result['check_id']
        finally:
            release.set()
            assert finished.wait(5)
    assert checks.get_dataset_check(result['check_id'])['ready']


def test_mount_change_does_not_reuse_old_result(monkeypatch):
    with patch.object(checks, 'validate_resource', return_value={'ready': True, 'message': 'OK'}):
        complete()
    monkeypatch.setenv('AMT_OBS_MOUNT_ROOT', '/different/mount')
    with pytest.raises(ValueError, match='不能提交'):
        checks.require_dataset_check('obs://bucket/data/')


def test_api_start_poll_and_failure_are_json():
    from fastapi.testclient import TestClient
    from auto_mixture_tool.api.server import app
    client = TestClient(app)  # No lifespan: do not resume any cloud workflows.
    with patch.object(checks._pool, 'submit'):
        response = client.post('/api/v1/resources/validate', json={'kind': 'dataset', 'uri': 'obs://bucket/data/'})
    assert response.status_code == 200 and response.json()['status'] == 'RUNNING'
    check_id = response.json()['check_id']
    with patch.object(checks, 'validate_resource', side_effect=ValueError('格式不符合')):
        checks._run(check_id)
    result = client.get(f'/api/v1/resources/checks/{check_id}').json()
    assert result['status'] == 'FAILED' and not result['ready'] and result['message'] == '格式不符合'
    assert client.get('/api/v1/resources/checks/missing').status_code == 400
