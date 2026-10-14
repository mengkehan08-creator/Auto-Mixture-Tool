import json
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest
import yaml

from nanochat_mid_compare.eval_formats import normalize_record, prepare_package, inspect_package
from nanochat_mid_compare.eval_assets import validate_task_records, validate_assets
from nanochat_mid_compare.offline_base_eval import adapt_evaluator, install_offline_eval
from auto_mixture_tool.modelarts.evaluation_job import validate_package


@pytest.mark.parametrize('key', ['question', 'query', 'problem', 'prompt', 'input'])
def test_generation_accepts_prompt_aliases_without_modifying_original(key):
    row = {key: '1+1?', 'answer': 'Calculation. #### 2'}
    result = normalize_record(row, {'icl_task_type': 'generation', 'answer_extractor': 'gsm8k'})
    assert result['query'] == result['question'] == result['problem'] == '1+1?'
    assert result['answer'] == row['answer'] and len(row) == 2


@pytest.mark.parametrize('row', [
    {'question': 'Q', 'choices': ['x', 'y'], 'answer': 1},
    {'question': 'Q', 'options': ['x', 'y'], 'answer': 'B'},
    {'question': 'Q', 'A': 'x', 'B': 'y', 'answer': 'B'},
    {'question': 'Q', 'choices': {'text': ['x', 'y'], 'label': ['1', '2']}, 'answerKey': '2'},
    {'question': {'stem': 'Q', 'choices': [{'label': 'A', 'text': 'x'}, {'label': 'B', 'text': 'y'}]}, 'answerKey': 'B'},
])
def test_choice_variants(row):
    result = normalize_record(row, {'task_type': 'multiple_choice'})
    assert result['query'] == 'Q' and result['choices'] == ['x', 'y'] and result['gold'] == 1


def test_schema_and_language_modeling_are_not_forced_to_have_query():
    schema = {'context_options': ['a', 'b'], 'continuation': 'c', 'gold': 0}
    lm = {'context': 'a', 'continuation': 'b'}
    assert normalize_record(schema, {'task_type': 'schema'}) == schema
    assert normalize_record(lm, {'task_type': 'language_modeling'}) == lm


def test_bad_answers_not_guessed():
    with pytest.raises(ValueError, match='编号起点'):
        normalize_record({'question': 'Q', 'choices': ['a', 'b'], 'answer': '1'}, {'task_type': 'multiple_choice'})
    with pytest.raises(ValueError, match='最终答案'):
        normalize_record({'problem': 'Q', 'solution': 'long solution'}, {'task_type': 'generation', 'answer_extractor': 'math'})
    with pytest.raises(ValueError, match='评分规则'):
        normalize_record({'question': 'Q', 'answer': 'a'}, {'task_type': 'generation', 'answer_extractor': 'judge'})


def test_original_gsm8k_preflight_and_runtime_use_same_mapping(tmp_path):
    (tmp_path / 'eval_data').mkdir()
    row = {'question': '1+1?', 'answer': '#### 2'}
    (tmp_path / 'eval_data/gsm8k.jsonl').write_text(json.dumps(row) + '\n')
    task = {'label': 'gsm8k_cot', 'dataset_uri': 'gsm8k.jsonl', 'icl_task_type': 'generation', 'answer_extractor': 'gsm8k', 'num_fewshot': [0]}
    assert validate_task_records(tmp_path, task) == 1
    seen = []
    def evaluator(model, tokenizer, data, device, meta, **kwargs):
        seen.extend(data)
        return .5
    assert adapt_evaluator(evaluator)(None, None, [row], None, {**task, 'task_type': 'generation'}) == .5
    assert seen[0]['question'] == seen[0]['query'] == '1+1?'


@pytest.mark.parametrize('extension', ['json', 'jsonl', 'parquet'])
def test_raw_directory_auto_prepares_runtime_bundle(tmp_path, extension):
    source, output = tmp_path / 'raw', tmp_path / 'prepared'
    source.mkdir()
    rows = [{'question': 'Q', 'choices': ['a', 'b'], 'answer': 1}]
    path = source / f'questions.{extension}'
    if extension == 'parquet':
        pa = pytest.importorskip('pyarrow')
        import pyarrow.parquet as pq
        pq.write_table(pa.Table.from_pylist(rows), path)
    else:
        path.write_text(json.dumps(rows if extension == 'json' else rows[0]), encoding='utf-8')
    before = path.read_bytes()
    assert validate_package(source) == ['questions']
    prepare_package(source, output)
    tasks, _ = inspect_package(output)
    assert tasks[0]['num_fewshot'] == [0]
    adapted = json.loads((output / 'eval_data/task_0.jsonl').read_text())
    assert adapted['query'] == 'Q' and adapted['gold'] == 1
    assert 'questions,50.0' in (output / 'eval_meta_data.csv').read_text()
    assert path.read_bytes() == before and not (source / 'core.yaml').exists()
    runtime = tmp_path / 'runtime'; runtime.mkdir()
    (runtime / 'eval_bundle').mkdir()
    import shutil
    shutil.copytree(output, runtime / 'eval_bundle', dirs_exist_ok=True)
    assert validate_assets(runtime, ['core'], [], []) == ['questions']


def test_raw_gsm8k_and_unknown_generation_explain_compatibility(tmp_path):
    path = tmp_path / 'gsm8k.jsonl'
    path.write_text('{"question":"Q", "answer":"#### 2"}\n')
    assert validate_package(tmp_path) == ['gsm8k']
    path.rename(tmp_path / 'freeform.jsonl')
    with pytest.raises(ValueError, match='评分方式'):
        validate_package(tmp_path)


def test_csv_letter_columns(tmp_path):
    (tmp_path / 'questions.csv').write_text('question,A,B,answer\nQ,a,b,B\n')
    assert validate_package(tmp_path) == ['questions']


def test_direct_cli_help_does_not_require_package_import_path():
    import subprocess
    import sys
    path = Path(__file__).resolve().parents[1] / 'nanochat_mid_compare/eval_assets.py'
    result = subprocess.run([sys.executable, str(path), '--help'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_adapter_is_installed_in_real_evaluator_entry(monkeypatch):
    import sys
    scripts, evaluator = ModuleType('scripts'), ModuleType('base_eval')
    calls = []
    evaluator.evaluate_generation_task = lambda m, t, data, d, meta: calls.extend(data)
    scripts.base_eval = evaluator
    monkeypatch.setitem(sys.modules, 'scripts', scripts)
    with patch('nanochat_mid_compare.offline_base_eval.prepare_tokenizer_runtime'):
        install_offline_eval()
        install_offline_eval()
    evaluator.evaluate_generation_task(None, None, [{'question': 'Q', 'answer': 'A'}], None, {'task_type': 'generation'})
    assert calls[0]['query'] == 'Q'


def test_eval_job_prepares_custom_packages_before_launch(tmp_path, monkeypatch):
    from auto_mixture_tool.modelarts import evaluation_job
    seen = []
    def prepare(source, target):
        assert source.name == 'eval_package_0'
        (target / 'marker').write_text('ok')
    def run(config, packages):
        seen.append(packages[0][1])
        assert (packages[0][1] / 'marker').read_text() == 'ok'
    monkeypatch.setattr(evaluation_job, '_run_packages', run)
    with patch('nanochat_mid_compare.eval_formats.prepare_package', side_effect=prepare):
        evaluation_job.run_evaluation({'evaluation': {'obs_packages': [{'name': 'raw'}]}})
    assert seen and not seen[0].exists()
