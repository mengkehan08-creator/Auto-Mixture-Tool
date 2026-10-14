#!/usr/bin/env python3
"""NanoChat platform adapter with explicit custom-STEM capability checks.

The upstream NanoChat checkout remains replaceable. A checkout that supports
custom validation exposes scripts.platform_validation and a run_validation()
function. Without that extension this adapter refuses to silently ignore custom
tasks/data. Plain benchmark-group evaluation continues to use the repository's
existing shell experiment.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-script", required=True)
    args = parser.parse_args()
    tasks = [item for item in os.environ.get("STEM_TASKS", "").split(",") if item]
    validation_data = os.environ.get("STEM_VALIDATION_DATA")
    nanochat_repo = os.environ.get("NANOCHAT_REPO")

    if not tasks and not validation_data:
        subprocess.run(["bash", args.experiment_script], check=True)
        return
    if not nanochat_repo:
        raise SystemExit("NANOCHAT_REPO is required for custom STEM validation")

    sys.path.insert(0, str(Path(nanochat_repo).resolve()))
    try:
        extension = importlib.import_module("scripts.platform_validation")
    except ImportError as exc:
        raise SystemExit(
            "The selected NanoChat checkout does not implement "
            "scripts.platform_validation; custom STEM tasks/data would be ignored. "
            "Implement run_validation(config) as documented in "
            "docs/PLATFORM_INTEGRATION_ZH.md."
        ) from exc

    config = {
        "tasks": tasks,
        "validation_data_uri": validation_data,
        "benchmarks": os.environ.get("EVAL_BENCHMARKS", "stem"),
        "experiment_script": str(Path(args.experiment_script).resolve()),
        "environment": dict(os.environ),
    }
    result = extension.run_validation(config)
    print(json.dumps(result or {"status": "completed"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
