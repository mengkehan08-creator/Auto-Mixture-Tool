import copy
import json
from unittest.mock import patch

import pytest

from auto_mixture_tool.modelarts.result_analysis import analyze_report, read_report, workflow_analysis


def report():
    identity = {'framework': 'nanochat', 'format': 'nanochat-checkpoint-v1',
                'model_config': dict(n_layer=24, n_embd=128, n_head=8, vocab_size=100, sequence_len=1024),
                'tokenizer_sha256': 'a' * 64, 'base_weights_sha256': 'b' * 64}
    return {'models': [
        {'id': name, 'name': name, 'comparison_identity': identity,
         'training_config': {'token_budget': 1000, 'num_iterations': 0, 'target_param_data_ratio': 0.5},
         'metrics': [{'Task ': 'math ', 'Accuracy ': str(a), 'Centered': '-0.1'},
                     {'Task': 'arc', 'Accuracy': str(b)},
                     {'Task': 'STEM', 'Accuracy': '', 'Centered': '0.99'}]}
        for name, a, b in [('QuadMix', 0.8, 0.6), ('Random', 0.6, 0.6)]]}


def record():
    return {'id': 'a' * 12, 'name': '实验', 'jobs': [{'module': 'evaluation', 'status': 'SUCCEEDED'}],
            'config': {'evaluation': {'datasets': ['stem']}}, 'outputs': {'reports': 'obs://bucket/results/'}}


def test_common_mean_excludes_official_aggregate_and_uses_percentage_points():
    result = analyze_report(report())
    assert result['common_tasks'] == ['arc', 'math']
    assert result['models'][0]['mean_accuracy'] == pytest.approx(0.7)
    assert result['models'][0]['aggregates']['STEM']['centered'] == .99
    assert result['models'][0]['metrics']['math']['centered'] == -.1
    assert any('10.00 个百分点' in line for line in result['conclusions'])
    assert any('并列最高：arc' in line for line in result['conclusions'])
    assert any('最大相对落后项为 math，低 20.00' in line for line in result['conclusions'])
    assert not any('同' in line and 'num_iterations' in line for line in result['warnings'])


@pytest.mark.parametrize('value', ['', 'nan', 'Infinity', True, '1.1', '-0.2', None])
def test_invalid_and_missing_scores_never_become_zero(value):
    data = report()
    data['models'][1]['metrics'][0]['Accuracy '] = value
    result = analyze_report(data)
    assert result['common_tasks'] == ['arc']
    assert result['models'][1]['metrics']['math']['accuracy'] is None
    assert all(model['mean_accuracy'] == .6 for model in result['models'])
    assert any('并列最高' in line for line in result['conclusions'])


def test_no_shared_tasks_and_single_model_do_not_claim_winner():
    data = report()
    data['models'][1]['metrics'] = [{'Task': 'other', 'Accuracy': '0.5'}]
    result = analyze_report(data)
    assert not result['common_tasks']
    assert all(m['mean_accuracy'] is None for m in result['models'])
    assert '无法' in result['conclusions'][0]
    data['models'] = data['models'][:1]
    assert '不能' in analyze_report(data)['conclusions'][0]


def test_duplicate_task_and_empty_models_rejected():
    data = report()
    data['models'][0]['metrics'].append({'Task': 'math', 'Accuracy': '0.9'})
    with pytest.raises(ValueError, match='重复'):
        analyze_report(data)
    with pytest.raises(ValueError, match='模型列表'):
        analyze_report({'models': []})


def test_different_training_budget_flagged_but_nodes_not_model_difference():
    data = copy.deepcopy(report())
    data['models'][0]['training_config']['nodes'] = 2
    data['models'][1]['training_config']['nodes'] = 4
    result = analyze_report(data)
    assert not any('nodes' in item for item in result['warnings'])
    data['models'][1]['training_config']['token_budget'] = 2000
    assert any('训练 Token 预算不同' in item for item in analyze_report(data)['warnings'])


