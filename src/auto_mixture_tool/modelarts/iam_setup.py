"""Activate an existing server-private IAM configuration without running it."""

import os
import threading
from pathlib import Path

from .iam_auth import _load_provider, _read_provider


class IamSetupError(ValueError):
    """A configuration failure whose message is safe to return to the UI."""


_configure_lock = threading.Lock()


def configure_iam_provider(workspace: Path, endpoint: str) -> dict:
    """Validate the selected private file and enable IAM in this server process."""
    with _configure_lock:
        configured = os.environ.get('AMT_IAM_PROVIDER', '').strip()
        try:
            candidate = (Path(configured) if configured else
                         Path(workspace).resolve().parent / 'private_auth' / 'iam_token_provider.py')
            if not candidate.is_absolute():
                raise IamSetupError('AMT_IAM_PROVIDER 必须指向仓库外已存在的私有 Python 文件绝对路径')
            source = candidate.resolve(strict=True)
            if not source.is_file():
                raise IamSetupError('IAM 私有配置必须为已存在的 Python 文件')
            if any((parent / '.git').is_file() or (parent / '.git').is_dir()
                   for parent in source.parents):
                raise IamSetupError('IAM 私有配置必须位于所有 Git 仓库之外，请使用独立私有副本')
        except IamSetupError:
            raise
        except (OSError, RuntimeError, ValueError):
            if not configured:
                message = ('未找到可读取的 IAM 私有配置；请先在工具目录同级 '
                           'private_auth/iam_token_provider.py 准备有效私有配置')
            else:
                message = '无法读取 AMT_IAM_PROVIDER 指定的私有配置，请检查文件路径与读取权限'
            raise IamSetupError(message) from None

        try:
            # Read afresh: a failed retry must leave the active provider cache intact.
            provider = _read_provider(str(source))
            provider.validate_endpoint(endpoint)
        except Exception:
            raise IamSetupError('IAM 私有配置无效或与当前 ModelArts 地址不匹配，请检查必填项与授权范围') from None

        os.environ['AMT_IAM_PROVIDER'] = str(source)
        _load_provider.cache_clear()
        return {'auth_mode': 'iam', 'message': 'IAM 自动认证已配置并立即生效，无需重启服务'}
