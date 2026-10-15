"""Snapshot a same-user Linux AMT backend's auth startup environment privately."""

import argparse
import os
import shlex
import tempfile
from pathlib import Path


AUTH_ENV = (
    'AMT_IAM_PROVIDER',
    'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY',
    'http_proxy', 'https_proxy', 'all_proxy',
    'NO_PROXY', 'no_proxy',
    'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
)


def read_auth_environment(process: Path, workspace: Path) -> dict[str, str]:
    if process.stat().st_uid != os.getuid():
        raise ValueError('只能复用当前用户自己的后端进程')
    command = (process / 'cmdline').read_bytes()
    args = [os.fsdecode(value) for value in command.split(b'\0') if value]
    if 'serve' not in args or not any(
        'auto_mixture_tool' in arg or Path(arg).name == 'auto-mixture' for arg in args
    ):
        raise ValueError('指定 PID 不是 Auto-Mixture-Tool 后端')
    cwd = (process / 'cwd').resolve(strict=True)
    if '--workspace' in args:
        index = args.index('--workspace') + 1
        if index >= len(args):
            raise ValueError('旧版进程缺少工作目录参数')
        actual = Path(args[index])
    else:
        actual = Path(next((arg.split('=', 1)[1] for arg in args
                            if arg.startswith('--workspace=')), str(cwd)))
    if (cwd / actual).resolve() != workspace.resolve(strict=True):
        raise ValueError('指定 PID 的工作目录与旧版目录不一致')
    environment = {}
    for entry in (process / 'environ').read_bytes().split(b'\0'):
        key, separator, value = entry.partition(b'=')
        name = os.fsdecode(key)
        if separator and name in AUTH_ENV:
            environment[name] = os.fsdecode(value)
    if (process / 'cmdline').read_bytes() != command:
        raise ValueError('旧版进程已变化，请重新检查 PID')
    return environment


def save_auth_environment(environment: dict[str, str]) -> Path:
    provider = Path(environment.get('AMT_IAM_PROVIDER', ''))
    if not provider.is_absolute() or not provider.is_file():
        raise ValueError('旧版未设置有效的 AMT_IAM_PROVIDER 私有文件绝对路径')
    output = provider.resolve().parent / 'amt_multinode_runtime.env'
    if any((parent / '.git').exists() for parent in output.parents):
        raise ValueError('认证环境文件必须保存在 Git 仓库之外的私有目录')
    fd, temporary = tempfile.mkstemp(prefix='.amt-runtime-', dir=output.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', errors='surrogateescape') as stream:
            stream.write('# Private AMT auth startup environment. Do not upload.\n')
            for key in AUTH_ENV:
                if key in environment:
                    stream.write(f'export {key}={shlex.quote(environment[key])}\n')
                else:
                    stream.write(f'unset {key}\n')
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description='复用正在运行的旧版 AMT 的认证启动环境；不显示配置值')
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--workspace', type=Path, required=True, help='旧版工具代码目录')
    args = parser.parse_args()
    if args.pid <= 0:
        parser.error('PID 必须大于 0')
    try:
        environment = read_auth_environment(Path('/proc') / str(args.pid), args.workspace)
        output = save_auth_environment(environment)
    except ValueError as error:
        print(f'复制失败：{error}')
        return 1
    except OSError:
        print('复制失败：旧版进程或私有目录不可访问，请确认 PID、目录和权限')
        return 1
    print(f'已保存认证启动环境：{output}（权限 600，配置值不显示）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
