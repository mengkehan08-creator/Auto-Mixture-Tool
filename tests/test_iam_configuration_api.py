"""The configuration button enables IAM without fetching a token or submitting jobs."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from auto_mixture_tool.api import server
from auto_mixture_tool.modelarts.iam_auth import _load_provider, get_provider
from auto_mixture_tool.modelarts.workflow import ModelArtsClient, ModelArtsWorkflowManager


ENDPOINT = 'https://gateway.example/jobs'


@pytest.fixture
def setup_api(tmp_path, monkeypatch):
    workspace = tmp_path / 'Auto-Mixture-Tool'
    workspace.mkdir()
    private = tmp_path / 'private_auth'
    private.mkdir()
    provider = private / 'iam_token_provider.py'
    provider.write_text('AUTH_CONFIG = ' + repr({
        'account': 'test-account', 'secret': 'test-secret-not-for-response',
        'project': 'test-project', 'enterprise': 'test-enterprise',
        'modelarts_endpoint': ENDPOINT,
    }), encoding='utf-8')
    manager = ModelArtsWorkflowManager(workspace)
    monkeypatch.setattr(server, '_workflow_manager', lambda: manager)
    monkeypatch.setenv('AMT_IAM_PROVIDER', '')
    monkeypatch.delenv('AMT_IAM_PROVIDER', raising=False)
    requests = Mock(side_effect=AssertionError('Configuration must not request IAM or ModelArts'))
    monkeypatch.setattr('requests.sessions.Session.request', requests)
    _load_provider.cache_clear()
    yield TestClient(server.app), manager, provider, requests
    _load_provider.cache_clear()


def test_button_configures_running_backend_and_replaces_cached_manual_client(setup_api, monkeypatch):
    client, manager, provider, requests = setup_api
    template = SimpleNamespace(url=ENDPOINT, headers={'Authorization': 'manual-token'})
    monkeypatch.setattr(manager, '_template', lambda: template)
    previous_client = manager._client()
    assert previous_client.provider is None

    response = client.post('/api/v1/iam/configure', json={'endpoint': ENDPOINT})

    assert response.status_code == 200
    assert set(response.json()) == {'auth_mode', 'message'}
    assert response.json()['auth_mode'] == 'iam'
    assert client.get('/api/v1/workflow-defaults').json()['auth_mode'] == 'iam'
    assert manager.client is None
    new_client = manager._client()
    assert new_client is not previous_client
    assert new_client.provider is get_provider()
    assert new_client.provider.config['secret'] == 'test-secret-not-for-response'
    assert str(provider) not in response.text
    assert all(value not in response.text for value in ('test-account', 'test-secret-not-for-response', 'manual-token'))
    requests.assert_not_called()


def test_configuration_failure_preserves_manual_mode_and_cached_client(setup_api):
    client, manager, _, requests = setup_api
    previous_client = ModelArtsClient(SimpleNamespace(url=ENDPOINT, headers={'Authorization': 'manual-token'}))
    manager.client = previous_client

    response = client.post('/api/v1/iam/configure', json={'endpoint': 'https://different.example/jobs'})

    assert response.status_code == 400
    assert get_provider() is None
    assert manager.client is previous_client
    assert client.get('/api/v1/workflow-defaults').json()['auth_mode'] == 'manual'
    assert 'test-secret-not-for-response' not in response.text
    requests.assert_not_called()


def test_configuration_preserves_injected_client_and_never_resumes_workflows(setup_api):
    client, manager, _, requests = setup_api
    injected_client = object()
    manager.client = injected_client
    manager.resume = Mock(side_effect=AssertionError('Button must not resume jobs'))

    response = client.post('/api/v1/iam/configure', json={'endpoint': ENDPOINT})

    assert response.status_code == 200
    assert manager.client is injected_client
    manager.resume.assert_not_called()
    requests.assert_not_called()


@pytest.mark.parametrize('body', [
    {}, {'endpoint': 7}, {'endpoint': ''}, {'endpoint': 'x' * 2049},
    {'endpoint': ENDPOINT, 'provider_path': '/tmp/arbitrary.py'},
])
def test_request_accepts_only_an_endpoint_without_mutation(setup_api, body):
    client, _, _, requests = setup_api
    assert client.post('/api/v1/iam/configure', json=body).status_code == 422
    assert get_provider() is None
    requests.assert_not_called()


@pytest.mark.parametrize('content_type', [None, 'text/plain', 'application/x-www-form-urlencoded'])
def test_non_json_browser_requests_cannot_enable_iam(setup_api, content_type):
    client, _, _, requests = setup_api
    headers = {'Content-Type': content_type} if content_type else {}
    response = client.post('/api/v1/iam/configure', content=json.dumps({'endpoint': ENDPOINT}), headers=headers)
    assert response.status_code in (415, 422)
    assert get_provider() is None
    requests.assert_not_called()


def test_json_charset_header_is_supported(setup_api):
    client, _, _, requests = setup_api
    response = client.post('/api/v1/iam/configure', content=json.dumps({'endpoint': ENDPOINT}),
                           headers={'Content-Type': 'application/json; charset=utf-8'})
    assert response.status_code == 200
    requests.assert_not_called()
