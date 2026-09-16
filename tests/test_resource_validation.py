import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from auto_mixture_tool.modelarts.input_validation import validate_resource, validate_workflow_resources
from auto_mixture_tool.modelarts.evaluation_job import validate_package
from auto_mixture_tool.modelarts.command_preview import commands_for_settings

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples/evaluation/basic'


@pytest.fixture
def package(tmp_path, monkeypatch):
    monkeypatch.setenv('AMT_OBS_MOUNT_ROOT', str(tmp_path))
    monkeypatch.setenv('AMT_OBS_MOUNT_PREFIX', 'obs://bucket/prefix/')
    target = tmp_path / 'example'
    shutil.copytree(EXAMPLE, target)
    return target


def test_valid_example_reads_all_rows(package):
    result = validate_resource('evaluation', 'obs://bucket/prefix/example/')
    assert result['ready'] and result['tasks'] == ['science_example']


@pytest.mark.parametrize('row', [[], {}, {'query': 'Q', 'choices': ['A', 'B'], 'gold': 2},
                                 {'query': 'Q', 'choices': ['A', 'B'], 'gold': True},
                                 {'query': '', 'choices': ['A', 'B'], 'gold': 0}])
def test_bad_records_are_rejected(package, row):
    (package / 'eval_data/science.jsonl').write_text(json.dumps(row), encoding='utf-8')
    with pytest.raises(ValueError, match='不符合'):
        validate_package(package)


@pytest.mark.parametrize('kind', ['code_execution', 'image', 'audio', 'language_modeling'])
def test_unsupported_task_type_is_rejected(package, kind):
    path = package / 'core.yaml'
    path.write_text(path.read_text().replace('multiple_choice', kind))
    with pytest.raises(ValueError, match='不支持'):
        validate_package(package)


def test_traversal_missing_metadata_and_unreadable_mount_fail_closed(package):
    with pytest.raises(ValueError):
        validate_resource('evaluation', 'obs://other/prefix/example/')
    path = package / 'core.yaml'
    path.write_text(path.read_text().replace('science.jsonl', '../../secret.jsonl'))
    with pytest.raises(ValueError, match='越界'):
        validate_package(package)


def test_changed_package_is_rechecked_at_submission(package):
    config = {'reuse': {'stage': 'training'}, 'evaluation': {'obs_packages': [{'obs_uri': 'obs://bucket/prefix/example/'}]}}
    validate_workflow_resources(config)
    (package / 'eval_data/science.jsonl').write_text('broken')
    with pytest.raises(ValueError):
        validate_workflow_resources(config)


@pytest.mark.parametrize('extractor', ['gsm8k', 'math'])
def test_generation_package_contract(package, extractor):
    config = package / 'core.yaml'
    config.write_text(config.read_text().replace('multiple_choice', 'generation') + f'    answer_extractor: {extractor}\n')
    (package / 'eval_data/science.jsonl').write_text('{"query":"1+1?","answer":"2"}\n')
    assert validate_package(package) == ['science_example']


def test_query_string_uri_is_rejected(package):
    with pytest.raises(ValueError, match='有效'):
        validate_resource('evaluation', 'obs://bucket/prefix/example/?token=private')


def test_missing_baseline_fails(package):
    (package / 'eval_meta_data.csv').unlink()
    with pytest.raises(ValueError, match='eval_meta_data.csv'):
        validate_package(package)


def test_commands_change_with_mount_and_image_without_credentials():
    a = commands_for_settings({'image_url': 'image:a', 'offline_resources': [{'name': 'wheels', 'uri': 'obs://bucket/a/'}], 'authorization': 'secret'})
    b = commands_for_settings({'image_url': 'image:b', 'offline_resources': [{'name': 'wheels', 'uri': 'obs://bucket/b/'}]})
    assert a['training'] != b['training']
    assert 'secret' not in a['training']
    assert 'stage_runner training' in a['training']
    from auto_mixture_tool.modelarts.workflow import ModelArtsWorkflowManager
    assert a['training'].endswith(ModelArtsWorkflowManager._command('training'))


def test_invalid_resource_prevents_manager_client_submission(tmp_path, monkeypatch):
    from auto_mixture_tool.modelarts.workflow import ModelArtsWorkflowManager
    from test_modelarts_workflow import config, FakeClient
    monkeypatch.setenv('AMT_OBS_MOUNT_ROOT', str(tmp_path))
    client = FakeClient()
    manager = ModelArtsWorkflowManager(tmp_path, client)
    with patch.object(manager, '_start') as start:
        with pytest.raises(ValueError, match='不能提交'):
            manager.create(config())
        start.assert_not_called()
    assert client.submissions == []


def test_parquet_schema_and_values(tmp_path, monkeypatch):
    pa = pytest.importorskip('pyarrow')
    import pyarrow.parquet as pq
    from auto_mixture_tool.modelarts.input_validation import QUALITY
    monkeypatch.setenv('AMT_OBS_MOUNT_ROOT', str(tmp_path))
    monkeypatch.setenv('AMT_OBS_MOUNT_PREFIX', 'obs://bucket/prefix/')
    root = tmp_path / 'data'; root.mkdir()
    row = {'domain': '数学', 'text': 'test', 'char_count': 4, **{k: .5 for k in QUALITY}}
    pq.write_table(pa.Table.from_pylist([row]), root / 'part.parquet')
    assert validate_resource('dataset', 'obs://bucket/prefix/data/')['rows'] == 1
    row['knowledge_value'] = '0.5'
    pq.write_table(pa.Table.from_pylist([row]), root / 'part.parquet')
    with pytest.raises(ValueError, match='数据格式不符合算法要求'):
        validate_resource('dataset', 'obs://bucket/prefix/data/')
    row['knowledge_value'] = float('nan')
    pq.write_table(pa.Table.from_pylist([row]), root / 'part.parquet')
    with pytest.raises(ValueError, match='NaN'):
        validate_resource('dataset', 'obs://bucket/prefix/data/')


def test_volume_reads_length_column_beyond_content_sample(tmp_path):
    pa = pytest.importorskip('pyarrow')
    import pyarrow.parquet as pq
    from auto_mixture_tool.modelarts.input_validation import QUALITY, validate_parquet
    row = {'domain': '数学', 'text': 'test', 'char_count': 4, **{k: .5 for k in QUALITY}}
    rows = [row] * 1000 + [{**row, 'char_count': 400}]
    pq.write_table(pa.Table.from_pylist(rows), tmp_path / 'part.parquet')
    result = validate_parquet(tmp_path)
    assert result['rows'] == 1001 and result['checked_rows'] == 1000
    assert result['total_chars'] == 4400 and result['estimated_tokens'] == 1100
    assert result['token_is_estimate'] is True
    assert result['size_bytes'] == (tmp_path / 'part.parquet').stat().st_size
    rows[-1] = {**row, 'char_count': -1}
    pq.write_table(pa.Table.from_pylist(rows), tmp_path / 'part.parquet')
    with pytest.raises(ValueError, match='char_count'):
        validate_parquet(tmp_path)
