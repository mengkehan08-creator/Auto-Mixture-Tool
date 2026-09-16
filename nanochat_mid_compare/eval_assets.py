"""Validate the exact offline tasks used by the mounted NanoChat evaluator."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

import yaml


def validate_task_records(root: Path, task):
    """Validate the actual NanoChat text evaluation contract, not dataset branding."""
    label = task['label']
    kind = task['icl_task_type']
    if kind not in {'multiple_choice', 'generation'}:
        raise ValueError(f'{label}：不支持 {kind}；代码执行、图像、音频任务需要额外评测器')
    if kind == 'generation' and task.get('answer_extractor', 'gsm8k') not in {'gsm8k', 'math'}:
        raise ValueError(f'{label}：不支持该答案提取器')
    base = (root / 'eval_data').resolve()
    if not base.is_relative_to(root.resolve()):
        raise ValueError(f'{label}：eval_data 不能链接到评测包外部')
    relative = task['dataset_uri']
    if not isinstance(relative, str) or Path(relative).is_absolute() or '\\' in relative or ':' in relative:
        raise ValueError(f'{label}：dataset_uri 必须是 eval_data 内的相对路径')
    path = (base / relative).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f'{label}：数据路径越界')
    count = 0
    with path.open(encoding='utf-8') as stream:
        for count, line in enumerate(stream, 1):
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get('query'), str) or not row['query'].strip():
                raise ValueError(f'{label} 第 {count} 行：缺少非空 query 字符串')
            if kind == 'multiple_choice':
                choices = row.get('choices')
                gold = row.get('gold')
                if (not isinstance(choices, list) or len(choices) < 2 or
                        any(not isinstance(c, str) or not c.strip() for c in choices) or
                        type(gold) is not int or not 0 <= gold < len(choices)):
                    raise ValueError(f'{label} 第 {count} 行：choices 必须是至少两个选项的字符串数组，gold 为有效的零起始整数索引')
            elif not isinstance(row.get('answer'), (str, int, float)) or isinstance(row.get('answer'), bool) or str(row['answer']).strip() == '':
                raise ValueError(f'{label} 第 {count} 行：生成题需要 answer')
    fewshot = task.get('num_fewshot', [0])
    if not count or not isinstance(fewshot, list) or not fewshot or type(fewshot[0]) is not int or not 0 <= fewshot[0] < count:
        raise ValueError(f'{label}：数据为空或样本数不足以满足 num_fewshot')
    return count


def task_definitions(repo: Path):
    """Read declarations without importing the mounted evaluator or torch."""
    tree = ast.parse((repo / 'scripts/base_eval.py').read_text(encoding='utf-8'))
    definitions = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {'STEM_TASKS', 'STEM_BENCHMARK_LABELS'}:
                    definitions[target.id] = ast.literal_eval(node.value)
    return definitions.get('STEM_TASKS', []), definitions.get('STEM_BENCHMARK_LABELS', [])


def validate_assets(base: Path, benchmarks, stem_tasks, stem_labels):
    core = base / 'eval_bundle'
    errors = []
    try:
        core_tasks = yaml.safe_load((core / 'core.yaml').read_text(encoding='utf-8'))['icl_tasks']
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        raise ValueError(f'离线评测配置缺失或无效：{core / "core.yaml"} ({type(exc).__name__})') from None
    if isinstance(benchmarks, str):
        benchmarks = [part.strip() for part in benchmarks.split(',') if part.strip()]
    requested = set(benchmarks or ['all'])
    if requested == {'stem'}:
        requested = set(stem_labels)
        if not requested:
            raise ValueError('当前 NanoChat 缺少 STEM 评测任务声明')
    groups = [(core_tasks, core)]
    if requested != {'core'}:
        groups.append((stem_tasks, base / 'eval_stem'))
    matched = set()
    for tasks, root in groups:
        selected = [t for t in tasks if requested in ({'all'}, {'core'}) or t['label'] in requested]
        if not selected:
            continue
        if not (root / 'eval_meta_data.csv').is_file():
            errors.append(f'缺少评测基线：{root / "eval_meta_data.csv"}')
        for task in selected:
            matched.add(task['label'])
            data_root = (root / 'eval_data').resolve()
            path = (data_root / task['dataset_uri']).resolve()
            if not path.is_relative_to(data_root):
                errors.append(f"非法评测数据路径：{task['label']}")
                continue
            try:
                rows = 0
                with path.open(encoding='utf-8') as stream:
                    for line in stream:
                        row = json.loads(line)
                        if not isinstance(row, dict):
                            raise ValueError('记录必须为对象')
                        rows += 1
                if not rows:
                    raise ValueError('数据文件为空')
            except (OSError, ValueError) as exc:
                errors.append(f"{task['label']}：{path} ({type(exc).__name__})")
    if requested not in ({'all'}, {'core'}):
        errors.extend(f'当前评测器不支持任务：{label}' for label in sorted(requested - matched))
    if not matched:
        errors.append('没有可执行的评测任务')
    if errors:
        raise ValueError('离线评测资源检查失败：\n- ' + '\n- '.join(errors))
    return sorted(matched)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--benchmarks', default='stem')
    args = parser.parse_args()
    tasks, labels = task_definitions(args.repo)
    print('Offline evaluation tasks ready:', ', '.join(validate_assets(args.base, args.benchmarks, tasks, labels)))


if __name__ == '__main__':
    main()
