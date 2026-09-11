import copy
import io
import json
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from auto_mixture_tool.modelarts import model_comparison as comparison
from auto_mixture_tool.modelarts.evaluation_job import validate_comparison_models


def identity():
    return {'framework': 'nanochat', 'format': 'nanochat-checkpoint-v1',
            'model_config': {'n_layer': 24, 'n_embd': 1536, 'n_head': 12, 'vocab_size': 32768, 'sequence_len': 2048},
            'tokenizer_sha256': 'a' * 64, 'base_weights_sha256': 'b' * 64}


def test_same_type_requires_evidence_not_tag_or_path():
    assert comparison.compare_identity(identity(), identity())['status'] == 'compatible'
    for field in identity():
        changed = identity()
        changed.pop(field)
        assert comparison.compare_identity(identity(), changed)['status'] == 'unknown'
    for field, value in [('framework', 'custom'), ('tokenizer_sha256', 'c' * 64),
                         ('base_weights_sha256', 'c' * 64), ('format', 'huggingface')]:
        changed = {**identity(), field: value}
        assert comparison.compare_identity(identity(), changed)['status'] == 'incompatible'
    changed = identity()
    changed['model_config']['n_layer'] = 12
    assert comparison.compare_identity(identity(), changed)['status'] == 'incompatible'
    changed['model_config'] = {'n_layer': 24}
    assert comparison.compare_identity(identity(), changed)['status'] == 'unknown'


def test_local_fingerprints_are_deterministic_and_detect_changes(tmp_path):
    weights = tmp_path / 'base_checkpoints/d24'
    weights.mkdir(parents=True)
    (weights / 'model_000001.pt').write_bytes(b'initial weights')
    (weights / 'meta_000001.json').write_text(json.dumps({'model_config': identity()['model_config']}))
    tokenizer = tmp_path / 'tokenizer'
    tokenizer.mkdir()
    (tokenizer / 'tokenizer.pkl').write_bytes(b'tokens')
    original = comparison.build_identity(tmp_path, 'd24')
    assert original == comparison.build_identity(tmp_path, 'd24')
    assert comparison.compare_identity(original, original)['status'] == 'compatible'
    (weights / 'model_000001.pt').write_bytes(b'different weights')
    assert comparison.build_identity(tmp_path, 'd24')['base_weights_sha256'] != original['base_weights_sha256']
    (tokenizer / 'tokenizer.pkl').write_bytes(b'different tokenizer')
    assert comparison.build_identity(tmp_path, 'd24')['tokenizer_sha256'] != original['tokenizer_sha256']
    with pytest.raises(ValueError):
        comparison.build_identity(tmp_path, '../d24')


@pytest.mark.parametrize('uri', ['https://bucket/models_manifest.json', 'obs://bucket/model.pt',
                                'obs://bucket/../models_manifest.json', 'obs://bucket/%2e%2e/models_manifest.json',
                                'obs://bucket/models_manifest.json?secret=value'])
def test_only_obs_metadata_paths_are_accepted(uri):
    with pytest.raises(ValueError, match='只允许读取'):
        comparison.read_metadata(uri)


def test_obs_read_is_bounded_and_errors_do_not_leak_credentials(monkeypatch):
    raw = b'{"version":1}'
    storage = SimpleNamespace(get_size=lambda uri: len(raw), File=lambda *args: io.BytesIO(raw))
    monkeypatch.setitem(sys.modules, 'moxing', SimpleNamespace(file=storage))
    assert comparison.read_metadata('obs://bucket/models_manifest.json') == {'version': 1}
    storage.get_size = lambda uri: comparison.MAX_METADATA_BYTES + 1
    with pytest.raises(ValueError, match='1 MiB'):
        comparison.read_metadata('obs://bucket/models_manifest.json')
    def failure(uri):
        raise RuntimeError('secret=sensitive-credential')
    storage.get_size = failure
    with pytest.raises(ValueError) as error:
        comparison.read_metadata('obs://bucket/models_manifest.json')
    assert 'sensitive' not in str(error.value)


