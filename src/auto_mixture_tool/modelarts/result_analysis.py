"""Read recorded evaluation artifacts and produce descriptive, evidence-bounded comparisons."""
from __future__ import annotations

import json
import math
import re
from urllib.parse import unquote, urlsplit

from .model_comparison import mounted_metadata_path, compare_identity, training_differences

MAX_REPORT_BYTES = 8 * 1024 * 1024
AGGREGATES = {'CORE', 'STEM'}


def invalid_constant(value):
    raise ValueError('报告不能包含 NaN 或 Infinity')


def read_report(uri):
    """Read only small JSON reports, never caller-supplied local paths or model weights."""
    parsed = urlsplit(uri)
    if (parsed.scheme != 'obs' or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,62}', parsed.netloc)
            or parsed.query or parsed.fragment or '\\' in uri or any(c.isspace() for c in uri)
            or '..' in unquote(parsed.path).split('/')
            or parsed.path.rsplit('/', 1)[-1] != 'comparison_report.json'):
        raise ValueError('评测报告地址无效，只允许读取 OBS comparison_report.json')
    local = mounted_metadata_path(uri)
    try:
        if local is not None:
            if local.stat().st_size > MAX_REPORT_BYTES:
                raise ValueError('report too large')
            with local.open('rb') as stream:
                raw = stream.read(MAX_REPORT_BYTES + 1)
        else:
            import moxing as mox
            if mox.file.get_size(uri) > MAX_REPORT_BYTES:
                raise ValueError('report too large')
            with mox.file.File(uri, 'rb') as stream:
                raw = stream.read(MAX_REPORT_BYTES + 1)
        if len(raw) > MAX_REPORT_BYTES:
            raise ValueError('report too large')
        report = json.loads(raw, parse_constant=invalid_constant)
        if not isinstance(report, dict):
            raise ValueError('invalid report')
        return report
    except ImportError:
        raise ValueError('报告目录未映射到本地挂载，且未安装 MoXing；请配置只读挂载或 OBS 读取环境') from None
    except Exception:
        # SDK exceptions may contain credentials or signed URLs.
        raise ValueError('评测报告读取失败：请检查报告已同步、挂载或 OBS 只读权限、JSON 格式及文件大小不超过 8 MiB') from None


def score(value, accuracy=False):
    if isinstance(value, bool) or value is None or str(value).strip() == '':
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or (accuracy and not 0 <= number <= 1):
        return None
    return number


def model_stats(report, model):
    stats = report.get('dataset_stats', {})
    if not isinstance(stats, dict):
        return {}
    if model.get('catalog_id'):
        stats = stats.get(model['catalog_id'], {})
    if not isinstance(stats, dict):
        return {}
    candidates = {k: v for k, v in stats.items() if isinstance(v, dict) and 'tokens' in v}
    selected = candidates.get(model.get('id'))
    if selected is None and len(candidates) == 1:
        selected = next(iter(candidates.values()))
    if not selected:
        return {}
    return {k: selected[k] for k in ('tokens', 'train_docs', 'domain_ratios', 'domain_doc_ratios') if k in selected}


