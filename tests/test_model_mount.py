import json
import sys

import pytest

from auto_mixture_tool.modelarts import model_comparison as comparison
from test_model_comparison import identity


@pytest.fixture
def mount(tmp_path, monkeypatch):
    monkeypatch.setenv('AMT_OBS_MOUNT_ROOT', str(tmp_path))
    monkeypatch.setenv('AMT_OBS_MOUNT_PREFIX', comparison.DEFAULT_OBS_PREFIX)
    monkeypatch.setitem(sys.modules, 'moxing', None)
    return tmp_path


def test_read_local_mount_without_moxing(mount):
    folder = mount / 'chengchao/run'
    folder.mkdir(parents=True)
    data = {'version': 1, 'models': []}
    (folder / 'models_manifest.json').write_text(json.dumps(data))
    uri = comparison.DEFAULT_OBS_PREFIX + 'chengchao/run/models_manifest.json'
    assert comparison.read_metadata(uri) == data
    assert comparison.mounted_metadata_path(uri) == folder / 'models_manifest.json'


def test_custom_mapping_and_prefix_boundary(mount, monkeypatch):
    monkeypatch.setenv('AMT_OBS_MOUNT_PREFIX', 'obs://other-bucket/model-root/')
    assert comparison.mounted_metadata_path('obs://other-bucket/model-root/models_manifest.json') == mount / 'models_manifest.json'
    assert comparison.mounted_metadata_path('obs://other-bucket/model-root-old/models_manifest.json') is None
    assert comparison.mounted_metadata_path('obs://another-bucket/model-root/models_manifest.json') is None
    monkeypatch.setenv('AMT_OBS_MOUNT_ROOT', '')
    assert comparison.mounted_metadata_path('obs://other-bucket/model-root/models_manifest.json') is None


@pytest.mark.parametrize('suffix', ['../models_manifest.json', '%2e%2e/models_manifest.json',
                                   'sub/%2e%2e/models_manifest.json', '%5csecret/models_manifest.json',
                                   'C:/models_manifest.json'])
def test_mount_rejects_path_escape(mount, suffix):
    with pytest.raises(ValueError):
        comparison.read_metadata(comparison.DEFAULT_OBS_PREFIX + suffix)


def test_mount_rejects_resolved_symlink_escape(mount, tmp_path_factory):
    outside = tmp_path_factory.mktemp('outside-mount')
    (outside / 'models_manifest.json').write_text('{"version":1}')
    try:
        (mount / 'link').symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip('This host does not permit directory symlinks')
    with pytest.raises(ValueError, match='不能超出'):
        comparison.read_metadata(comparison.DEFAULT_OBS_PREFIX + 'link/models_manifest.json')


def test_local_missing_or_invalid_manifest_does_not_fall_back_to_network(mount):
    uri = comparison.DEFAULT_OBS_PREFIX + 'models_manifest.json'
    with pytest.raises(ValueError, match='挂载目录未找到'):
        comparison.read_metadata(uri)
    path = mount / 'models_manifest.json'
    for raw in ('invalid', '{"version":2}', 'x' * (comparison.MAX_METADATA_BYTES + 1)):
        path.write_text(raw)
        with pytest.raises(ValueError, match='挂载目录模型清单读取失败'):
            comparison.read_metadata(uri)


def test_identical_saved_parameters_do_not_differ_when_metadata_is_missing(mount):
    training = {'framework': 'nanochat', 'base_model_tag': 'd24', 'token_budget': 100, 'nodes': 2}
    catalog = [{'id': 'run:random', 'name': '历史模型', 'strategy_id': 'random', 'framework': 'nanochat',
                'obs_uri': comparison.DEFAULT_OBS_PREFIX + 'result', 'training_config': {**training, 'nodes': 8}}]
    reference = {'model_obs_uri': comparison.DEFAULT_OBS_PREFIX + 'base', 'base_model_tag': 'd24',
                 'training_configs': [training]}
    check = comparison.compare_catalog(catalog, reference)[0]['comparison']
    assert check['status'] == 'compatible'
    assert check['reasons'] == []
    assert '未核验' in check['metadata_notice']
    assert len([w for w in check['warnings'] if '挂载目录未找到' in w]) == 1
    rows = {row['key']: row for row in check['parameters']}
    assert rows['framework']['same']
    assert rows['training.0.token_budget']['same']
    assert rows['tokenizer_sha256']['missing']
    assert not any('MoXing' in w for w in check['warnings'])
    catalog[0]['training_config']['token_budget'] = 200
    assert comparison.compare_catalog(catalog, reference)[0]['comparison']['status'] == 'different'


def test_mounted_manifests_enrich_and_expose_real_difference(mount):
    (mount / 'base').mkdir()
    (mount / 'result').mkdir()
    (mount / 'base/model_identity_d24.json').write_text(json.dumps({'version': 1, 'identity': identity()}))
    candidate = identity()
    candidate['model_config']['n_layer'] = 12
    (mount / 'result/models_manifest.json').write_text(json.dumps({'version': 1, 'models': [{'id': 'random', 'comparison_identity': candidate}]}))
    catalog = [{'id': 'run:random', 'name': '模型', 'strategy_id': 'random', 'framework': 'nanochat',
                'obs_uri': comparison.DEFAULT_OBS_PREFIX + 'result', 'training_config': {'token_budget': 100}}]
    reference = {'model_obs_uri': comparison.DEFAULT_OBS_PREFIX + 'base', 'base_model_tag': 'd24',
                 'training_configs': [{'token_budget': 100}]}
    check = comparison.compare_catalog(catalog, reference)[0]['comparison']
    assert check['status'] == 'different'
    assert check['metadata_notice'] == ''
    assert '模型结构 · n_layer不同' in check['reasons']
