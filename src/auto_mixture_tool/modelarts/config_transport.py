"""Transport configuration within ModelArts' per-environment-value limit."""
import json
import base64
import hashlib
import zlib

KEY = 'AMT_WORKFLOW_CONFIG_JSON'
PART = KEY + '_PART_'
COUNT = KEY + '_PART_COUNT'
LIMIT = 4000
ENCODING = KEY + '_ENCODING'
CHECKSUM = KEY + '_SHA256'
MAX_CONFIG_BYTES = 1024 * 1024  # Tool safety bound, not a claimed ModelArts quota.
MAX_PARTS = 256


def write_config(env, config):
    for key in list(env):
        if key in {KEY, ENCODING, CHECKSUM} or key.startswith(PART):
            del env[key]
    # ASCII also keeps the UTF-8 byte length below the service limit.
    try:
        raw = json.dumps(config, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError('运行配置必须为合法 JSON，不能包含 NaN、Infinity 或不可序列化对象') from None
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError('运行配置超过工具的 1 MiB 安全上限，请减少策略配置')
    if len(raw) <= LIMIT:
        env[KEY] = raw
        return
    encoded = base64.b64encode(zlib.compress(raw.encode('ascii'))).decode('ascii')
    chunks = [encoded[i:i + LIMIT] for i in range(0, len(encoded), LIMIT)]
    if len(chunks) > MAX_PARTS:
        raise ValueError('运行配置分段过多，请减少策略配置')
    env[ENCODING] = 'zlib-base64'
    env[CHECKSUM] = hashlib.sha256(raw.encode('ascii')).hexdigest()
    env[COUNT] = str(len(chunks))
    for i, chunk in enumerate(chunks):
        env[PART + str(i)] = chunk


def read_config(env):
    if COUNT in env:
        try:
            count = int(env[COUNT])
            if not 1 <= count <= MAX_PARTS:
                raise ValueError()
            raw = ''.join(env[PART + str(i)] for i in range(count))
        except (KeyError, ValueError):
            raise ValueError('工作流配置分段缺失或数量无效，请检查环境变量') from None
        if env.get(ENCODING):
            if env[ENCODING] != 'zlib-base64':
                raise ValueError('不支持的工作流配置编码')
            try:
                decoder = zlib.decompressobj()
                decoded = decoder.decompress(base64.b64decode(raw, validate=True), MAX_CONFIG_BYTES + 1)
                if len(decoded) > MAX_CONFIG_BYTES or not decoder.eof or decoder.unused_data:
                    raise ValueError('无效或超长的压缩配置')
                if hashlib.sha256(decoded).hexdigest() != env.get(CHECKSUM):
                    raise ValueError('配置摘要不匹配')
                raw = decoded.decode('ascii')
            except (ValueError, zlib.error) as exc:
                raise ValueError('工作流配置损坏或超长，请重新提交') from exc
    else:
        raw = env.get(KEY, '')
    if not raw:
        raise ValueError('缺少工作流配置环境变量')
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError('工作流配置超过安全上限')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('工作流配置必须是 JSON 对象')
    return value
