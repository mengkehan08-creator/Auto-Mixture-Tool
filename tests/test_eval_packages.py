import pytest
pytestmark = pytest.mark.usefixtures('mock_resource_preflight')
from auto_mixture_tool.modelarts.evaluation_job import validate_package
from auto_mixture_tool.modelarts.workflow import ModelArtsWorkflowManager
from test_modelarts_workflow import config, FakeClient
from unittest.mock import patch
from pathlib import Path


def test_unsupported_package(tmp_path):
    (tmp_path / 'core.yaml').write_text('icl_tasks:\n- label: test\n  icl_task_type: unknown\n')
    with pytest.raises(ValueError, match='不支持任务类型'):
        validate_package(tmp_path)


def test_supported_package_declaration(tmp_path):
    (tmp_path / 'core.yaml').write_text('icl_tasks:\n- label: test\n  icl_task_type: multiple_choice\n  dataset_uri: test.jsonl\n  num_fewshot: [0]\n')
    (tmp_path / 'eval_data').mkdir()
    (tmp_path / 'eval_data/test.jsonl').write_text('{"query":"Q?","choices":["A","B"],"gold":0}\n')
    (tmp_path / 'eval_meta_data.csv').write_text('Eval Task,Random baseline\ntest,50\n')
    assert validate_package(tmp_path) == ['test']


def test_obs_package_without_builtin_creates_evaluation(tmp_path):
    manager = ModelArtsWorkflowManager(Path(__file__).resolve().parents[1], FakeClient())
    manager.directory = tmp_path
    body = config()
    body['evaluation'].update(datasets=[], obs_packages=[{'name': 'custom', 'obs_uri': 'obs://bucket/custom/'}])
    with patch.object(manager, '_start'):
        record = manager.create(body)
    assert len(record['jobs']) == 3
    payload = manager._payload(manager.records[record['id']], 'evaluation')
    package = next(x for x in payload['algorithm']['inputs'] if x['name'] == 'eval_package_0')
    assert package['remote']['obs']['obs_url'] == 'obs://bucket/custom/'
