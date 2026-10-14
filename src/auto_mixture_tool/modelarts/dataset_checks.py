"""Short HTTP requests for asynchronous input checks; submission only reads status."""
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from .input_validation import validate_resource

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='dataset-check')
_lock = Lock()
_checks = {}
_latest = {}
CHECK_TTL = 3600
MAX_CHECKS = 128


def _key(uri):
    return (str(uri).strip().rstrip('/'), os.environ.get('AMT_OBS_MOUNT_ROOT', ''),
            os.environ.get('AMT_OBS_MOUNT_PREFIX', ''))


def _public(item):
    return {**item.get('result', {}), 'check_id': item['id'], 'uri': item['key'][0],
            'status': item['status'], 'ready': item['status'] == 'SUCCEEDED',
            'message': item['message']}


def _run(check_id):
    with _lock:
        item = _checks[check_id]
        uri = item['key'][0]
    try:
        result = validate_resource('dataset', uri)
        if not result.get('ready'):
            raise ValueError(result.get('message', '输入数据校验未通过'))
        status, message = 'SUCCEEDED', result['message']
    except Exception as exc:
        result, status, message = {}, 'FAILED', str(exc)
    with _lock:
        item.update(result=result, status=status, message=message, finished=time.monotonic())


def start_dataset_check(uri, force=False):
    key = _key(uri)
    with _lock:
        now = time.monotonic()
        for check_id, item in list(_checks.items()):
            if item['status'] != 'RUNNING' and now - item['finished'] >= CHECK_TTL:
                del _checks[check_id]
                if _latest.get(item['key']) == check_id:
                    del _latest[item['key']]
        existing = _checks.get(_latest.get(key))
        if existing and (existing['status'] == 'RUNNING' or not force):
            return _public(existing)
        if len(_checks) >= MAX_CHECKS:
            raise ValueError('数据校验请求过多，请稍后重试')
        check_id = uuid.uuid4().hex
        item = {'id': check_id, 'key': key, 'status': 'RUNNING', 'message': '正在随机抽样校验并估算数据量…'}
        _checks[check_id] = item
        _latest[key] = check_id
        _pool.submit(_run, check_id)
        return _public(item)


def get_dataset_check(check_id):
    with _lock:
        item = _checks.get(check_id)
        if item is None or (item['status'] != 'RUNNING' and time.monotonic() - item['finished'] >= CHECK_TTL):
            raise ValueError('数据校验记录已失效，请返回配比配置重新校验')
        return _public(item)


def require_dataset_check(uri):
    with _lock:
        item = _checks.get(_latest.get(_key(uri)))
        if (item is None or item['status'] != 'SUCCEEDED'
                or time.monotonic() - item['finished'] >= CHECK_TTL):
            raise ValueError('输入数据尚未校验通过或结果已过期，不能提交；请返回配比配置完成自动校验')
