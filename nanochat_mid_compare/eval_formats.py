"""Adapt common text benchmark records without changing mounted source data."""
import csv
import json
import math
import re
from pathlib import Path

import yaml

TASK_TYPES = {'multiple_choice', 'generation', 'schema', 'language_modeling'}


def _text(row, keys):
    for key in keys:
        value = row.get(key)
        if isinstance(value, dict) and key == 'question':
            value = value.get('stem')
        if isinstance(value, str) and value.strip():
            return value
    raise ValueError('无法识别题目文本；可识别字段：' + ' / '.join(keys))


def normalize_record(row, task):
    if not isinstance(row, dict):
        raise ValueError('记录必须是包含题目和答案的对象')
    kind = task.get('icl_task_type', task.get('task_type'))
    if kind not in TASK_TYPES:
        raise ValueError(f'不支持任务类型：{kind}；代码执行、多模态或自定义评分需要对应评测器')
    out = dict(row)
    if kind == 'language_modeling':
        out['context'] = _text(row, ['context'])
        out['continuation'] = _text(row, ['continuation'])
        return out
    if kind == 'schema':
        choices = row.get('context_options')
        out['continuation'] = _text(row, ['continuation'])
    else:
        out['query'] = _text(row, ['query', 'question', 'problem', 'prompt', 'input'])
        if kind == 'generation':
            extractor = task.get('answer_extractor', 'gsm8k')
            if extractor not in {'gsm8k', 'math'}:
                raise ValueError(f'当前评测器不支持答案提取器 {extractor}；不能自动替换评分规则')
            answer = next((row[k] for k in ('answer', 'final_answer', 'target') if k in row), None)
            if (isinstance(answer, bool) or not isinstance(answer, (str, int, float))
                    or not str(answer).strip() or (isinstance(answer, float) and not math.isfinite(answer))):
                raise ValueError('缺少可评分的标准答案（answer / final_answer / target）；仅有 solution 解题过程时需提供最终答案')
            out['answer'] = str(answer)
            # Mounted NanoChat versions differ in the prompt key they read.
            out.setdefault('question', out['query'])
            out.setdefault('problem', out['query'])
            return out
        choices = row.get('choices', row.get('options'))
        if choices is None and isinstance(row.get('question'), dict):
            choices = row['question'].get('choices')
    labels = None
    if isinstance(choices, dict):
        if 'text' in choices:
            labels, choices = choices.get('label'), choices['text']
        else:
            labels, choices = list(choices), list(choices.values())
    elif isinstance(choices, list) and choices and all(isinstance(c, dict) for c in choices):
        labels, choices = [c.get('label') for c in choices], [c.get('text') for c in choices]
    if choices is None and kind == 'multiple_choice':
        labels = [k for k in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' if isinstance(row.get(k), str)]
        choices = [row[k] for k in labels]
    if not isinstance(choices, list) or len(choices) < 2 or any(not isinstance(c, str) or not c.strip() for c in choices):
        raise ValueError('无法识别选项；需要 choices/options、带 label/text 的选项，或 A/B/C/D 列')
    if labels is not None and (len(labels) != len(choices) or any(not isinstance(x, str) for x in labels) or len(set(labels)) != len(labels)):
        raise ValueError('选项标签缺失、重复或与选项数量不匹配')
    gold = row.get('gold', row.get('answerKey', row.get('answer', row.get('label'))))
    if 'gold' in row and isinstance(gold, str) and gold.isdecimal():
        gold = int(gold)  # The explicit gold field is always zero-based.
    if isinstance(gold, str):
        candidates = labels if labels is not None else list('ABCDEFGHIJKLMNOPQRSTUVWXYZ')[:len(choices)]
        if gold in candidates:
            gold = candidates.index(gold)
        elif choices.count(gold) == 1:
            gold = choices.index(gold)
    if type(gold) is not int or not 0 <= gold < len(choices):
        raise ValueError('无法确定正确选项；答案须为有效的零起始整数、选项标签或唯一选项文本，不猜测编号起点')
    out['context_options' if kind == 'schema' else 'choices'] = choices
    out['gold'] = gold
    return out


def read_records(path):
    path = Path(path)
    if path.suffix.lower() == '.parquet':
        try:
            import pyarrow.parquet as pq
        except ImportError:
            raise ValueError('读取 Parquet 评测集需要安装 pyarrow') from None
        with pq.ParquetFile(path) as data:
            for batch in data.iter_batches(batch_size=1024):
                yield from batch.to_pylist()
    elif path.suffix.lower() == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as stream:
            yield from csv.DictReader(stream)
    elif path.suffix.lower() == '.json':
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if isinstance(data, dict):
            data = data.get('data', data.get('examples'))
        if not isinstance(data, list):
            raise ValueError('JSON 文件未包含记录数组，支持顶层数组或 data/examples 数组')
        yield from data
    elif path.suffix.lower() == '.jsonl':
        with path.open(encoding='utf-8-sig') as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    raise ValueError(f'{path.name} 第 {line_number} 行不是有效 JSON') from None
    else:
        raise ValueError(f'不能读取 {path.suffix} 数据；当前支持 JSON、JSONL、CSV、Parquet，压缩包或 datasets 缓存请先导出')


def record_path(root, relative, data_dir='eval_data'):
    root = Path(root).resolve()
    if not isinstance(relative, str) or Path(relative).is_absolute() or '\\' in relative or ':' in relative:
        raise ValueError('dataset_uri 必须是评测目录内的相对路径')
    base = (root / data_dir).resolve()
    path = (base / relative).resolve()
    if not base.is_relative_to(root) or not path.is_relative_to(base):
        raise ValueError('评测数据路径越界')
    return path


def package_tasks(source):
    source = Path(source).resolve()
    config = source / 'core.yaml'
    if config.exists():
        if not config.resolve().is_relative_to(source):
            raise ValueError('core.yaml 路径越界')
        tasks = yaml.safe_load(config.read_text(encoding='utf-8'))['icl_tasks']
        if not isinstance(tasks, list) or not tasks:
            raise ValueError('icl_tasks 不能为空')
        return tasks, 'eval_data'
    files = sorted(p for p in source.rglob('*') if p.is_file() and p.suffix.lower() in {'.jsonl', '.json', '.csv', '.parquet'} and p.name != 'eval_meta_data.csv')
    if not files:
        raise ValueError('目录中没有可识别的 JSON、JSONL、CSV 或 Parquet 评测数据')
    tasks = []
    for path in files:
        if not path.resolve().is_relative_to(source):
            raise ValueError('评测数据路径越界')
        row = next(read_records(path), None)
        if not isinstance(row, dict):
            raise ValueError(f'{path.name}：空数据或缺少题目对象')
        label = re.sub(r'[^\w-]', '_', str(path.relative_to(source).with_suffix('')))
        task = {'label': label, 'dataset_uri': path.relative_to(source).as_posix(), 'num_fewshot': [0], 'continuation_delimiter': '\nAnswer: '}
        if 'context_options' in row:
            task['icl_task_type'] = 'schema'
        elif 'context' in row and 'continuation' in row:
            task['icl_task_type'] = 'language_modeling'
        elif any(k in row for k in ('choices', 'options')) or all(k in row for k in ('A', 'B')) or isinstance(row.get('question'), dict):
            task['icl_task_type'] = 'multiple_choice'
        elif re.search(r'(^|[_-])(gsm8k|math(?:500)?)([_-]|$)', path.stem.lower()):
            task.update(icl_task_type='generation', answer_extractor='gsm8k' if 'gsm8k' in path.name.lower() else 'math', max_gen_tokens=256)
        else:
            raise ValueError(f'{path.name}：无法确定任务及评分方式；开放问答、代码或多模态数据需要相应评测器。可用可选 core.yaml 明确受支持的任务类型和答案提取器')
        tasks.append(task)
    return tasks, ''


def inspect_package(source):
    tasks, data_dir = package_tasks(source)
    labels = set()
    for task in tasks:
        label = task['label']
        if task.get('icl_task_type') not in TASK_TYPES:
            raise ValueError(f"不支持任务类型：{task.get('icl_task_type')}；需要对应的评测器")
        if not isinstance(label, str) or not label.strip() or label in labels:
            raise ValueError('任务名称为空或重复')
        labels.add(label)
        count = 0
        for count, row in enumerate(read_records(record_path(source, task['dataset_uri'], data_dir)), 1):
            try:
                normalize_record(row, task)
            except ValueError as exc:
                raise ValueError(f'{label} 第 {count} 条：{exc}') from None
        shots = task.get('num_fewshot', [0])
        if not count or not isinstance(shots, list) or not shots or type(shots[0]) is not int or not 0 <= shots[0] < count:
            raise ValueError(f'{label}：数据为空或样本数不足以满足 num_fewshot')
    metadata = Path(source) / 'eval_meta_data.csv'
    if metadata.is_file():
        if not metadata.resolve().is_relative_to(Path(source).resolve()):
            raise ValueError('eval_meta_data.csv 路径越界')
        with metadata.open(encoding='utf-8-sig') as stream:
            for row in csv.DictReader(stream):
                value = float(row['Random baseline'])
                if not 0 <= value < 100:
                    raise ValueError('Random baseline 必须在 [0, 100) 范围')
    return tasks, data_dir


def prepare_package(source, target):
    """Create an evaluator-compatible copy in a job-local temporary directory."""
    source, target = Path(source), Path(target)
    tasks, data_dir = inspect_package(source)
    (target / 'eval_data').mkdir(parents=True, exist_ok=True)
    baselines = {}
    metadata = source / 'eval_meta_data.csv'
    if metadata.is_file():
        if not metadata.resolve().is_relative_to(source.resolve()):
            raise ValueError('eval_meta_data.csv 路径越界')
        with metadata.open(encoding='utf-8-sig') as stream:
            for row in csv.DictReader(stream):
                value = float(row['Random baseline'])
                if not 0 <= value < 100:
                    raise ValueError('Random baseline 必须在 [0, 100) 范围')
                baselines[row['Eval Task']] = value
    output_tasks = []
    for i, task in enumerate(tasks):
        count, chance = 0, 0.0
        with (target / 'eval_data' / f'task_{i}.jsonl').open('w', encoding='utf-8') as stream:
            for count, row in enumerate(read_records(record_path(source, task['dataset_uri'], data_dir)), 1):
                value = normalize_record(row, task)
                stream.write(json.dumps(value, ensure_ascii=False) + '\n')
                choices = value.get('choices', value.get('context_options'))
                if task['icl_task_type'] in {'multiple_choice', 'schema'}:
                    chance += 100 / len(choices)
        baselines.setdefault(task['label'], chance / count)
        output_tasks.append({**task, 'dataset_uri': f'task_{i}.jsonl', 'num_fewshot': task.get('num_fewshot', [0])})
    (target / 'core.yaml').write_text(yaml.safe_dump({'icl_tasks': output_tasks}, allow_unicode=True), encoding='utf-8')
    with (target / 'eval_meta_data.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['Eval Task', 'Random baseline'])
        writer.writerows((task['label'], baselines[task['label']]) for task in tasks)
    (target / 'adaptation.json').write_text(json.dumps({'source': str(source), 'default_fewshot': 0,
        'baseline_policy': 'Provided baselines are preserved; missing choice baselines use uniform random choice, generation/continuation use 0 (uncentered accuracy).'}, ensure_ascii=False), encoding='utf-8')