def analyze_report(report):
    raw_models = report.get('models')
    if not isinstance(raw_models, list) or not 1 <= len(raw_models) <= 256:
        raise ValueError('评测报告缺少有效模型列表（支持 1–256 个模型）')
    warnings, models, identities, training_configs = [], [], [], []
    comparability = report.get('comparability') or []
    if not isinstance(comparability, list):
        raise ValueError('评测报告可比性信息格式无效')
    for index, model in enumerate(raw_models):
        if not isinstance(model, dict) or not isinstance(model.get('metrics'), list):
            raise ValueError('评测报告模型或指标列表格式无效')
        name = str(model.get('name') or model.get('id') or f'模型 {index + 1}')
        metrics, aggregates, seen = {}, {}, set()
        if len(model['metrics']) > 1024:
            raise ValueError('单模型评测指标超过 1024 项')
        for raw in model['metrics']:
            if not isinstance(raw, dict):
                raise ValueError('评测指标行格式无效')
            row = {str(k).strip(): v for k, v in raw.items()}
            task = str(row.get('Task') or '').strip()
            if not task:
                warnings.append(f'{name}：忽略了未命名的指标行。')
                continue
            if task in seen:
                raise ValueError(f'{name} 的评测项 {task} 重复，无法确定有效结果')
            seen.add(task)
            values = {'accuracy': score(row.get('Accuracy'), True), 'centered': score(row.get('Centered'))}
            (aggregates if task in AGGREGATES else metrics)[task] = values
            if task not in AGGREGATES and values['accuracy'] is None:
                warnings.append(f'{name} / {task}：正确率缺失或无效，未按零分计算。')
        training = model.get('training_config') or {}
        identity = model.get('comparison_identity') or {}
        if not isinstance(training, dict) or not isinstance(identity, dict):
            raise ValueError('模型训练配置或身份信息格式无效')
        identities.append(identity)
        training_configs.append(training)
        models.append({'id': f'model_{index}', 'name': name,
                       'model_tag': model.get('model_tag'), 'step': model.get('step'),
                       'source_workflow_id': model.get('source_workflow_id'),
                       'metrics': metrics, 'aggregates': aggregates, 'sampling': model_stats(report, model),
                       'configured_ratios': model.get('configured_ratios', {}),
                       'training': {k: training[k] for k in ('token_budget', 'num_iterations', 'device_batch_size',
                                   'sequence_len', 'learning_rate', 'global_batch_size') if k in training}})
    tasks = sorted(set().union(*(m['metrics'].keys() for m in models)))
    common = [t for t in tasks if all(m['metrics'].get(t, {}).get('accuracy') is not None for m in models)]
    for model in models:
        model['mean_accuracy'] = sum(model['metrics'][t]['accuracy'] for t in common) / len(common) if common else None
    conclusions = []
    if len(common) < len(tasks):
        warnings.append('部分评测项没有覆盖全部模型；均值只使用全部模型都有有效正确率的共同评测项。')
    if len(models) == 1:
        conclusions.append('本次仅有一个模型的结果，可以查看得分，不能据此比较策略优劣。')
    elif not common:
        conclusions.append('没有所有模型共同完成的有效评测项，无法进行总体排序。')
    else:
        best = max(m['mean_accuracy'] for m in models)
        leaders = [m for m in models if math.isclose(m['mean_accuracy'], best, abs_tol=1e-9, rel_tol=0)]
        names = '、'.join(m['name'] for m in leaders)
        conclusions.append(f'在共同的 {len(common)} 个评测项上，{names} 的等权平均正确率'
                           f'{"并列" if len(leaders) > 1 else ""}最高，为 {best:.2%}。此均值不是官方 CORE/STEM 汇总指标。')
        lower = [m for m in models if m not in leaders]
        if lower:
            runner_up = max(lower, key=lambda m: m['mean_accuracy'])
            conclusions.append(f'最高均值比 {runner_up["name"]} 高 {(best - runner_up["mean_accuracy"]) * 100:.2f} 个百分点。'
                               '这是本次观测差值，不代表统计显著。')
        reference = leaders[0]
        for model in models:
            wins, ties = [], []
            for task in common:
                top = max(m['metrics'][task]['accuracy'] for m in models)
                winners = [m for m in models if math.isclose(m['metrics'][task]['accuracy'], top, abs_tol=1e-9, rel_tol=0)]
                if model in winners:
                    (wins if len(winners) == 1 else ties).append(task)
            if wins or ties:
                detail = []
                if wins:
                    detail.append('单项最高：' + '、'.join(wins))
                if ties:
                    detail.append('并列最高：' + '、'.join(ties))
                conclusions.append(f'{model["name"]}：' + '；'.join(detail) + '。')
            if model is not reference:
                differences = [(t, model['metrics'][t]['accuracy'] - reference['metrics'][t]['accuracy']) for t in common]
                above = sum(delta > 1e-9 for _, delta in differences)
                below = sum(delta < -1e-9 for _, delta in differences)
                conclusions.append(f'{model["name"]} 相对均值最高的 {reference["name"]}：'
                                   f'{above} 项更高、{below} 项更低、{len(common) - above - below} 项持平。')
                if below:
                    weakest, delta = min(differences, key=lambda item: item[1])
                    conclusions.append(f'{model["name"]} 的最大相对落后项为 {weakest}，低 {-delta * 100:.2f} 个百分点。')
    for index in range(1, len(models)):
        check = compare_identity(identities[0], identities[index])
        reasons = check['reasons'] + training_differences(training_configs[0], training_configs[index])
        if any(training_configs[i].get('token_budget') is None for i in (0, index)):
            reasons.append('训练 Token 预算未完整记录')
        for key in ('num_iterations', 'target_param_data_ratio'):
            left, right = training_configs[0].get(key), training_configs[index].get(key)
            if left is None or right is None:
                reasons.append(f'{key} 未完整记录')
            elif left != right:
                reasons.append(f'{key} 不同')
        if reasons:
            warnings.append(f'{models[index]["name"]} 与 {models[0]["name"]}：' + '；'.join(dict.fromkeys(reasons)) + '。')
    for check in comparability:
        if isinstance(check, dict):
            for field in ('reasons', 'warnings'):
                entries = check.get(field) or []
                if not isinstance(entries, list):
                    raise ValueError('评测报告可比性提示格式无效')
                warnings.extend(str(v) for v in entries)
    warnings.append('当前报告未提供多随机种子重复实验和逐样本统计检验；结论仅描述本次得分，不能证明某策略普遍更优或具有因果优势。')
    warnings.append('不同模型结构、基础权重、Tokenizer 或训练预算可能影响结果；节点数量本身不作为模型类型差异。')
    return {'models': models, 'tasks': tasks, 'common_tasks': common, 'conclusions': conclusions,
            'warnings': list(dict.fromkeys(warnings)),
            'method': '逐项正确率与共同评测项等权均值；缺失值不补零。Centered 和官方汇总值单独展示，不混入均值。'}