def records():
    return [{'id': 'run:random', 'strategy_id': 'random', 'name': '历史随机模型', 'framework': 'nanochat',
             'obs_uri': 'obs://bucket/models', 'input_data_obs_uri': 'obs://bucket/data',
             'training_config': {'token_budget': 100}}]


def reference():
    return {'model_obs_uri': 'obs://bucket/base', 'base_model_tag': 'd24',
            'training_configs': [{'token_budget': 200}], 'input_data_obs_uri': 'obs://bucket/data'}


def test_catalog_reads_only_metadata_and_deduplicates_sources():
    calls = []
    def reader(uri):
        calls.append(uri)
        return {'version': 1, 'identity': identity(), 'models': [{'id': 'random', 'comparison_identity': identity()}]}
    checked = comparison.compare_catalog(records() * 2, reference(), reader)
    assert len(calls) == 2
    assert all(uri.endswith('.json') for uri in calls)
    assert checked[0]['comparison']['status'] == 'different'
    assert '训练 Token 预算不同' in checked[0]['comparison']['warnings']
    assert records()[0].get('comparison') is None


@pytest.mark.parametrize('manifest', [{}, {'models': 42}, {'models': [{'id': 'random'}]},
                                    {'models': [{'id': 'random', 'comparison_identity': 'bad'}]}])
def test_legacy_or_malformed_manifest_is_different(manifest):
    checked = comparison.compare_catalog(records(), reference(), lambda uri: manifest)
    assert checked[0]['comparison']['status'] == 'different'


def test_unreadable_obs_is_different():
    def reader(uri):
        raise ValueError('OBS 只读权限不足')
    result = comparison.compare_catalog(records(), reference(), reader)[0]['comparison']
    assert result['status'] == 'different'
    assert 'OBS 只读权限不足' in result['reasons']


def test_submission_rechecks_even_without_client_policy(monkeypatch):
    config = {'evaluation': {'model_ids': ['run:random']},
              'resources': {'nanochat_model_obs_uri': reference()['model_obs_uri']},
              'training': {'base_model_tag': 'd24'}, 'strategies': [{'training': {'token_budget': 200}}],
              'input_data_obs_uri': reference()['input_data_obs_uri']}
    catalog = {model['id']: model for model in records()}
    data = {'version': 1, 'identity': identity(), 'models': [{'id': 'random', 'comparison_identity': identity()}]}
    monkeypatch.setattr(comparison, 'read_metadata', lambda uri: data)
    comparison.validate_selection(config, catalog)
    assert config['evaluation']['comparison_policy'] == 'allow-differences'
    assert config['evaluation']['model_comparison'][0]['status'] == 'different'
    data['models'][0]['comparison_identity']['tokenizer_sha256'] = 'c' * 64
    comparison.validate_selection(config, catalog)
    assert 'Tokenizer 指纹不同' in config['evaluation']['model_comparison'][0]['reasons']
    assert 'parameters' not in config['evaluation']['model_comparison'][0]


def test_evaluation_rechecks_actual_tokenizer(tmp_path):
    (tmp_path / 'tokenizer.pkl').write_bytes(b'actual')
    actual = identity()
    actual['tokenizer_sha256'] = comparison.directory_digest(tmp_path, [tmp_path / 'tokenizer.pkl'])
    model_root = tmp_path / 'model'
    (model_root / 'test').mkdir(parents=True)
    meta = model_root / 'test/meta_000001.json'
    meta.write_text(json.dumps({'model_config': actual['model_config']}))
    model = {'name': 'test', '_tokenizer': str(tmp_path), 'model_config': actual['model_config'], 'comparison_identity': actual,
             '_root': str(model_root), 'model_tag': 'test', 'step': 1, 'files': [{'path': 'test/meta_000001.json'}]}
    # The tokenizer mount contains only tokenizer files, separate from checkpoint files.
    tokenizer = tmp_path / 'tokens'
    tokenizer.mkdir()
    (tmp_path / 'tokenizer.pkl').rename(tokenizer / 'tokenizer.pkl')
    model['_tokenizer'] = str(tokenizer)
    validate_comparison_models([model, copy.deepcopy(model)])
    mismatch = copy.deepcopy(model)
    mismatch['comparison_identity']['base_weights_sha256'] = 'c' * 64
    with pytest.raises(ValueError, match='基础权重'):
        validate_comparison_models([model, mismatch])
    validate_comparison_models([model, mismatch], allow_differences=True)
    legacy = copy.deepcopy(model)
    legacy.pop('comparison_identity')
    legacy.pop('model_config')
    validate_comparison_models([legacy], allow_differences=True)
    (tokenizer / 'tokenizer.pkl').write_bytes(b'replaced')
    with pytest.raises(ValueError, match='Tokenizer'):
        validate_comparison_models([model])
    with pytest.raises(ValueError, match='Tokenizer'):
        validate_comparison_models([model], allow_differences=True)
    meta.write_text(json.dumps({'model_config': {'n_layer': 3}}))
    with pytest.raises(ValueError, match='实际结构'):
        validate_comparison_models([model])


