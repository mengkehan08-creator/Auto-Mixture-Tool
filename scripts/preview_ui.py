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
    return [{'id': 'visual-check', 'name': '界面验收示例（非真实实验）', 'created_at': '2026-09-15T12:00:00+08:00',
             'status': 'SUCCEEDED', 'progress': 100, 'stage': '评测完成', 'message': '只读预览服务，所有云作业提交均被禁止。',
             'jobs': [{'module': stage, 'id': None, 'nodes': 1, 'status': 'SUCCEEDED', 'name': stage}
                      for stage in ['mixing', 'training', 'evaluation']], 'outputs': {}}]


@app.get('/api/v1/workflows/visual-check/analysis')
def analysis():
    report = analyze_report({'models': [
        {'id': str(i), 'name': name, 'step': 383, 'model_tag': 'd24',
         'strategy_config': {'type': kind, 'proxy_experiments': 16, 'proxy_steps': 15, 'seed': 42},
         'training_config': {'token_budget': 401395843},
         'metrics': [{'Task': task, 'Accuracy': score} for task, score in zip(['arc_easy', 'mmlu_stem', 'gsm8k_cot'], scores)]}
        for i, (name, kind, scores) in enumerate([('QuaDMix · 示例', 'quadmix', [.71, .46, .32]),
                                                ('人工配比 · 示例', 'manual', [.67, .47, .30]),
                                                ('随机配比 · 示例', 'random', [.61, .40, .25])])]})
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
