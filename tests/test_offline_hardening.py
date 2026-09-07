import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nanochat_mid_compare.eval_assets import validate_assets, task_definitions
from auto_mixture_tool.modelarts.workflow import ModelArtsWorkflowManager


def assets(tmp_path):
    root = tmp_path / 'eval_bundle'
    (root / 'eval_data').mkdir(parents=True)
    (root / 'core.yaml').write_text('icl_tasks:\n  - label: arc_easy\n    dataset_uri: arc.jsonl\n', encoding='utf-8')
    (root / 'eval_meta_data.csv').write_text('Eval Task,Random baseline\narc_easy,25\n', encoding='utf-8')
    (root / 'eval_data/arc.jsonl').write_text('{"question":"q"}\n', encoding='utf-8')
    return root


def test_selected_eval_assets_checked_before_training(tmp_path):
    root = assets(tmp_path)
    assert validate_assets(tmp_path, 'arc_easy', [], []) == ['arc_easy']
    (root / 'eval_data/arc.jsonl').unlink()
    with pytest.raises(ValueError, match='arc_easy'):
        validate_assets(tmp_path, 'arc_easy', [], [])


def test_stem_task_missing_is_not_silently_skipped(tmp_path):
    assets(tmp_path)
    with pytest.raises(ValueError, match='gsm8k'):
        validate_assets(tmp_path, 'stem', [{'label': 'gsm8k_cot', 'dataset_uri': 'gsm8k.jsonl'}], ['arc_easy', 'gsm8k_cot'])


def test_malformed_jsonl_and_unknown_labels(tmp_path):
    root = assets(tmp_path)
    (root / 'eval_data/arc.jsonl').write_text('not json', encoding='utf-8')
    with pytest.raises(ValueError, match='arc_easy'):
        validate_assets(tmp_path, 'arc_easy', [], [])
    with pytest.raises(ValueError, match='unknown'):
        validate_assets(tmp_path, ['unknown'], [], [])


def test_evaluator_declarations_do_not_execute_code(tmp_path):
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts/base_eval.py').write_text("raise RuntimeError('must not execute')\nSTEM_TASKS = []\nSTEM_BENCHMARK_LABELS = ['arc_easy']", encoding='utf-8')
    assert task_definitions(tmp_path) == ([], ['arc_easy'])


def test_default_commands_short_and_no_bootstrap_duplication():
    for stage in ('mixing', 'training'):
        command = ModelArtsWorkflowManager._command(stage)
        assert len(command) < 200
        assert command.endswith('run_modelarts_stage.sh ' + stage)


def test_missing_tokenizer_never_downloads_in_offline_mode(tmp_path):
    import sys
    from quadmix.utils.tokenizer_utils import get_tokenizer
    tokenizer = SimpleNamespace(from_pretrained=lambda _: pytest.fail('network tokenizer called'))
    with patch.dict(sys.modules, {'tokenizers': SimpleNamespace(Tokenizer=tokenizer)}), patch.dict('os.environ', {'HF_HUB_OFFLINE': '1'}):
        with pytest.raises(FileNotFoundError, match='离线'):
            get_tokenizer(str(tmp_path / 'missing'), use_cache=False)


def test_default_settings_never_return_credentials(tmp_path):
    from auto_mixture_tool.api import server
    (tmp_path / 'configs').mkdir()
    (tmp_path / 'configs/modelarts_ui_defaults.json').write_text(json.dumps({'region': 'cn-south-1', 'Authorization': 'secret', 'authorization': 'secret'}))
    with patch.object(server, '_workflow_manager', return_value=SimpleNamespace(workspace=tmp_path)):
        assert server.workflow_defaults()['modelarts'] == {'region': 'cn-south-1'}


def test_proxy_validation_offline_skips_remote_checks(tmp_path):
    # Compile this small helper independently: the runner imports heavy training dependencies.
    source = Path('scripts/runners/run_essential_web_v1.py').read_text(encoding='utf-8')
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_ensure_hf_data')
    import os
    namespace = {'os': os, 'VAL_SHA256': {}, '_hf_remote_size': lambda *a: pytest.fail('remote HEAD called')}
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<offline-helper>', 'exec'), namespace)
    path = tmp_path / 'validation.pt'
    path.write_bytes(b'existing validation')
    with patch.dict(os.environ, {'HF_HUB_OFFLINE': '1'}):
        assert namespace['_ensure_hf_data'](str(path), 'repo', 'file') == str(path)


def test_mounted_resources_report_multiple_missing_files(tmp_path):
    from auto_mixture_tool.modelarts.preflight import check_mounted_assets
    with pytest.raises(ValueError) as exc:
        check_mounted_assets({'training': {}, 'evaluation': {}}, 'mixing', tmp_path)
    assert 'tokenizer.json' in str(exc.value)
    assert 'stem_v2_tokenized.pt' in str(exc.value)
    assert 'token_bytes.pt' in str(exc.value)


def test_zip_cannot_escape_runtime(tmp_path):
    import zipfile
    from nanochat_mid_compare.prepare_offline_eval_bundle import materialize
    source = tmp_path / 'source'
    source.mkdir()
    with zipfile.ZipFile(source / 'bad.zip', 'w') as archive:
        archive.writestr('../escape', 'unsafe')
    with pytest.raises(ValueError, match='unsafe'):
        materialize(source, tmp_path / 'runtime')
    assert not (tmp_path / 'escape').exists()