def test_historical_models_and_sampling_stats_preserve_identity():
    data = report()
    data['models'][0].update(catalog_id='history:a', source_workflow_id='a' * 12)
    data['dataset_stats'] = {'history:a': {'quadmix': {'tokens': 123, 'domain_ratios': {'数学': .7}}}}
    model = analyze_report(data)['models'][0]
    assert model['source_workflow_id'] == 'a' * 12
    assert model['sampling']['domain_ratios']['数学'] == .7


def test_pending_evaluation_does_not_read_obs():
    data = record()
    data['jobs'][0]['status'] = 'FAILED'
    with patch('auto_mixture_tool.modelarts.result_analysis.read_report') as read:
        assert workflow_analysis(data)['status'] == 'pending'
        read.assert_not_called()


def test_custom_packages_are_separate_and_partial_failures_visible():
    data = record()
    data['config']['evaluation']['obs_packages'] = [{'name': '自定义', 'obs_uri': 'obs://bucket/eval/'}]
    seen = []
    def read(uri):
        seen.append(uri)
        if '/package_0/' in uri:
            raise ValueError('report missing')
        return report()
    result = workflow_analysis(data, read)
    assert seen == ['obs://bucket/results/builtin/comparison_report.json', 'obs://bucket/results/package_0/comparison_report.json']
    assert result['status'] == 'partial'
    assert len(result['reports']) == 1
    assert result['errors'][0]['name'] == '自定义'


def test_read_report_from_mount_and_reject_untrusted_paths(tmp_path, monkeypatch):
    monkeypatch.setenv('AMT_OBS_MOUNT_ROOT', str(tmp_path))
    monkeypatch.setenv('AMT_OBS_MOUNT_PREFIX', 'obs://bucket/results/')
    (tmp_path / 'comparison_report.json').write_text(json.dumps(report()), encoding='utf-8')
    assert read_report('obs://bucket/results/comparison_report.json')['models']
    for uri in ['http://localhost/comparison_report.json', 'obs://bucket/results/model.pt',
                'obs://bucket/results/%2e%2e/comparison_report.json', 'obs://bucket/results/comparison_report.json?token=secret']:
        with pytest.raises(ValueError):
            read_report(uri)
    (tmp_path / 'comparison_report.json').write_text('broken')
    with pytest.raises(ValueError, match='JSON'):
        read_report('obs://bucket/results/comparison_report.json')


def test_oversized_report_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv('AMT_OBS_MOUNT_ROOT', str(tmp_path))
    monkeypatch.setenv('AMT_OBS_MOUNT_PREFIX', 'obs://bucket/results/')
    with (tmp_path / 'comparison_report.json').open('wb') as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match='8 MiB'):
        read_report('obs://bucket/results/comparison_report.json')


def test_nonfinite_json_and_bad_comparability_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv('AMT_OBS_MOUNT_ROOT', str(tmp_path))
    monkeypatch.setenv('AMT_OBS_MOUNT_PREFIX', 'obs://bucket/results/')
    (tmp_path / 'comparison_report.json').write_text('{"bad": NaN}')
    with pytest.raises(ValueError, match='JSON'):
        read_report('obs://bucket/results/comparison_report.json')
    data = report()
    data['comparability'] = [{'warnings': 'not a list'}]
    with pytest.raises(ValueError, match='可比性'):
        analyze_report(data)


def test_analysis_endpoint_reads_only_saved_record():
    from fastapi import HTTPException
    from auto_mixture_tool.api import server
    data = record()
    from types import SimpleNamespace
    manager = SimpleNamespace(get=lambda id: data, records={data['id']: data})
    with patch.object(server, '_workflow_manager', return_value=manager), \
         patch('auto_mixture_tool.modelarts.result_analysis.read_report', return_value=report()):
        result = server.result_analysis(data['id'])
        assert result['status'] == 'ready'
        assert 'config' not in result
    def missing(id):
        raise ValueError('workflow not found')
    manager.get = missing
    with patch.object(server, '_workflow_manager', return_value=manager), pytest.raises(HTTPException) as error:
        server.result_analysis('missing')
    assert error.value.status_code == 404
