import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from auto_mixture_tool.modelarts.iam_auth import _load_provider, get_provider
from auto_mixture_tool.modelarts.iam_setup import IamSetupError, configure_iam_provider


ENDPOINT = 'https://gateway.example/jobs'
SECRET = 'private-secret-must-not-escape'


def config():
    return dict(account='test-account', secret=SECRET, project='test-project',
                enterprise='test-enterprise', modelarts_endpoint=ENDPOINT)


def write_provider(path, value=None, extra=''):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('AUTH_CONFIG = ' + repr(config() if value is None else value) + '\n' + extra,
                    encoding='utf-8')
    return path


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('AMT_IAM_PROVIDER', '')
    monkeypatch.delenv('AMT_IAM_PROVIDER', raising=False)
    _load_provider.cache_clear()
    root = tmp_path / 'tool'
    root.mkdir()
    (root / '.git').mkdir()
    yield root
    _load_provider.cache_clear()


def default_file(workspace):
    return workspace.parent / 'private_auth' / 'iam_token_provider.py'


def test_default_config_activates_without_network_or_executing_python(workspace, capsys):
    source = write_provider(default_file(workspace), extra=(
        "import module_that_does_not_exist\nprint('must-not-execute')\n"
        "raise RuntimeError('must-not-execute')\n"))
    before = source.read_text()
    with patch('requests.post') as post, patch('requests.get') as get:
        result = configure_iam_provider(workspace, ENDPOINT)
    assert result == {'auth_mode': 'iam', 'message': 'IAM 自动认证已配置并立即生效，无需重启服务'}
    assert get_provider().config == config()
    assert source.read_text() == before
    assert SECRET not in repr(result)
    assert str(source) not in repr(result)
    post.assert_not_called()
    get.assert_not_called()
    assert capsys.readouterr() == ('', '')


def test_existing_environment_has_priority(workspace, monkeypatch):
    existing = write_provider(workspace.parent / 'other_private.py', dict(config(), account='existing'))
    write_provider(default_file(workspace))
    monkeypatch.setenv('AMT_IAM_PROVIDER', str(existing))
    configure_iam_provider(workspace, ENDPOINT)
    assert get_provider().config['account'] == 'existing'


@pytest.mark.parametrize('path', ['private_auth/iam_token_provider.py', '/missing/private-secret-must-not-escape.py'])
def test_invalid_environment_never_falls_back_or_changes_environment(workspace, monkeypatch, path):
    write_provider(default_file(workspace))
    monkeypatch.setenv('AMT_IAM_PROVIDER', path)
    with pytest.raises(IamSetupError) as error:
        configure_iam_provider(workspace, ENDPOINT)
    assert os.environ['AMT_IAM_PROVIDER'] == path
    assert SECRET not in str(error.value)


@pytest.mark.parametrize('path', ['', ' '])
def test_blank_environment_uses_default_private_file(workspace, monkeypatch, path):
    source = write_provider(default_file(workspace))
    monkeypatch.setenv('AMT_IAM_PROVIDER', path)
    configure_iam_provider(workspace, ENDPOINT)
    assert os.environ['AMT_IAM_PROVIDER'] == str(source.resolve())


def test_missing_default_is_actionable_and_leaves_manual_auth(workspace):
    with pytest.raises(IamSetupError, match='工具目录同级 private_auth/iam_token_provider.py'):
        configure_iam_provider(workspace, ENDPOINT)
    assert get_provider() is None


@pytest.mark.parametrize('marker', ['directory', 'file'])
def test_files_in_any_git_repository_are_rejected(workspace, monkeypatch, marker):
    repo = workspace.parent / 'other-repository'
    source = write_provider(repo / 'nested' / 'private.py')
    git = repo / '.git'
    git.mkdir() if marker == 'directory' else git.write_text('gitdir: /another/place')
    monkeypatch.setenv('AMT_IAM_PROVIDER', str(source))
    with pytest.raises(IamSetupError, match='所有 Git 仓库之外'):
        configure_iam_provider(workspace, ENDPOINT)


def test_resolved_symlink_into_repository_is_rejected(workspace, monkeypatch):
    source = write_provider(workspace / 'private.py')
    link = workspace.parent / 'private.py'
    link.symlink_to(source)
    monkeypatch.setenv('AMT_IAM_PROVIDER', str(link))
    with pytest.raises(IamSetupError, match='所有 Git 仓库之外'):
        configure_iam_provider(workspace, ENDPOINT)


def test_tracked_placeholder_template_is_rejected(workspace, monkeypatch):
    source = Path(__file__).resolve().parents[1] / 'iam_token_provider.py'
    monkeypatch.setenv('AMT_IAM_PROVIDER', str(source))
    with pytest.raises(IamSetupError, match='所有 Git 仓库之外'):
        configure_iam_provider(workspace, ENDPOINT)


