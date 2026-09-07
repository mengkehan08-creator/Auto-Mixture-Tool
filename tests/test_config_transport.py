import pytest
from auto_mixture_tool.modelarts.config_transport import write_config, read_config, KEY, COUNT, PART
from auto_mixture_tool.modelarts.config_transport import CHECKSUM


@pytest.mark.parametrize('size', [1, 3990, 4096, 20000])
def test_config_round_trip(size):
    config = {'text': '数学😀' * size, 'strategies': [{'name': '人工配比'}]}
    env = {'OTHER': 'unchanged'}
    write_config(env, config)
    assert read_config(env) == config
    assert all(len(value.encode('utf-8')) <= 4096 for value in env.values())
    assert env['OTHER'] == 'unchanged'
    write_config(env, {'small': True})
    assert KEY in env and COUNT not in env
    assert not any(k.startswith(PART) for k in env)


def test_missing_chunk_is_explicit():
    with pytest.raises(ValueError, match='分段缺失'):
        read_config({COUNT: '2', PART + '0': '{}'})


def test_legacy_config():
    assert read_config({KEY: '{"old":true}'}) == {'old': True}


def test_corrupt_checksum_rejected():
    env = {}
    write_config(env, {'long': 'text' * 10000})
    env[CHECKSUM] = 'not-the-checksum'
    with pytest.raises(ValueError, match='损坏'):
        read_config(env)


def test_legacy_uncompressed_parts():
    assert read_config({COUNT: '2', PART + '0': '{"old":', PART + '1': 'true}'}) == {'old': True}


def test_internal_size_limit():
    with pytest.raises(ValueError, match='安全上限'):
        write_config({}, {'huge': 'x' * (1024 * 1024)})
