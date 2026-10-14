from pathlib import Path
from unittest.mock import patch

import pytest
pytestmark = pytest.mark.usefixtures('mock_resource_preflight')

from auto_mixture_tool.modelarts.evaluation_job import publish_models, validate_models
from auto_mixture_tool.modelarts.workflow import ModelArtsWorkflowManager
from test_modelarts_workflow import config, FakeClient


@pytest.mark.parametrize('automatic', [False, True])
def test_no_evaluation_creates_only_two_jobs(tmp_path, automatic):
    manager = ModelArtsWorkflowManager(Path(__file__).resolve().parents[1], FakeClient())
    manager.directory = tmp_path
    body = config()
    body['evaluation']['datasets'] = []
    body['evaluation']['automatic_api_requested'] = automatic
    with patch.object(manager, '_start'):
        record = manager.create(body)
    assert [job['module'] for job in record['jobs']] == ['mixing', 'training']


def test_legacy_record_does_not_add_evaluation(tmp_path):
    manager = ModelArtsWorkflowManager(Path(__file__).resolve().parents[1], FakeClient())
    manager.directory = tmp_path
    with patch.object(manager, '_start'):
        created = manager.create(config())
    record = manager.records[created['id']]
    record.pop('pipeline_version')
    record['jobs'] = record['jobs'][:2]
    calls = []
    with patch.object(manager, '_submit_and_wait', side_effect=lambda r, i, stage, *a: calls.append(stage) or True):
        manager._run(record['id'])
    assert calls == ['mixing', 'training']


def test_model_handoff_checks_contents(tmp_path, monkeypatch):
    monkeypatch.setenv('AMT_RUN_ID', 'run-test')
    body = config()
    body['strategies'] = [{'id': 'random', 'type': 'random'}]
    folder = tmp_path / 'd24_stem_random_run-test'
    folder.mkdir()
    (folder / 'model_000015.pt').write_bytes(b'model')
    (folder / 'meta_000015.json').write_text('{}')
    (tmp_path / 'dataset_stats.json').write_text('{}')
    publish_models(body, tmp_path, tmp_path)
    assert validate_models(tmp_path)['models'][0]['step'] == 15
    (folder / 'model_000015.pt').write_bytes(b'broken')
    with pytest.raises(ValueError, match='校验失败'):
        validate_models(tmp_path)


def test_missing_checkpoint_does_not_publish_manifest(tmp_path, monkeypatch):
    monkeypatch.setenv('AMT_RUN_ID', 'run-test')
    with pytest.raises(ValueError, match='训练输出不完整'):
        publish_models(config(), tmp_path, tmp_path)
    assert not (tmp_path / 'models_manifest.json').exists()


def test_evaluation_mount_is_training_output(tmp_path):
    manager = ModelArtsWorkflowManager(Path(__file__).resolve().parents[1], FakeClient())
    manager.directory = tmp_path
    body = config()
    body['evaluation_nodes'] = 4
    body['training']['output_obs_uri'] = 'obs://models/custom/'
    with patch.object(manager, '_start'):
        record = manager.create(body)
    payload = manager._payload(manager.records[record['id']], 'evaluation')
    assert payload['spec']['resource']['node_count'] == 4
    mounted = next(x for x in payload['algorithm']['inputs'] if x['name'] == 'trained_models')
    assert mounted['remote']['obs']['obs_url'] == record['outputs']['models']


def test_training_failure_blocks_evaluation(tmp_path):
    manager = ModelArtsWorkflowManager(Path(__file__).resolve().parents[1], FakeClient())
    manager.directory = tmp_path
    with patch.object(manager, '_start'):
        created = manager.create(config())
    calls = []
    def wait(record, index, stage, *args):
        calls.append(stage)
        return stage != 'training'
    with patch.object(manager, '_submit_and_wait', side_effect=wait):
        manager._run(created['id'])
    assert calls == ['mixing', 'training']


@pytest.mark.parametrize('field,value', [('devices_per_node', 9), ('core_eval_batch_size', 0), ('max_per_task', 0)])
def test_invalid_evaluation_parameters(tmp_path, field, value):
    body = config()
    body['evaluation'][field] = value
    with pytest.raises(ValueError, match='评测参数'):
        ModelArtsWorkflowManager(tmp_path, FakeClient())._validate(body)


def test_report_keeps_each_models_actual_batch_history(tmp_path, monkeypatch):
    import json
    import sys
    from types import ModuleType
    from auto_mixture_tool.modelarts import evaluation_job
    runner = ModuleType('auto_mixture_tool.modelarts.stage_runner')
    runner.OUTPUT, runner.WORKSPACE = tmp_path / 'output', tmp_path
    monkeypatch.setitem(sys.modules, runner.__name__, runner)
    monkeypatch.setenv('MA_NUM_HOSTS', '1')
    monkeypatch.setenv('VC_TASK_INDEX', '0')
    models = [{'id': f'm{i}', 'name': f'model{i}', 'model_tag': f'm{i}', 'step': 1,
               '_root': str(tmp_path / f'weights{i}'), '_tokenizer': str(tmp_path / 'tokenizer')}
              for i in range(2)]
    manifest = {'run': 'test', 'models': models, 'dataset_stats': {}}
    def evaluate(command, cwd, env, check):
        base = Path(env['NANOCHAT_BASE_DIR']) / 'base_eval'
        base.mkdir(exist_ok=True)
        log = base / 'adaptive_batch.jsonl'
        assert not log.exists(), 'previous model history leaked'
        log.write_text(json.dumps({'task': 'test', 'final_batch_size': 12}) + '\n')
        (base / 'mid_model_000001.csv').write_text('Task,Accuracy,Centered\ntest,0.5,0.5\n')
    body = {'evaluation': {'datasets': ['test']}}
    with patch.object(evaluation_job, 'evaluation_models', return_value=manifest), \
         patch.object(evaluation_job.subprocess, 'run', side_effect=evaluate), \
         patch.object(Path, 'symlink_to'), \
         patch('nanochat_mid_compare.prepare_offline_eval_bundle.materialize'):
        evaluation_job._run_evaluation(body, tmp_path / 'bundle', None)
    folder = runner.OUTPUT / 'training/results'
    report = json.loads((folder / 'comparison_report.json').read_text(encoding='utf-8'))
    assert all(model['adaptive_batch'] == [{'task': 'test', 'final_batch_size': 12}] for model in report['models'])
    assert (folder / 'm0_adaptive_batch.jsonl').exists()
    assert (folder / 'm1_adaptive_batch.jsonl').exists()
