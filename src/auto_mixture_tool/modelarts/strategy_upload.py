"""Validate small trusted strategy sources without importing or executing them."""
import ast
from pathlib import Path

MAX_SCRIPT_BYTES = 32 * 1024
MAX_TOTAL_BYTES = 128 * 1024


def validate_script(upload):
    if not isinstance(upload, dict) or set(upload) != {'name', 'content'}:
        raise ValueError('上传脚本必须包含 name 和 content')
    name, content = upload['name'], upload['content']
    if (not isinstance(name, str) or not name.lower().endswith('.py') or len(name) > 128
            or any(c in name for c in '/\\\x00\r\n') or name in {'.py', '..py'}):
        raise ValueError('请选择有效的 .py 脚本文件')
    if not isinstance(content, str) or not content.strip():
        raise ValueError('策略脚本内容不能为空')
    try:
        size = len(content.encode('utf-8'))
    except UnicodeError:
        raise ValueError('策略脚本必须使用 UTF-8 编码') from None
    if size > MAX_SCRIPT_BYTES:
        raise ValueError('直接上传的单个脚本不能超过 32 KiB，较大脚本请使用 OBS 地址')
    try:
        tree = ast.parse(content)
        compile(tree, '<uploaded-strategy>', 'exec')
    except (SyntaxError, ValueError, RecursionError):
        raise ValueError('策略脚本 Python 语法不正确') from None
    version = any(isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'STRATEGY_API_VERSION' for t in node.targets)
                  and isinstance(node.value, ast.Constant) and node.value.value == '1'
                  for node in tree.body)
    select = any(isinstance(node, ast.FunctionDef) and node.name == 'select' for node in tree.body)
    if not version or not select:
        raise ValueError("策略脚本须声明 STRATEGY_API_VERSION = '1' 并定义 select(pool, context, config)")
    return size


def materialize_scripts(config, directory):
    total = 0
    for index, strategy in enumerate(config.get('strategies', [])):
        upload = strategy.get('script_upload')
        if upload is None:
            continue
        if strategy.get('type') not in {'manual', 'random'} or strategy.get('script_obs_uri'):
            raise ValueError('人工或随机策略只能选择一种脚本来源')
        total += validate_script(upload)
        if total > MAX_TOTAL_BYTES:
            raise ValueError('本次上传脚本总大小不能超过 128 KiB')
        # Never use the uploaded filename as an output path.
        path = Path(directory) / f'strategy_{index}.py'
        path.write_text(upload['content'], encoding='utf-8')
        strategy['local_script_path'] = str(path)