def test_private_placeholder_copy_is_rejected(workspace):
    write_provider(default_file(workspace), dict(config(), secret='REPLACE_ME_SECRET'))
    with pytest.raises(IamSetupError):
        configure_iam_provider(workspace, ENDPOINT)
    assert get_provider() is None


@pytest.mark.parametrize('source', [
    "AUTH_CONFIG = {'secret': 'private-secret-must-not-escape'}",
    "AUTH_CONFIG = dict(secret='private-secret-must-not-escape')",
    "AUTH_CONFIG = {\nsecret = 'private-secret-must-not-escape'",
    "print('must-not-execute'); raise RuntimeError('private-secret-must-not-escape')",
])
def test_invalid_or_dynamic_config_does_not_execute_or_leak(workspace, monkeypatch, capsys, source):
    path = default_file(workspace)
    path.parent.mkdir()
    path.write_text(source)
    with pytest.raises(IamSetupError) as error:
        configure_iam_provider(workspace, ENDPOINT)
    assert 'AMT_IAM_PROVIDER' not in os.environ
    assert SECRET not in str(error.value)
    assert error.value.__suppress_context__ is True
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('endpoint', ['http://gateway.example/jobs', 'https://other.example/jobs', None])
def test_endpoint_validation_failure_preserves_active_provider(workspace, monkeypatch, endpoint):
    path = write_provider(default_file(workspace))
    monkeypatch.setenv('AMT_IAM_PROVIDER', str(path))
    active = get_provider()
    with pytest.raises(IamSetupError):
        configure_iam_provider(workspace, endpoint)
    assert os.environ['AMT_IAM_PROVIDER'] == str(path)
    assert get_provider() is active


def test_read_error_is_redacted_and_preserves_active_provider(workspace, monkeypatch):
    path = write_provider(default_file(workspace))
    monkeypatch.setenv('AMT_IAM_PROVIDER', str(path))
    active = get_provider()
    with patch.object(Path, 'read_text', side_effect=PermissionError(SECRET)):
        with pytest.raises(IamSetupError) as error:
            configure_iam_provider(workspace, ENDPOINT)
    assert SECRET not in str(error.value)
    assert get_provider() is active


def test_path_error_is_redacted_and_preserves_environment(workspace, monkeypatch):
    path = write_provider(default_file(workspace))
    monkeypatch.setenv('AMT_IAM_PROVIDER', str(path))
    with patch.object(Path, 'resolve', side_effect=PermissionError(SECRET)):
        with pytest.raises(IamSetupError) as error:
            configure_iam_provider(workspace, ENDPOINT)
    assert SECRET not in str(error.value)
    assert str(path) not in str(error.value)
    assert os.environ['AMT_IAM_PROVIDER'] == str(path)


def test_changed_file_is_read_again_and_old_cache_is_cleared_after_success(workspace, monkeypatch):
    path = write_provider(default_file(workspace))
    monkeypatch.setenv('AMT_IAM_PROVIDER', str(path))
    active = get_provider()
    write_provider(path, dict(config(), secret='updated-private-secret', iam_verify_ssl=False,
                              modelarts_verify_ssl=False))
    configure_iam_provider(workspace, ENDPOINT)
    updated = get_provider()
    assert updated is not active
    assert updated.config['secret'] == 'updated-private-secret'
    assert updated.config['iam_verify_ssl'] is False
    assert updated.config['modelarts_verify_ssl'] is False


def test_invalid_edit_leaves_previous_cache_and_environment_intact(workspace, monkeypatch):
    path = write_provider(default_file(workspace))
    monkeypatch.setenv('AMT_IAM_PROVIDER', str(path))
    active = get_provider()
    write_provider(path, dict(config(), secret='REPLACE_ME_SECRET'))
    with pytest.raises(IamSetupError):
        configure_iam_provider(workspace, ENDPOINT)
    assert get_provider() is active
    assert os.environ['AMT_IAM_PROVIDER'] == str(path)


def test_legacy_auth_dictionary_remains_supported(workspace):
    path = default_file(workspace)
    path.parent.mkdir()
    legacy = config()
    legacy.pop('project')
    path.write_text('auth = ' + repr(legacy))
    configure_iam_provider(workspace, ENDPOINT)
    assert get_provider().config['project'] == legacy['account']


def test_concurrent_repeated_configuration_is_idempotent(workspace):
    source = write_provider(default_file(workspace))
    with patch('requests.post') as post:
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(lambda _: configure_iam_provider(workspace, ENDPOINT), range(12)))
    assert all(result == results[0] for result in results)
    assert os.environ['AMT_IAM_PROVIDER'] == str(source.resolve())
    assert get_provider().config == config()
    post.assert_not_called()
