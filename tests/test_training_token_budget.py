from pathlib import Path
from unittest.mock import patch

import pytest

from auto_mixture_tool.modelarts.workflow import ModelArtsWorkflowManager
from auto_mixture_tool.modelarts import stage_runner
from test_modelarts_workflow import config, FakeClient


@pytest.mark.parametrize('budget', [0, -1, True, 1.5, '', '100', 9007199254740992])
def test_invalid_budget_rejected(tmp_path, budget):
    body = config()
    body['training']['token_budget'] = budget
    with pytest.raises(ValueError, match='Token'):
        ModelArtsWorkflowManager(tmp_path, FakeClient())._validate(body)


def test_budget_rejects_fixed_steps(tmp_path):
    body = config()
    body['training'].update(token_budget=401395843, num_iterations=1200)
    with pytest.raises(ValueError, match='不能同时'):
        ModelArtsWorkflowManager(tmp_path, FakeClient())._validate(body)


def test_budget_reaches_training_process(tmp_path):
    body = config()
    body['strategies'] = [{'id': 'random', 'type': 'random', 'name': 'Random'}]
    body['training']['token_budget'] = 401395843
    data = tmp_path / 'random_data'
    data.mkdir()
    (data / 'part.parquet').touch()
    with patch.object(stage_runner, '_prepared_data_dir', return_value=tmp_path), \
            patch.object(stage_runner.subprocess, 'run') as run:
        stage_runner.run_training(body)
    assert run.call_args.kwargs['env']['TRAIN_TOKEN_BUDGET'] == '401395843'
    assert run.call_args.kwargs['env']['TRAIN_NUM_ITERATIONS'] == '0'


def test_budget_override_precedes_step_calculation():
    script = (Path(__file__).resolve().parents[1] /
              'nanochat_mid_compare/run_stem_experiment.sh').read_text(encoding='utf-8')
    assert script.index('TRAIN_BUDGET="$TRAIN_TOKEN_BUDGET"') < script.index('run_mid_training "$QUADMIX_DATA"')
    assert '--tokens "$TRAIN_TOKENS" --steps "$TRAIN_NUM_ITERATIONS"' in script


@pytest.mark.parametrize('batch', [0, -1, True, 1.5, '', '100', 9007199254740992])
def test_invalid_global_batch_rejected(tmp_path, batch):
    body = config()
    body['training']['total_batch_size'] = batch
    with pytest.raises(ValueError, match='batch'):
        ModelArtsWorkflowManager(tmp_path, FakeClient())._validate(body)


def test_global_batch_reaches_both_training_adapters(tmp_path):
    from auto_mixture_tool.core.nanochat_trainer import NanoChatTrainer as CoreTrainer
    from auto_mixture_tool.plugins.trainers.nanochat import NanoChatTrainer
    body = config()
    body['strategies'] = [{'id': 'random', 'type': 'random'}]
    body['training']['total_batch_size'] = 540672
    data = tmp_path / 'random_data'
    data.mkdir()
    (data / 'part.parquet').touch()
    with patch.object(stage_runner, '_prepared_data_dir', return_value=tmp_path), patch.object(stage_runner.subprocess, 'run') as run:
        stage_runner.run_training(body)
    assert run.call_args.kwargs['env']['TRAIN_TOTAL_BATCH_SIZE'] == '540672'
    command = NanoChatTrainer().build({'job_id': 'test', 'dataset_uri': '/data', 'schema_uri': '/schema',
                                      'trainer_config': {'total_batch_size': 540672, 'token_budget': 1000000}}, tmp_path)[0]
    assert command.env['TRAIN_TOTAL_BATCH_SIZE'] == '540672'
    assert command.env['TRAIN_TOKEN_BUDGET'] == '1000000'
    core = CoreTrainer(total_batch_size=540672, token_budget=1000000)
    env = core._build_env(tmp_path / 'data.jsonl', tmp_path, tmp_path)
    assert env['TRAIN_TOTAL_BATCH_SIZE'] == '540672'
    assert env['TRAIN_TOKEN_BUDGET'] == '1000000'
    assert env['NANOCHAT_LOAD_OPTIMIZER'] == '0'
