#!/usr/bin/env bash
# ModelArts starts this on each node. All dependencies come from the image/OBS.
set -euo pipefail
STAGE="${1:-}"
case "$STAGE" in mixing|training) ;; *) echo "ERROR: expected mixing or training"; exit 2 ;; esac
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
PY311="${AMT_PYTHON_EXECUTABLE:-$(command -v python3.11 || command -v python3 || true)}"
test -n "$PY311" || { echo "ERROR: Python 3.11 is required"; exit 2; }
"$PY311" -c 'import sys; assert sys.version_info[:2] == (3, 11), "The training image must provide Python 3.11"'

export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export HF_HUB_DISABLE_TELEMETRY=1 PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1
export NANOCHAT_SKIP_EVAL_DOWNLOAD=1 NANOCHAT_DISABLE_WANDB=1
PY_DEPS=/tmp/auto-mixture-python-packages
mkdir -p "$PY_DEPS" /tmp/auto-mixture-python
# Preserve the existing optional-Dask compatibility mode. LightGBM is real.
# The tool does not run distributed Dask; a broken image Dask must not be imported.
: > "$PY_DEPS/dask.py"
export PYTHONPATH="$REPO_DIR:$REPO_DIR/src:$PY_DEPS:${PYTHONPATH:-}"
if ! "$PY311" -c 'import lightgbm' >/dev/null 2>&1; then
    WHEEL=/home/ma-user/modelarts/inputs/python_wheels_dir_7/lightgbm-4.6.0-py3-none-manylinux2014_aarch64.whl
    if [ -f "$WHEEL" ]; then
        "$PY311" -m pip install --no-index --no-deps --upgrade --target "$PY_DEPS" "$WHEEL"
    else
        echo "Missing offline LightGBM wheel: $WHEEL; runtime check will report all missing modules."
    fi
fi
export AMT_PYTHON_EXECUTABLE="$PY311"
ln -sf "$PY311" /tmp/auto-mixture-python/python
ln -sf "$PY311" /tmp/auto-mixture-python/python3
export PATH="/tmp/auto-mixture-python:$PATH"
"$PY311" scripts/modelarts_runtime_check.py
exec "$PY311" -m auto_mixture_tool.modelarts.stage_runner "$STAGE"