def workflow_analysis(record, reader=None):
    reader = reader or read_report
    jobs = [j for j in record.get('jobs', []) if j.get('module') == 'evaluation']
    base = {'workflow_id': record['id'], 'name': record.get('name', record['id']), 'reports': [], 'errors': []}
    if not jobs:
        return {**base, 'status': 'unavailable', 'message': '此实验没有独立评测作业，暂不提供结果分析。'}
    if any(j.get('status') != 'SUCCEEDED' for j in jobs):
        return {**base, 'status': 'pending', 'message': '评测尚未成功完成；完成后可读取结果分析。'}
    settings = record.get('config', {}).get('evaluation', {})
    root = record.get('outputs', {}).get('reports', '').rstrip('/')
    if not root:
        return {**base, 'status': 'unavailable', 'message': '实验未记录评测报告输出地址。'}
    packages = settings.get('obs_packages', [])
    sources = []
    if not packages:
        sources.append(('builtin', '内置评测集', root))
    else:
        if settings.get('datasets'):
            sources.append(('builtin', '内置评测集', root + '/builtin'))
        for index, package in enumerate(packages):
            sources.append((f'package_{index}', package.get('name') or f'自定义评测集 {index + 1}', root + f'/package_{index}'))
    for key, name, directory in sources:
        uri = directory + '/comparison_report.json'
        try:
            report = analyze_report(reader(uri))
            base['reports'].append({**report, 'id': key, 'name': name, 'source': uri})
        except ValueError as exc:
            base['errors'].append({'name': name, 'source': uri, 'message': str(exc)})
    status = 'partial' if base['reports'] and base['errors'] else 'ready' if base['reports'] else 'unavailable'
    return {**base, 'status': status, 'message': '部分报告不可用，当前分析不覆盖全部评测集。' if status == 'partial'
            else '报告尚不可读，请确认 ModelArts 输出同步完成后刷新。' if status == 'unavailable' else ''}
