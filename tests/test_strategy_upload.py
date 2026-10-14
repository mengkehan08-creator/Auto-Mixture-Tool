from pathlib import Path
from unittest.mock import patch

import pytest
pytestmark = pytest.mark.usefixtures('mock_resource_preflight')

from auto_mixture_tool.modelarts.config_transport import read_config
from auto_mixture_tool.modelarts.strategy_upload import validate_script, materialize_scripts
from auto_mixture_tool.modelarts.stage_runner import _comparison
from test_workflow_execution import manager
from test_modelarts_workflow import config


SOURCE = "STRATEGY_API_VERSION = '1'\ndef select(pool, context, config):\n    return [0]\n"


def upload(name='strategy.py', content=SOURCE):
    return {'name': name, 'content': content}


@pytest.mark.parametrize('data', [upload('../escape.py'), upload('test.txt'), upload(content=''),
    upload(content='x' * 32769), upload(content='def broken('), upload(content='print(1)'),
    upload(content='\ud800'), {'name': 'x.py'}])
def test_invalid_upload(data):
    with pytest.raises(ValueError):
        validate_script(data)


def test_validation_does_not_execute(tmp_path):
    content = SOURCE + "\nraise RuntimeError('must not execute')\n"
    validate_script(upload(content=content))
    cfg = {'strategies': [{'type': 'manual', 'id': 'm1', 'script_upload': upload(content=content)}]}
    materialize_scripts(cfg, tmp_path)
    assert (tmp_path / 'strategy_0.py').read_text(encoding='utf-8') == content
    assert _comparison(cfg)['manual_plans'][0]['strategy']['script_path'] == str(tmp_path / 'strategy_0.py')


def test_upload_transported_only_to_mixing(manager, tmp_path):
    cfg = config()
    strategy = {'id': 'random', 'type': 'random', 'name': 'uploaded random', 'seed': 42}
    cfg['strategies'].append(strategy)
    strategy['script_upload'] = upload()
    with patch.object(manager, '_start'):
        result = manager.create(cfg)
    record = manager.records[result['id']]
    first = manager._payload(record, 'mixing')
    decoded = read_config(first['algorithm']['environments'])
    assert next(s for s in decoded['strategies'] if s['type'] == 'random')['script_upload'] == upload()
    materialize_scripts(decoded, tmp_path)
    assert Path(_comparison(decoded)['random_strategy']['script_path']).is_file()
    second = read_config(manager._payload(record, 'training')['algorithm']['environments'])
    assert all('script_upload' not in s for s in second['strategies'])
    assert next(s for s in manager.copy_configuration(result['id'])['strategies'] if s['type'] == 'random')['script_upload'] == upload()
    strategy['script_obs_uri'] = 'obs://bucket/strategy.py'
    with pytest.raises(ValueError, match='一种脚本来源'):
        manager.create(cfg)


def test_examples_conform():
    root = Path(__file__).resolve().parents[1]
    for name in ['manual_quality_first.py', 'random_length_aware.py']:
        validate_script(upload(name, (root / 'examples/strategies' / name).read_text(encoding='utf-8')))
