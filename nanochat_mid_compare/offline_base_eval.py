"""Run NanoChat evaluation while forbidding its internal download helper."""

from __future__ import annotations

import os
import importlib
import sys
from pathlib import Path
from nanochat_mid_compare.eval_assets import validate_assets


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
