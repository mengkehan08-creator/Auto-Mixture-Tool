"""Render editable launch commands from non-secret UI settings."""
import json
import shlex


def commands_for_settings(settings):
    from .workflow import ModelArtsWorkflowManager
    resources = settings.get('offline_resources') or []
    if not isinstance(resources, list) or len(resources) > 100:
        raise ValueError('运行资源列表无效')
    manifest = []
    for item in resources:
        if not isinstance(item, dict):
            raise ValueError('运行资源必须包含 name 和 uri')
        name, uri = str(item.get('name', '')), str(item.get('uri', ''))
        if len(name) > 128 or len(uri) > 2048 or '\x00' in name + uri:
            raise ValueError('资源名称或地址无效')
        manifest.append({'name': name, 'uri': uri, 'role': str(item.get('role', ''))})
    context = {
        'AMT_JOB_IMAGE': str(settings.get('image_url', '')),
        'AMT_JOB_RESOURCES': json.dumps(manifest, ensure_ascii=False, separators=(',', ':')),
        'AMT_JOB_DATA_URI': str(settings.get('input_data_obs_uri', '')),
        'AMT_JOB_MODEL_URI': str(settings.get('model_obs_uri', '')),
        'AMT_JOB_FRAMEWORK_URI': str(settings.get('framework_obs_uri', '')),
        'AMT_JOB_EVAL_URI': str(settings.get('eval_bundle_obs_uri', '')),
        'AMT_JOB_EVAL_PACKAGES': json.dumps(settings.get('eval_packages', []), ensure_ascii=False, separators=(',', ':')),
        'AMT_JOB_OUTPUT_URI': str(settings.get('output_obs_uri', '')),
        'AMT_JOB_MODEL_OUTPUT_URI': str(settings.get('model_output_obs_uri', '')),
        'AMT_JOB_REPORT_OUTPUT_URI': str(settings.get('report_output_obs_uri', '')),
    }
    if any('\x00' in value or len(value) > 16384 for value in context.values()):
        raise ValueError('命令配置过长或包含空字符')
    prefix = ' '.join(f'{key}={shlex.quote(value)}' for key, value in context.items())
    result = {}
    for stage in ('mixing', 'training', 'evaluation'):
        command = ModelArtsWorkflowManager._command(stage)
        # Fixed local mount names are part of stage_runner's contract. Changing
        # an OBS URL changes the ModelArts input, not the container-local path.
        result[stage] = prefix + ' ' + command
        if len(result[stage]) > 32768:
            raise ValueError('生成的 command 超过 32768 字符，请减少资源配置')
    return result
