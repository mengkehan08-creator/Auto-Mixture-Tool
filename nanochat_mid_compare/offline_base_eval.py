"""Run NanoChat evaluation while forbidding its internal download helper."""

from __future__ import annotations

import os
import importlib
import sys
from pathlib import Path
from nanochat_mid_compare.eval_assets import validate_assets
from nanochat_mid_compare.eval_formats import normalize_record
from functools import wraps


def adapt_evaluator(function):
    @wraps(function)
    def evaluate(model, tokenizer, data, device, task_meta, *args, **kwargs):
        records = []
        for index, row in enumerate(data, 1):
            try:
                records.append(normalize_record(row, task_meta))
            except ValueError as exc:
                raise ValueError(f"{task_meta.get('label', '评测集')} 第 {index} 条不能评测：{exc}") from None
        return function(model, tokenizer, records, device, task_meta, *args, **kwargs)
    return evaluate


def prepare_tokenizer_runtime():
    """Match training's existing-tokenizer support without hiding broken installs."""
    try:
        importlib.import_module('rustbpe')
    except ModuleNotFoundError as exc:
        if exc.name != 'rustbpe':
            raise
        from nanochat_mid_compare.compat import rustbpe
        sys.modules['rustbpe'] = rustbpe
        print('rustbpe unavailable: using the mounted tokenizer; tokenizer training is disabled')


def install_offline_eval():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
    prepare_tokenizer_runtime()
    from scripts import base_eval
    # Adapt both checks and actual evaluator inputs, not just the preflight.
    for name in ('evaluate_task', 'evaluate_generation_task'):
        function = getattr(base_eval, name, None)
        if callable(function) and not getattr(function, '_amt_adapted', False):
            wrapper = adapt_evaluator(function)
            wrapper._amt_adapted = True
            setattr(base_eval, name, wrapper)

    def use_mounted_assets(benchmarks="all"):
        base_dir = os.environ.get("NANOCHAT_BASE_DIR")
        if not base_dir or not os.path.isdir(base_dir):
            raise RuntimeError("NANOCHAT_BASE_DIR does not contain mounted evaluation assets")
        validate_assets(Path(base_dir), benchmarks, getattr(base_eval, 'STEM_TASKS', []),
                        getattr(base_eval, 'STEM_BENCHMARK_LABELS', []))
        print(f"Offline evaluation enabled; using {base_dir} for {benchmarks}")

    # Newer NanoChat versions call this both during preflight and inside
    # evaluate_core(). Replacing the module global prevents the second download.
    if hasattr(base_eval, "prepare_eval_data"):
        base_eval.prepare_eval_data = use_mounted_assets
    return base_eval


def main() -> None:
    base_eval = install_offline_eval()
    base_eval.main()


if __name__ == "__main__":
    main()
