"""Optional server-private IAM JWT authentication; credentials never enter job config."""

import ast
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import requests


class IamTokenProvider:
    def __init__(self, config):
        self.config = dict(config)
        self._lock = threading.Lock()
        self._token = ''
        self._expires_at = None

    def validate_endpoint(self, endpoint):
        for key in ('account', 'secret', 'project', 'enterprise'):
            value = self.config.get(key)
            if not isinstance(value, str) or not value.strip() or 'REPLACE_ME' in value:
                raise ValueError(f'IAM 私有配置缺少有效的 {key}')
        target = endpoint.rstrip('/')
        parsed = urlsplit(target)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or any(c.isspace() for c in target)):
            raise ValueError('ModelArts 地址必须为无鉴权参数的 HTTPS 作业 API 地址')
        allowed = self.config.get('modelarts_endpoint', '')
        if allowed and 'REPLACE_ME' not in allowed:
            if target != allowed.rstrip('/'):
                raise ValueError('当前 ModelArts API 地址不在独立配置的授权范围内')
        else:
            # Legacy auth.endpoint is unused by JWT acquisition. Never derive a
            # job URL from it. Allow only this known gateway and account scope.
            route = (r'/csb/projects/' + re.escape(self.config['account'])
                     + r'/vendors/huaweicloud-china/resourcetypes/modelarts/regions/'
                     + r'[a-z0-9-]+/projects/[a-zA-Z0-9]+(?:/v2/[a-zA-Z0-9]+)?/training-jobs')
            if (parsed.hostname != 'csbgw.roma.huawei.com' or parsed.port not in (None, 443)
                    or not re.fullmatch(route, parsed.path)):
                raise ValueError('作业地址不属于默认可信 ModelArts 网关；如使用其他接口，请单独配置 modelarts_endpoint')
        if self.config.get('authorization_prefix', '') not in ('', 'Bearer '):
            raise ValueError('authorization_prefix 只支持空字符串或 Bearer 加空格')

    def authorization(self, endpoint, force_refresh=False):
        self.validate_endpoint(endpoint)
        with self._lock:
            now = datetime.now(timezone.utc)
            if (not force_refresh and self._token and self._expires_at
                    and now + timedelta(minutes=5) < self._expires_at):
                return self.config.get('authorization_prefix', '') + self._token
            attributes = {key: self.config[key] for key in ('account', 'secret', 'project', 'enterprise')}
            try:
                response = requests.post(
                    'https://iam.his-op.huawei.com/iam/auth/token',
                    json={'data': {'type': 'jwt-token', 'attributes': attributes}},
                    headers={'Content-Type': 'application/json'}, timeout=30,
                    verify=self.config.get('ca_bundle') or True, allow_redirects=False,
                )
            except requests.RequestException:
                raise ValueError('IAM Token 获取失败：请检查网络、代理及 CA 证书') from None
            if not 200 <= response.status_code < 300:
                raise ValueError(f'IAM Token 获取失败（HTTP {response.status_code}），请检查私有认证配置')
            try:
                data = response.json()
                token = data.get('access_token')
            except (ValueError, AttributeError):
                raise ValueError('IAM 响应格式无效') from None
            if not isinstance(token, str) or not token.strip() or any(c.isspace() for c in token):
                raise ValueError('IAM 响应缺少有效 access_token')
            expires = None
            try:
                expires = datetime.fromisoformat(str(data.get('expires_at', '')).replace('Z', '+00:00'))
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
            except ValueError:
                pass  # Unknown expiry: do not reuse the token on the next request.
            if expires is not None and expires <= now:
                raise ValueError('IAM 返回的 Token 已过期')
            self._token, self._expires_at = token, expires
            return self.config.get('authorization_prefix', '') + token


@lru_cache(maxsize=1)
def _load_provider(path):
    source = Path(path)
    if not source.is_absolute() or not source.is_file():
        raise ValueError('AMT_IAM_PROVIDER 必须指向已存在的私有 Python 文件绝对路径')
    try:
        tree = ast.parse(source.read_text(encoding='utf-8-sig'))
        assignments = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {'AUTH_CONFIG', 'auth'}:
                        assignments[target.id] = ast.literal_eval(node.value)
        config = assignments.get('AUTH_CONFIG', assignments.get('auth'))
        if not isinstance(config, dict):
            raise ValueError('missing literal config')
        config = dict(config)
        if 'AUTH_CONFIG' not in assignments:
            config['project'] = config.get('project') or config.get('account')
        return IamTokenProvider(config)
    except Exception:
        raise ValueError('无法加载 IAM 私有配置：需要 AUTH_CONFIG 或 auth 字面量字典；详细内容不会输出') from None


def get_provider():
    path = os.environ.get('AMT_IAM_PROVIDER', '').strip()
    return _load_provider(path) if path else None
