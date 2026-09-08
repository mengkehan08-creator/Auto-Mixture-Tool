from pathlib import Path
from unittest.mock import patch

import pytest

from auto_mixture_tool.modelarts.iam_auth import IamTokenProvider
from auto_mixture_tool.plugins.trainers.nanochat import NanoChatTrainer
from test_modelarts_workflow import config
from test_workflow_execution import manager


def test_iam_error_is_not_template_error(manager):
    provider = IamTokenProvider({'account': 'test-account'})
    with patch('auto_mixture_tool.modelarts.workflow.get_provider', return_value=provider):
        with pytest.raises(ValueError, match='secret') as error:
            manager.preview(config())
    assert '请求模板' not in str(error.value)


def test_missing_template_has_actionable_error(manager):
    with patch.object(manager, '_configured_template', side_effect=FileNotFoundError()):
        with pytest.raises(ValueError, match='--workspace'):
            manager.preview(config())


@pytest.mark.parametrize('section,key,value', [
    ('training', 'base_model_tag', '../other'),
    ('training', 'devices_per_node', 2.5),
    ('evaluation', 'datasets', ['stem', 'gsm8k_cot']),
])
def test_invalid_runtime_choices_fail_locally(manager, section, key, value):
    body = config()
    body[section][key] = value
    with pytest.raises(ValueError):
        manager.create(body)
    assert not manager.client.submissions


@pytest.mark.parametrize('key,value', [('proxy_steps', 1.5), ('devices_per_node', 9),
    ('seed', -1), ('script_config', []), ('id', '../bad'), ('name', 'a\nb')])
def test_strategy_validation(manager, key, value):
    body = config()
    body['strategies'][0][key] = value
    with pytest.raises(ValueError):
        manager.preview(body)


def test_duplicate_ids_rejected(manager):
    body = config()
    body['strategies'][1]['id'] = 'quadmix'
    with pytest.raises(ValueError, match='唯一'):
        manager.preview(body)


def test_shared_seed_reaches_sampler(manager):
    body = config()
    body['strategies'][0]['seed'] = 123
    validated = manager._validate(body)
    assert all(s['seed'] == 123 for s in validated['strategies'])
    commands = NanoChatTrainer().build({
        'job_id': 'test', 'dataset_uri': '/data', 'schema_uri': '/schema',
        'algorithm_config': {'seed': 123},
        'comparison_config': {'methods': ['quadmix', 'random']},
    }, Path('/workspace'))
    assert commands[0].env['SEED'] == '123'


def test_oversized_config_rejected_before_record_or_submit(manager):
    body = config()
    body['strategies'][0]['script_config'] = {'payload': 'x' * 1100000}
    with pytest.raises(ValueError, match='安全上限'):
        manager.create(body)
    assert not manager.records
    assert not manager.client.submissions


def test_second_payload_failure_prevents_first_job(manager):
    original = manager._payload
    def payload(record, stage):
        if stage == 'training':
            raise ValueError('second stage invalid')
        return original(record, stage)
    with patch.object(manager, '_payload', side_effect=payload):
        with pytest.raises(ValueError, match='second stage'):
            manager.create(config())
    assert not manager.records and not manager.client.submissions


def test_invalid_iam_file_does_not_stop_resume(manager):
    with patch.object(manager, '_start'):
        result = manager.create(config())
    with patch('auto_mixture_tool.modelarts.workflow.get_provider', side_effect=ValueError('IAM 私有配置无效')):
        manager.resume()
    assert manager.get(result['id'])['status'] == 'WAITING_AUTH'


def test_nonfinite_script_config_rejected(manager):
    body = config()
    body['strategies'][0]['script_config'] = {'value': float('nan')}
    with pytest.raises(ValueError, match='JSON'):
        manager.create(body)
