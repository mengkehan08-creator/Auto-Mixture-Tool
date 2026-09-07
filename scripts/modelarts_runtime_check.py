"""Check all ModelArts runtime dependencies before starting a long job."""

from __future__ import annotations

import importlib
import os
import platform
import sys


REQUIRED_MODULES = (
    "yaml",
    "numpy",
    "pandas",
    "pyarrow",
    "scipy",
    "sklearn",
    "lightgbm",
    "joblib",
    "matplotlib",
    "tqdm",
    "psutil",
    "jinja2",
    "torch",
    "torch_npu",
    "transformers",
    "tokenizers",
    "datasets",
    "tiktoken",
    "filelock",
    "requests",
)


def main() -> int:
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {platform.python_version()}")

    failures: list[str] = []
    loaded: dict[str, object] = {}
    modules = list(REQUIRED_MODULES)
    wandb_disabled = os.environ.get("NANOCHAT_DISABLE_WANDB", "1") == "1"
    if not wandb_disabled:
        modules.append("wandb")
    else:
        fallback_dir = os.path.join(
            os.getcwd(), "nanochat_mid_compare", "compat", "wandb_disabled"
        )
        sys.path.insert(0, fallback_dir)
        modules.append("wandb")

    for name in modules:
        try:
            loaded[name] = importlib.import_module(name)
        except Exception as exc:  # report incompatible imports as well as missing ones
            failures.append(f"{name}: {type(exc).__name__}: {exc}")

    for name in modules:
        module = loaded.get(name)
        if module is not None:
            print(f"{name} version: {getattr(module, '__version__', 'unknown')}")

    lightgbm = loaded.get("lightgbm")
    if lightgbm is not None:
        try:
            model = lightgbm.LGBMRegressor(n_estimators=2, n_jobs=1, verbosity=-1)
            model.fit([[0.0], [1.0], [2.0]], [0.0, 1.0, 2.0])
        except Exception as exc:
            failures.append(
                f"lightgbm smoke test: {type(exc).__name__}: {exc}"
            )

    if wandb_disabled and "wandb" in loaded:
        try:
            run = loaded["wandb"].init(mode="disabled")
            run.log({"runtime_check": 1})
            run.finish()
        except Exception as exc:
            failures.append(f"wandb fallback: {type(exc).__name__}: {exc}")

    if failures:
        print("ERROR: ModelArts runtime check found these problems:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print('Prepare compatible Python 3.11/aarch64 wheels in OBS or rebuild the image. '
              'No online installation was attempted; do not replace torch/torch_npu independently of CANN.', file=sys.stderr)
        return 1

    print("ModelArts runtime dependencies OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
