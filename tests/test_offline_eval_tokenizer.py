import sys
from types import ModuleType
from unittest.mock import patch

import pytest

from nanochat_mid_compare.offline_base_eval import prepare_tokenizer_runtime, install_offline_eval


def test_missing_rustbpe_uses_existing_tokenizer_only(monkeypatch):
    monkeypatch.delitem(sys.modules, 'rustbpe', raising=False)
    with patch('importlib.import_module', side_effect=ModuleNotFoundError(name='rustbpe')):
        prepare_tokenizer_runtime()
    module = sys.modules.pop('rustbpe')
    with pytest.raises(RuntimeError, match='training a new tokenizer is unavailable'):
        module.Tokenizer()


def test_real_rustbpe_is_preserved(monkeypatch):
    real = ModuleType('rustbpe')
    monkeypatch.setitem(sys.modules, 'rustbpe', real)
    prepare_tokenizer_runtime()
    assert sys.modules['rustbpe'] is real


def test_broken_install_is_not_silenced():
    with patch('importlib.import_module', side_effect=ModuleNotFoundError(name='native_dependency')):
        with pytest.raises(ModuleNotFoundError) as error:
            prepare_tokenizer_runtime()
    assert error.value.name == 'native_dependency'


def test_evaluator_initializes_tokenizer_before_import(monkeypatch):
    scripts = ModuleType('scripts')
    evaluator = ModuleType('base_eval')
    scripts.base_eval = evaluator
    monkeypatch.setitem(sys.modules, 'scripts', scripts)
    with patch('nanochat_mid_compare.offline_base_eval.prepare_tokenizer_runtime') as prepare:
        assert install_offline_eval() is evaluator
    prepare.assert_called_once()
