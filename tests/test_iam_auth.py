import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from auto_mixture_tool.modelarts.iam_auth import IamTokenProvider, get_provider, _load_provider
from auto_mixture_tool.modelarts.workflow import ModelArtsClient, ModelArtsRejected


def config():
    return dict(account='test-account', secret='test-only-secret', project='test-project',
                enterprise='test-enterprise', modelarts_endpoint='https://gateway.example/jobs')


def response(token='test-token', **changes):
    body = {'access_token': token, 'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    body.update(changes)
    return SimpleNamespace(status_code=200, json=lambda: body)


def test_cache_and_force_refresh():
    provider = IamTokenProvider(config())
    with patch('requests.post', side_effect=[response('token-one'), response('token-two')]) as post:
        assert provider.authorization(config()['modelarts_endpoint']) == 'token-one'
        assert provider.authorization(config()['modelarts_endpoint']) == 'token-one'
        assert provider.authorization(config()['modelarts_endpoint'], True) == 'token-two'
    assert post.call_count == 2
    assert post.call_args.kwargs['verify'] is True
    assert post.call_args.kwargs['allow_redirects'] is False


def test_private_endpoint_binding_and_placeholders():
    with patch('requests.post') as post:
        with pytest.raises(ValueError, match='授权范围'):
            IamTokenProvider(config()).authorization('https://other.example/jobs')
        cfg = config()
        cfg['secret'] = 'REPLACE_ME_SECRET'
        with pytest.raises(ValueError, match='secret'):
            IamTokenProvider(cfg).authorization(cfg['modelarts_endpoint'])
        post.assert_not_called()


@pytest.mark.parametrize('result', [
    SimpleNamespace(status_code=401, json=lambda: {'message': 'test-only-secret'}),
    response('bad\nheader'),
    response(expires_at='2000-01-01T00:00:00Z'),
    requests.ConnectionError('test-only-secret'),
])
def test_iam_errors_do_not_leak_secrets(result):
    provider = IamTokenProvider(config())
    with patch('requests.post', side_effect=[result]):
        with pytest.raises(ValueError) as error:
            provider.authorization(config()['modelarts_endpoint'])
    assert 'test-only-secret' not in str(error.value)


def test_unknown_expiry_not_cached():
    provider = IamTokenProvider(config())
    with patch('requests.post', return_value=response(expires_at='')) as post:
        provider.authorization(config()['modelarts_endpoint'])
        provider.authorization(config()['modelarts_endpoint'])
        assert post.call_count == 2


def test_client_gets_fresh_token_on_each_submission():
    provider = IamTokenProvider(config())
    template = SimpleNamespace(url=config()['modelarts_endpoint'], headers={'Authorization': ''})
    with patch('auto_mixture_tool.modelarts.workflow.get_provider', return_value=provider):
        client = ModelArtsClient(template)
    with patch.object(provider, 'authorization', return_value='private-token') as auth:
        with patch('requests.post', return_value=SimpleNamespace(status_code=200, json=lambda: {'id': 'job'})) as post:
            client.submit({})
            client.submit({})
            assert auth.call_count == 2
            assert all(call.args[1] is True for call in auth.call_args_list)
            assert post.call_args.kwargs['headers']['Authorization'] == 'private-token'
            assert post.call_args.kwargs['verify'] is True
        with patch('requests.get', return_value=SimpleNamespace(status_code=400, json=lambda: {'error_msg': 'private-token'})):
            with pytest.raises(ModelArtsRejected) as error:
                client.get('job')
            assert 'private-token' not in str(error.value)
    assert 'private-token' not in str(client.headers)


def test_opt_in_and_placeholder_template(monkeypatch):
    monkeypatch.delenv('AMT_IAM_PROVIDER', raising=False)
    assert get_provider() is None
    path = Path(__file__).resolve().parents[1] / 'iam_token_provider.py'
    spec = importlib.util.spec_from_file_location('template', path)
    module = importlib.util.module_from_spec(spec)
    with patch('requests.post') as post:
        spec.loader.exec_module(module)
        post.assert_not_called()
    assert module.AUTH_CONFIG['secret'] == 'REPLACE_ME_SECRET'
    monkeypatch.setenv('AMT_IAM_PROVIDER', str(path))
    _load_provider.cache_clear()
    with pytest.raises(ValueError):
        get_provider().validate_endpoint(config()['modelarts_endpoint'])
    _load_provider.cache_clear()