def test_training_manifest_contains_local_identity_and_final_metadata(tmp_path, monkeypatch):
    from auto_mixture_tool.modelarts.evaluation_job import publish_models
    monkeypatch.setenv('AMT_RUN_ID', 'test')
    folder = tmp_path / 'd24_stem_random_test'
    folder.mkdir()
    (folder / 'model_000015.pt').write_bytes(b'model')
    (folder / 'meta_000015.json').write_text(json.dumps({'model_config': identity()['model_config']}))
    (tmp_path / 'dataset_stats.json').write_text('{}')
    publish_models({'training': {'base_model_tag': 'd24'}, 'strategies': [{'id': 'random', 'type': 'random'}]}, tmp_path, tmp_path, identity())
    manifest = json.loads((tmp_path / 'models_manifest.json').read_text())
    assert manifest['models'][0]['comparison_identity'] == identity()
    assert manifest['models'][0]['step'] == 15


def test_compare_api_returns_status_without_submitting_jobs():
    from fastapi.testclient import TestClient
    from auto_mixture_tool.api.server import app
    with patch('auto_mixture_tool.api.server._workflow_manager'), \
         patch('auto_mixture_tool.modelarts.parallel_workflow.models', return_value=records()), \
         patch.object(comparison, 'read_metadata', return_value={'version': 1}):
        response = TestClient(app).post('/api/v1/models/compare', json=reference())
    assert response.status_code == 200
    assert response.json()[0]['comparison']['status'] == 'different'


def test_parameter_rows_ignore_nodes_and_show_real_differences():
    reference_training = {'nodes': 2, 'token_budget': 100, 'device_batch_size': 1, 'output_obs_uri': 'obs://bucket/new'}
    candidate_training = {**reference_training, 'nodes': 8, 'output_obs_uri': 'obs://bucket/old'}
    rows = comparison.parameter_rows(identity(), identity(), [reference_training], candidate_training)
    assert all(row['same'] for row in rows)
    assert not any(row['key'].endswith(('.nodes', '.output_obs_uri')) for row in rows)
    candidate_training['token_budget'] = 200
    candidate = identity()
    candidate['model_config']['n_layer'] = 12
    rows = comparison.parameter_rows(identity(), candidate, [reference_training], candidate_training)
    differences = {row['key'] for row in rows if not row['same']}
    assert differences == {'model_config.n_layer', 'training.0.token_budget'}
    rows = comparison.parameter_rows({}, {}, [{}], {})
    assert all(row['missing'] and not row['same'] for row in rows)


def test_only_node_change_keeps_same_type():
    ref = reference()
    ref['training_configs'] = [{'token_budget': 100, 'nodes': 2}]
    history = records()
    history[0]['nodes'] = 8
    history[0]['training_config']['nodes'] = 8
    reader = lambda uri: {'version': 1, 'identity': identity(), 'models': [{'id': 'random', 'comparison_identity': identity()}]}
    assert comparison.compare_catalog(history, ref, reader)[0]['comparison']['status'] == 'compatible'
    history[0]['training_config']['token_budget'] = 200
    assert comparison.compare_catalog(history, ref, reader)[0]['comparison']['status'] == 'different'
