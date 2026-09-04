"""Run NanoChat evaluation while forbidding its internal download helper."""

from __future__ import annotations

import os


def main() -> None:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
    from scripts import base_eval

    def use_mounted_assets(benchmarks="all"):
        base_dir = os.environ.get("NANOCHAT_BASE_DIR")
        if not base_dir or not os.path.isdir(base_dir):
            raise RuntimeError("NANOCHAT_BASE_DIR does not contain mounted evaluation assets")
        print(f"Offline evaluation enabled; using {base_dir} for {benchmarks}")

    # Newer NanoChat versions call this both during preflight and inside
    # evaluate_core(). Replacing the module global prevents the second download.
    if hasattr(base_eval, "prepare_eval_data"):
        base_eval.prepare_eval_data = use_mounted_assets
    base_eval.main()


if __name__ == "__main__":
    main()
