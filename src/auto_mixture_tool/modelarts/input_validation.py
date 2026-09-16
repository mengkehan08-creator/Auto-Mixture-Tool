"""Read-only, fail-closed checks of OBS resources mapped to the local mount."""
from pathlib import Path
import math
import random
from urllib.parse import urlsplit

from .model_comparison import mounted_metadata_path

QUALITY = ('stem_relevance', 'knowledge_value', 'notation_fidelity', 'rigor_coherence', 'noise_level')


def mounted_directory(uri):
    parsed = urlsplit(str(uri))
    if parsed.scheme != 'obs' or not parsed.netloc or parsed.query or parsed.fragment or any(c.isspace() for c in str(uri)):
        raise ValueError('请输入有效的 obs://桶/目录/ 地址，不支持网页链接或带空格的地址')
    # Reuse the configured subtree boundary and symlink traversal protection.
    path = mounted_metadata_path(str(uri).rstrip('/') + '/.amt-validation')
    if path is None or not path.parent.is_dir():
        raise ValueError('无法读取 OBS 挂载目录，请检查 AMT_OBS_MOUNT_ROOT、AMT_OBS_MOUNT_PREFIX 及只读权限；未完成校验，不能提交作业')
    return path.parent


def validate_parquet(root):
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        raise ValueError('数据校验需要开发环境安装 pyarrow；未完成校验，不能提交作业') from None
    root = Path(root).resolve()
    files = sorted(root.rglob('*.parquet'))
    if not files:
        raise ValueError('数据格式不符合算法要求：目录中没有 Parquet 分片')
    rows = checked = size_bytes = 0
    estimated_chars = 0.0
    for file in files:
        if not file.resolve().is_relative_to(root):
            raise ValueError('数据路径不能超出挂载目录')
        try:
            parquet = pq.ParquetFile(file)
            schema = parquet.schema_arrow
            required = ('domain', 'text', 'char_count', *QUALITY)
            missing = set(required) - set(schema.names)
            if missing:
                raise ValueError('缺少列：' + ', '.join(sorted(missing)))
            for key in QUALITY:
                dtype = schema.field(key).type
                if not (pa.types.is_integer(dtype) or pa.types.is_floating(dtype)):
                    raise ValueError(f'{key} 必须是数值列')
            if not pa.types.is_integer(schema.field('char_count').type):
                raise ValueError('char_count 必须是整数列')
            domain_type = schema.field('domain').type
            if pa.types.is_dictionary(domain_type):
                domain_type = domain_type.value_type
            if not (pa.types.is_integer(domain_type) or pa.types.is_string(domain_type) or pa.types.is_large_string(domain_type)):
                raise ValueError('domain 必须是领域名称或整数编码')
            if not (pa.types.is_string(schema.field('text').type) or pa.types.is_large_string(schema.field('text').type)):
                raise ValueError('text 必须是字符串列')
            count = parquet.metadata.num_rows
            if not count:
                raise ValueError('数据分片为空')
            rows += count
            size_bytes += file.stat().st_size
            # Uniform document sampling without replacement, across the whole file.
            # Parquet still needs to decode the row groups containing sampled rows.
            selected = sorted(random.SystemRandom().sample(range(count), min(3, count)))
            sample = []
            offset = 0
            for group in range(parquet.metadata.num_row_groups):
                group_count = parquet.metadata.row_group(group).num_rows
                positions = [i - offset for i in selected if offset <= i < offset + group_count]
                if positions:
                    batch_offset = 0
                    for batch in parquet.iter_batches(batch_size=1024, row_groups=[group], columns=list(required)):
                        sample.extend(batch.slice(i - batch_offset, 1).to_pylist()[0]
                                      for i in positions if batch_offset <= i < batch_offset + len(batch))
                        batch_offset += len(batch)
                        if batch_offset > positions[-1]:
                            break
                offset += group_count
            for row in sample:
                if not row['text'] or not row['text'].strip() or row['domain'] is None or str(row['domain']).strip() == '':
                    raise ValueError('text/domain 不能为空')
                if row['char_count'] is None or row['char_count'] <= 0:
                    raise ValueError('char_count 必须大于 0')
                if any(row[k] is None or not math.isfinite(row[k]) for k in QUALITY):
                    raise ValueError('质量分不能为缺失值、NaN 或无穷大')
                checked += 1
            estimated_chars += count * sum(len(row['text']) for row in sample) / len(sample)
        except Exception as exc:
            raise ValueError(f'数据格式不符合算法要求：{file.name}：{exc}') from None
    if not rows:
        raise ValueError('数据格式不符合算法要求：数据集为空')
    return {'ready': True, 'files': len(files), 'rows': rows, 'checked_rows': checked,
            'size_bytes': size_bytes, 'estimated_chars': estimated_chars,
            'estimated_tokens': estimated_chars / 4,
            'token_method': 'sum(file_rows * sampled_mean_text_length) / 4', 'token_is_estimate': True,
            'message': f'共 {len(files)} 个分片、{rows:,} 篇文档；每片随机抽查至多 3 条，共 {checked} 条通过。预计 {estimated_chars / 4:,.0f} Token（按各片抽样平均文本长度 × 文档数 ÷ 4 估算），不是全文校验或精确分词计数。'}


def validate_resource(kind, uri):
    root = mounted_directory(uri)
    if kind == 'dataset':
        return validate_parquet(root)
    if kind == 'evaluation':
        from .evaluation_job import validate_package
        labels = validate_package(root)
        return {'ready': True, 'tasks': labels, 'message': '评测包格式和全部记录检查通过：' + '、'.join(labels)}
    raise ValueError('未知校验类型')


def validate_workflow_resources(config):
    retry_key = config.get('job_reuse', {}).get('key', '')
    if not config.get('reuse') and not retry_key.startswith(('training-', 'evaluation')):
        from .dataset_checks import require_dataset_check
        require_dataset_check(config['input_data_obs_uri'])
    settings = config.get('evaluation', {})
    if settings.get('datasets'):
        from nanochat_mid_compare.eval_assets import task_definitions, validate_task_records
        resources = config['resources']
        core = mounted_directory(resources['eval_bundle_obs_uri'])
        repo = mounted_directory(resources['nanochat_repo_obs_uri'])
        for base, filename in ((repo, 'scripts/base_eval.py'), (core, 'core.yaml')):
            if not (base / filename).resolve().is_relative_to(base.resolve()):
                raise ValueError(f'{filename} 不能链接到挂载目录外部')
        tasks, stem_labels = task_definitions(repo)
        # Read mounted files directly; never materialize or download packages on
        # the development host just to check compatibility.
        import yaml
        core_tasks = yaml.safe_load((core / 'core.yaml').read_text(encoding='utf-8'))['icl_tasks']
        requested = set(settings['datasets'])
        if requested == {'stem'}:
            requested = set(stem_labels)
        found = set()
        for root, definitions in ((core, core_tasks), (core / 'eval_stem', tasks)):
            for task in definitions:
                if task['label'] not in requested and requested not in ({'all'}, {'core'}):
                    continue
                if root != core and requested == {'core'}:
                    continue
                validate_task_records(root, task)
                if not (root / 'eval_meta_data.csv').is_file():
                    raise ValueError('评测包缺少 eval_meta_data.csv')
                found.add(task['label'])
        if not found or (requested not in ({'all'}, {'core'}) and requested - found):
            raise ValueError('评测集不支持所选任务：' + ', '.join(sorted(requested - found)))
    for package in config.get('evaluation', {}).get('obs_packages', []):
        validate_resource('evaluation', package['obs_uri'])
