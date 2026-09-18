"""Local, read-only UI acceptance server. Never loads IAM or submits cloud jobs."""
import argparse
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
import uvicorn

from auto_mixture_tool.modelarts.command_preview import commands_for_settings
from auto_mixture_tool.modelarts.input_validation import validate_resource
from auto_mixture_tool.modelarts.result_analysis import analyze_report

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title='AMT read-only UI acceptance')


@app.get('/ui')
def ui():
    return FileResponse(ROOT / 'src/auto_mixture_tool/api/static/index.html')


@app.get('/api/v1/workflow-defaults')
def defaults():
    settings = json.loads((ROOT / 'configs/modelarts_ui_defaults.json').read_text(encoding='utf-8'))
    allowed = {'endpoint', 'region', 'workspace_id', 'workspace_name', 'image_url', 'image_repo_id', 'flavor_id', 'pool_id'}
    return {'auth_mode': 'manual', 'modelarts': {k: v for k, v in settings.items() if k in allowed},
            'commands': commands_for_settings({})}


@app.post('/api/v1/workflow-commands')
def commands(payload: dict):
    return {'commands': commands_for_settings(payload)}


@app.post('/api/v1/resources/validate')
def check(payload: dict):
    try:
        if payload['kind'] == 'dataset':
            from auto_mixture_tool.modelarts.dataset_checks import start_dataset_check
            return start_dataset_check(payload['uri'], payload.get('force', False))
        return validate_resource(payload['kind'], payload['uri'])
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get('/api/v1/resources/checks/{check_id}')
def dataset_check_status(check_id: str):
    from auto_mixture_tool.modelarts.dataset_checks import get_dataset_check
    try:
        return get_dataset_check(check_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get('/api/v1/models')
@app.post('/api/v1/models/compare')
def models():
    return []


@app.get('/api/v1/workflows')
def workflows():
    record = {'id': 'visual-check', 'name': '界面验收示例（非真实实验）', 'created_at': '2026-09-15T12:00:00+08:00',
             'status': 'SUCCEEDED', 'progress': 100, 'stage': '评测完成', 'message': '只读预览服务，所有云作业提交均被禁止。',
             'pipeline_version': 4, 'run_root_obs_uri': 'obs://preview-only/source/',
             'jobs': [{'module': stage, 'key': stage, 'strategy_id': 'quadmix', 'strategy_name': 'QuaDMix 示例',
                       'id': None, 'nodes': 1, 'priority': 2, 'status': 'SUCCEEDED', 'name': stage,
                       'depends_on': [] if stage == 'mixing' else ['mixing' if stage == 'training' else 'training'],
                       'input_obs_uri': 'obs://preview-only/source/sampled/' if stage == 'training' else '',
                       'outputs': {'models': 'obs://preview-only/source/models/'}}
                      for stage in ['mixing', 'training', 'evaluation']],
             'outputs': {'sampled': 'obs://preview-only/source/sampled/', 'models': 'obs://preview-only/source/models/'}}
    return [record, {**record, 'id': 'legacy-check', 'name': '旧版阶段重试验收（非真实实验）', 'pipeline_version': 3}]


@app.get('/api/v1/workflows/{workflow_id}/configuration')
def configuration(workflow_id: str):
    if workflow_id not in {'visual-check', 'legacy-check'}:
        raise HTTPException(404, '仅提供本机验收配置')
    return {'execution_mode': 'parallel' if workflow_id == 'visual-check' else 'sequential',
            'strategies': [{'id': 'quadmix', 'type': 'quadmix'}],
            'training_nodes': 1, 'evaluation_nodes': 1, 'priority': 2,
            'training': {'token_budget': 401395843, 'devices_per_node': 8, 'device_batch_size': 8,
                         'eval_every': 100, 'core_metric_every': -1, 'base_model_tag': 'd24'},
            'evaluation': {'datasets': ['stem'], 'devices_per_node': 8, 'core_eval_batch_size': 16,
                           'obs_packages': [{'name': 'SuperGPQA 示例', 'obs_uri': 'obs://preview-only/supergpqa/'}]},
            'resources': {key: 'obs://preview-only/' + name + '/' for key, name in (
                ('code_obs_uri', 'code'), ('nanochat_repo_obs_uri', 'nanochat'), ('nanochat_model_obs_uri', 'model'),
                ('python_wheels_obs_uri', 'wheels'), ('eval_bundle_obs_uri', 'eval'))},
            'output_root_obs_uri': 'obs://preview-only/results/', 'modelarts': defaults()['modelarts']}


@app.get('/api/v1/workflows/visual-check/analysis')
def analysis():
    report = analyze_report({'models': [
        {'id': str(i), 'name': name, 'step': 383, 'model_tag': 'd24',
         'strategy_config': {'type': kind, 'proxy_experiments': 50, 'proxy_steps': 15, 'seed': 42,
                             'sampling_bounds': {'omega': [0, .2], 'epsilon': [0, .001], 'lambda': [0, 1000], 'eta': [0, 1]}},
         'training_config': {'token_budget': 401395843},
         'metrics': [{'Task': task, 'Accuracy': score} for task, score in zip(['arc_easy', 'mmlu_stem', 'gsm8k_cot'], scores)]}
        for i, (name, kind, scores) in enumerate([('QuaDMix · 示例', 'quadmix', [.71, .46, .32]),
                                                ('自定义配比 · 示例', 'manual', [.67, .47, .30]),
                                                ('随机配比 · 示例', 'random', [.61, .40, .25])])],
        'dataset_stats': {'config': {'domain_names': ['数学', '化学', '生物学', '物理'], 'token_method': 'nanochat tokenizer'},
                          '0': {'tokens': 165000000, 'train_docs': 45000,
                                'domain_ratios': {'0': .6, '1': .125, '2': .125, '3': .15}},
                          '1': {'tokens': 390000000, 'train_docs': 95000,
                                'domain_ratios': {'0': .6, '1': .125, '2': .125, '3': .15}},
                          '2': {'tokens': 390000000, 'train_docs': 99000,
                                'domain_ratios': {'0': .3, '1': .2, '2': .25, '3': .25}}}})
    return {'name': '界面验收示例（非真实实验）', 'reports': [{**report, 'id': 'sample', 'name': '示例数据', 'source': '本机验收夹具，非真实评测结果'}],
            'errors': [], 'message': '以下数值仅用于验收图表布局，不代表算法性能。'}


@app.api_route('/api/v1/{path:path}', methods=['GET', 'POST', 'DELETE'])
def disabled(path: str):
    raise HTTPException(403, '本机只读预览：禁止创建、修改或删除任何云作业。正式运行请使用 auto-mixture serve。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8093)
    args = parser.parse_args()
    uvicorn.run(app, host='127.0.0.1', port=args.port)
