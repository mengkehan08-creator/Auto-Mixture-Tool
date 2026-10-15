import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/reuse_modelarts_auth_env.py'
spec = importlib.util.spec_from_file_location('reuse_modelarts_auth_env', SCRIPT)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


@pytest.fixture
def backend(tmp_path):
    workspace = tmp_path / 'Auto-Mixture-Tool'
    workspace.mkdir()
    private = tmp_path / 'private_auth'
    private.mkdir()
    provider = private / 'iam_token_provider.py'
    provider.write_text('not executed\n')
    process = tmp_path / '1406516'
    process.mkdir()
    (process / 'cwd').symlink_to(workspace)
    args = ['python', '-m', 'auto_mixture_tool.cli', '--workspace', str(workspace), 'serve']
    (process / 'cmdline').write_bytes('\0'.join(args).encode() + b'\0')
    environment = {
        'AMT_IAM_PROVIDER': str(provider),
        'HTTPS_PROXY': "http://user:fake-password'$(touch should-not-exist)@proxy.example",
        'https_proxy': 'http://lowercase-proxy.example',
        'NO_PROXY': 'localhost,iam.his-op.huawei.com',
        'no_proxy': 'different.internal',
        'UNRELATED_SECRET': 'must-not-copy',
    }
    (process / 'environ').write_bytes(b'\0'.join(
        os.fsencode(key + '=' + value) for key, value in environment.items()
    ) + b'\0')
    return process, workspace, environment


def test_snapshot_round_trips_proxy_values_without_shell_execution(backend, tmp_path, capsys):
    process, workspace, environment = backend
    selected = migration.read_auth_environment(process, workspace)
    assert 'UNRELATED_SECRET' not in selected
    output = migration.save_auth_environment(selected)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    code = 'import json,os; print(json.dumps({k: os.environ.get(k) for k in ' + repr(list(migration.AUTH_ENV)) + '}))'
    result = subprocess.run(
        ['bash', '-c', 'source "$1"; exec "$2" -c "$3"', 'snapshot', str(output), sys.executable, code],
        cwd=tmp_path, env={**os.environ, 'ALL_PROXY': 'http://new-only-proxy.example',
                          'REQUESTS_CA_BUNDLE': '/new-only-ca.pem'},
        capture_output=True, text=True, check=True,
    )
    restored = json.loads(result.stdout)
    assert restored == {key: selected.get(key) for key in migration.AUTH_ENV}
    assert not (tmp_path / 'should-not-exist').exists()
    assert 'must-not-copy' not in output.read_text()
    assert capsys.readouterr().out == ''


def test_replacing_existing_snapshot_keeps_private_permissions(backend):
    process, workspace, _ = backend
    selected = migration.read_auth_environment(process, workspace)
    output = Path(selected['AMT_IAM_PROVIDER']).parent / 'amt_multinode_runtime.env'
    output.write_text('old snapshot')
    output.chmod(0o644)
    assert migration.save_auth_environment(selected) == output
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_rejects_wrong_workspace_and_non_backend(backend, tmp_path):
    process, workspace, _ = backend
    other = tmp_path / 'Auto-Mixture-Tool-MultiNode'
    other.mkdir()
    with pytest.raises(ValueError, match='工作目录'):
        migration.read_auth_environment(process, other)
    (process / 'cmdline').write_bytes(b'python\0unrelated.py\0')
    with pytest.raises(ValueError, match='不是 Auto-Mixture-Tool'):
        migration.read_auth_environment(process, workspace)


def test_rejects_other_users_process(backend, monkeypatch):
    process, workspace, _ = backend
    owner = process.stat().st_uid
    monkeypatch.setattr(migration.os, 'getuid', lambda: owner + 1)
    with pytest.raises(ValueError, match='当前用户'):
        migration.read_auth_environment(process, workspace)


@pytest.mark.parametrize('style', ['cwd', 'equals', 'relative'])
def test_workspace_argument_forms(backend, style):
    process, workspace, _ = backend
    options = {'cwd': [], 'equals': ['--workspace=' + str(workspace)],
               'relative': ['--workspace', '.']}[style]
    command = ['auto-mixture', *options, 'serve']
    (process / 'cmdline').write_bytes('\0'.join(command).encode() + b'\0')
    assert migration.read_auth_environment(process, workspace)['AMT_IAM_PROVIDER']


def test_rejects_missing_provider_and_output_inside_git_repository(backend):
    process, workspace, _ = backend
    with pytest.raises(ValueError, match='私有文件绝对路径'):
        migration.save_auth_environment({})
    provider = workspace / 'private.py'
    provider.write_text('not executed')
    (workspace / '.git').mkdir()
    with pytest.raises(ValueError, match='Git 仓库之外'):
        migration.save_auth_environment({'AMT_IAM_PROVIDER': str(provider)})
    assert not (workspace / 'amt_multinode_runtime.env').exists()


def test_cli_failure_does_not_print_environment_values(backend, monkeypatch, capsys):
    process, workspace, _ = backend
    def fail(*_):
        raise PermissionError('fake-password must-not-print')
    monkeypatch.setattr(migration, 'read_auth_environment', fail)
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--pid', '1406516', '--workspace', str(workspace)])
    assert migration.main() == 1
    message = capsys.readouterr().out
    assert '复制失败' in message
    assert 'fake-password' not in message and 'must-not-print' not in message


def test_cli_success_prints_only_private_snapshot_path(backend, monkeypatch, capsys):
    process, workspace, _ = backend
    selected = migration.read_auth_environment(process, workspace)
    monkeypatch.setattr(migration, 'read_auth_environment', lambda *_: selected)
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--pid', '1406516', '--workspace', str(workspace)])
    assert migration.main() == 0
    message = capsys.readouterr().out
    assert 'amt_multinode_runtime.env' in message
    assert 'fake-password' not in message and 'proxy.example' not in message


def test_failed_snapshot_write_preserves_previous_file_and_removes_temporary(backend, monkeypatch):
    process, workspace, _ = backend
    selected = migration.read_auth_environment(process, workspace)
    output = Path(selected['AMT_IAM_PROVIDER']).parent / 'amt_multinode_runtime.env'
    output.write_text('previous snapshot')
    def fail(*_):
        raise OSError('write failure')
    monkeypatch.setattr(migration.os, 'replace', fail)
    with pytest.raises(OSError):
        migration.save_auth_environment(selected)
    assert output.read_text() == 'previous snapshot'
    assert list(output.parent.glob('.amt-runtime-*')) == []
