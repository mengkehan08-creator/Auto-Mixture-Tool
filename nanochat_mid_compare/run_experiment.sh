#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# QuadMix vs Random: Nanochat Mid-Training Comparison Experiment
# ──────────────────────────────────────────────────────────────
#
# This script runs nanochat mid-training on two datasets:
#   1. QuadMix-selected subset from essential-web
#   2. Random subset from essential-web (token-count aligned)
#
# Usage (after running QuaDMix pipeline, e.g. bash scripts/demo_run_full.sh):
#   bash nanochat_mid_compare/run_experiment.sh
#
# QUADMIX_SAMPLED_DATA defaults to a specific sampled_dataset path.
# PREPROCESSED_DATA_DIR defaults to $HOME/.cache/QuaDMix/temp/preprocessed.
#
# Override any config via environment variables:
#   QUADMIX_SAMPLED_DATA=/path/to/sampled_dataset \
#   PREPROCESSED_DATA_DIR=/path/to/preprocessed \
#   NANOCHAT_MODEL_DIR=/path/to/.cache/nanochat \
#   bash nanochat_mid_compare/run_experiment.sh
#
# ──────────────────────────────────────────────────────────────

set -euo pipefail

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION — edit these or set via environment variables
# ══════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
QUADMIX_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TIMESTAMP="${AMT_RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
AMT_PYTHON_EXECUTABLE="${AMT_PYTHON_EXECUTABLE:-$(command -v python3)}"
if [ -z "$AMT_PYTHON_EXECUTABLE" ] || [ ! -x "$AMT_PYTHON_EXECUTABLE" ]; then
    echo "ERROR: Python executable not found: ${AMT_PYTHON_EXECUTABLE:-<empty>}"
    exit 1
fi
# Keep every Python and torchrun child on the interpreter selected by the
# ModelArts submission command instead of falling back to an image default.
python3() {
    "$AMT_PYTHON_EXECUTABLE" "$@"
}

NUM_NPU="${NUM_NPU:-8}"
DISTRIBUTED_ENV=$(python3 "$SCRIPT_DIR/distributed_runtime.py" environment --devices "$NUM_NPU")
eval "$DISTRIBUTED_ENV"
install_shared_symlink() {
    local TARGET="$1"
    local LINK="$2"
    local CURRENT=""
    if [ -e "$LINK" ] && [ ! -L "$LINK" ]; then
        echo "ERROR: $LINK exists but is not a symbolic link"
        return 1
    fi
    # A concurrent ln can briefly lose a check-then-create race. Retry and
    # accept success only after observing the requested final target.
    for _ in $(seq 1 20); do
        ln -sfnT "$TARGET" "$LINK" 2>/dev/null || true
        CURRENT=$(readlink "$LINK" 2>/dev/null || true)
        if [ "$CURRENT" = "$TARGET" ]; then
            return 0
        fi
        sleep 0.1
    done
    echo "ERROR: unable to install symlink: $LINK -> $TARGET"
    return 1
}


# QuadMix output: sampled_dataset from QuadMix pipeline
if [ -z "${QUADMIX_SAMPLED_DATA:-}" ]; then
    QUADMIX_SAMPLED_DATA="/home/ma-user/work/QuaDMix/result/revalidate_openhermes_20260702_193824/sampled_dataset"
fi

# Preprocessed shards directory (preprocessed_*.parquet with quality scores)
# Used for both random baseline and quality top-k baseline
PREPROCESSED_DATA_DIR="${PREPROCESSED_DATA_DIR:-$HOME/.cache/QuaDMix/temp/preprocessed}"

# Quality score methods for top-k selection (comma-separated)
# Options: dclm, fineweb_edu, english, math_general, math_openweb
if [ -n "${COMPARISON_METHODS:-}" ]; then
    QUALITY_METHODS="${QUALITY_METHODS:-}"
else
    QUALITY_METHODS="${QUALITY_METHODS-dclm,fineweb_edu}"
fi
COMPARISON_METHODS="${COMPARISON_METHODS:-quadmix,random}"
has_method() { case ",$COMPARISON_METHODS," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }
for method in ${COMPARISON_METHODS//,/ }; do
    case "$method" in quadmix|random) ;; *) echo "ERROR: use run_stem_experiment.sh for $method" >&2; exit 2 ;; esac
done
PREPARED_COMPARISON_DATA_DIR="${PREPARED_COMPARISON_DATA_DIR:-}"
PREPARE_ONLY="${PREPARE_ONLY:-0}"
if [ "$PREPARE_ONLY" = "1" ] && [ "$NODE_RANK" != "0" ]; then exit 0; fi

# Nanochat model directory (contains tokenizer/, base_checkpoints/)
NANOCHAT_MODEL_DIR="${NANOCHAT_MODEL_DIR:-/home/ma-user/work/nanochat_model_dir}"

# Base model tag (pretrained model in $NANOCHAT_MODEL_DIR/base_checkpoints/<tag>/)
BASE_MODEL_TAG="${BASE_MODEL_TAG:-d28}"

# Nanochat repo root
NANOCHAT_REPO="${NANOCHAT_REPO:-/home/ma-user/work/nanochat_midtrain_326}"
export NANOCHAT_REPO
NANOCHAT_RUNTIME_DIR="${NANOCHAT_RUNTIME_DIR:-/tmp/auto-mixture-$TIMESTAMP/node-$NODE_RANK/nanochat_model}"
NANOCHAT_EVAL_BUNDLE_DIR="${NANOCHAT_EVAL_BUNDLE_DIR:-}"
if [ -z "$NANOCHAT_EVAL_BUNDLE_DIR" ] && [ -d "$NANOCHAT_MODEL_DIR/eval_bundle" ]; then
    NANOCHAT_EVAL_BUNDLE_DIR="$NANOCHAT_MODEL_DIR/eval_bundle"
fi
NANOCHAT_LOAD_OPTIMIZER="${NANOCHAT_LOAD_OPTIMIZER:-0}"
NANOCHAT_DISABLE_WANDB="${NANOCHAT_DISABLE_WANDB:-1}"
LOADER="${LOADER:-flat}"
TRAIN_NUM_ITERATIONS="${TRAIN_NUM_ITERATIONS:-0}"
TRAIN_TOKEN_BUDGET="${TRAIN_TOKEN_BUDGET:-}"
EVALUATION_ENABLED="${EVALUATION_ENABLED:-1}"
if [ -n "$TRAIN_TOKEN_BUDGET" ] && [ "$TRAIN_NUM_ITERATIONS" != "0" ]; then
    echo "ERROR: Token budget and fixed steps cannot be combined" >&2
    exit 2
fi


# Mid-training checkpoint output directory (where trained models are saved)
# If set, $NANOCHAT_MODEL_DIR/mid_checkpoints will be symlinked here
# to avoid filling up EVS storage with large checkpoint files
MID_CHECKPOINTS_OUTPUT_DIR="${MID_CHECKPOINTS_OUTPUT_DIR:-$HOME/.cache/nanochat_mid_compare/mid_checkpoints}"

# Experiment output directory (logs, data, reports)
RESULT_DIR="${RESULT_DIR:-$SCRIPT_DIR/results/$TIMESTAMP}"
if [ "$NODE_RANK" != "0" ]; then RESULT_DIR="$RESULT_DIR/node-$NODE_RANK"; fi
mkdir -p "$RESULT_DIR"
exec > >(tee "$RESULT_DIR/experiment.log") 2>&1

# ── Mid-training hyperparameters ──
# Training token budget: min(target_ratio * num_scaling_params, dataset_tokens)
# - If data < ratio * params: use all data (1 epoch, no overfitting)
# - If data > ratio * params: cap at ratio * params (no over-training)
# d28 model: num_scaling_params auto-detected from checkpoint meta JSON
TARGET_PARAM_DATA_RATIO="${TARGET_PARAM_DATA_RATIO:-0.5}"
NUM_SCALING_PARAMS="${NUM_SCALING_PARAMS:-}"
DEVICE_BATCH_SIZE="${DEVICE_BATCH_SIZE:-1}"
NUM_NPU="${NUM_NPU:-8}"
CORE_METRIC_EVERY="${CORE_METRIC_EVERY:--1}"
# Val BPB disabled by default (-1) because QuadMix and Random use different data,
# so their val sets are not comparable. Use CORE metric for comparison instead.
EVAL_EVERY="${EVAL_EVERY:--1}"
EVAL_BENCHMARKS="${EVAL_BENCHMARKS:-core}"

# Data preparation
SHARD_SIZE="${SHARD_SIZE:-10000}"
VAL_RATIO="${VAL_RATIO:-0}"
SEED="${SEED:-42}"
MAX_SHARDS="${MAX_SHARDS:-500}"

# Mid-training model tags (auto-generated if empty)
# The script creates a symlink from BASE_MODEL_TAG to MODEL_TAG in base_checkpoints/
# so mid_train.py loads the base model and saves to mid_checkpoints/<MODEL_TAG>/
QUADMIX_MODEL_TAG="${QUADMIX_MODEL_TAG:-}"
RANDOM_MODEL_TAG="${RANDOM_MODEL_TAG:-}"

# ══════════════════════════════════════════════════════════════
#  VALIDATION
# ══════════════════════════════════════════════════════════════

if [ -z "$QUADMIX_SAMPLED_DATA" ]; then
    echo "ERROR: QUADMIX_SAMPLED_DATA not set and no sampled_dataset found under $QUADMIX_DIR/result/"
    echo "  Run the QuaDMix pipeline first (e.g. bash scripts/demo_run_full.sh),"
    echo "  or set via: QUADMIX_SAMPLED_DATA=/path/to/sampled_dataset"
    exit 1
fi

if [ -z "$PREPARED_COMPARISON_DATA_DIR" ] && [ ! -f "$QUADMIX_SAMPLED_DATA" ] && [ ! -d "$QUADMIX_SAMPLED_DATA" ]; then
    echo "ERROR: QuadMix dataset not found: $QUADMIX_SAMPLED_DATA"
    exit 1
fi

if [ -z "$PREPARED_COMPARISON_DATA_DIR" ] && [ ! -d "$PREPROCESSED_DATA_DIR" ]; then
    echo "ERROR: Preprocessed directory not found: $PREPROCESSED_DATA_DIR"
    echo "  Set via: PREPROCESSED_DATA_DIR=/path/to/preprocessed"
    exit 1
fi

if [ ! -d "$NANOCHAT_REPO" ]; then
    echo "ERROR: Nanochat repo not found: $NANOCHAT_REPO"
    echo "  Set via: NANOCHAT_REPO=/path/to/nanochat-npu"
    exit 1
fi

BASE_CKPT_DIR="$NANOCHAT_MODEL_DIR/base_checkpoints/$BASE_MODEL_TAG"
if [ ! -d "$BASE_CKPT_DIR" ]; then
    echo "ERROR: Base model checkpoint not found: $BASE_CKPT_DIR"
    exit 1
fi

TOKENIZER_DIR="$NANOCHAT_MODEL_DIR/tokenizer"
if [ ! -f "$TOKENIZER_DIR/tokenizer.pkl" ]; then
    echo "ERROR: Tokenizer not found: $TOKENIZER_DIR/tokenizer.pkl"
    exit 1
fi

# Auto-detect NUM_SCALING_PARAMS from checkpoint meta JSON if not set
if [ -z "$NUM_SCALING_PARAMS" ]; then
    MODEL_INFO=$(python3 "$SCRIPT_DIR/get_model_info.py" \
        --ckpt-dir "$BASE_CKPT_DIR" \
        --nanochat-repo "$NANOCHAT_REPO")
    NUM_SCALING_PARAMS=$(echo "$MODEL_INFO" | grep NUM_SCALING_PARAMS | cut -d= -f2)
    CKPT_TOTAL_BATCH_SIZE=$(echo "$MODEL_INFO" | grep TOTAL_BATCH_SIZE | cut -d= -f2)
    echo "  Auto-detected: NUM_SCALING_PARAMS=$NUM_SCALING_PARAMS, TOTAL_BATCH_SIZE=$CKPT_TOTAL_BATCH_SIZE"
else
    CKPT_TOTAL_BATCH_SIZE=""
    if [ -d "$BASE_CKPT_DIR" ]; then
        CKPT_META_JSON=$(ls "$BASE_CKPT_DIR"/meta_*.json 2>/dev/null | sort | tail -1)
        if [ -n "$CKPT_META_JSON" ]; then
            CKPT_TOTAL_BATCH_SIZE=$(python3 -c "import json; print(json.load(open('$CKPT_META_JSON'))['total_batch_size'])")
        fi
    fi
fi

if [ -z "$CKPT_TOTAL_BATCH_SIZE" ]; then
    CKPT_TOTAL_BATCH_SIZE=524288
    echo "  WARNING: CKPT_TOTAL_BATCH_SIZE not found, using default 524288"
fi

# Auto-generate model tags
if [ -z "$QUADMIX_MODEL_TAG" ]; then
    QUADMIX_MODEL_TAG="${BASE_MODEL_TAG}_quadmix_${TIMESTAMP}"
fi
if [ -z "$RANDOM_MODEL_TAG" ]; then
    RANDOM_MODEL_TAG="${BASE_MODEL_TAG}_random_${TIMESTAMP}"
fi

IFS=',' read -ra QUALITY_METHOD_ARRAY <<< "$QUALITY_METHODS"

DO_QUALITY=0
if [ -n "$QUALITY_METHODS" ]; then
    DO_QUALITY=1
fi

# ══════════════════════════════════════════════════════════════
#  NPU ENVIRONMENT SETUP (from nanochat speedrun.sh)
# ══════════════════════════════════════════════════════════════

export OMP_NUM_THREADS=1
export PYTHONWARNINGS="ignore::UserWarning:torch_npu"
export WANDB_MODE=offline
export NANOCHAT_BASE_DIR="$NANOCHAT_RUNTIME_DIR"
mkdir -p "$NANOCHAT_RUNTIME_DIR"
if [ "$NANOCHAT_DISABLE_WANDB" = "1" ]; then
    export PYTHONPATH="$SCRIPT_DIR/compat/wandb_disabled:${PYTHONPATH:-}"
    export WANDB_MODE=disabled
fi

source /usr/local/Ascend/ascend-toolkit/set_env.sh

export ASCEND_HCCL_PATH=/usr/local/Ascend/ascend-toolkit/latest/hccl
export LD_LIBRARY_PATH=${ASCEND_HCCL_PATH}/lib64:${LD_LIBRARY_PATH:-}
export HCCL_CONNECT_TIMEOUT=1200
export HCCL_WHITELIST_DISABLE=1
export NCCL_IB_DISABLE=1
export NCCL_SOCKET_IFNAME=eth0

export PYTORCH_ALLOC_CONF=expandable_segments:True
export ASCEND_GLOBAL_LOG_LEVEL=3

if [ -z "${ASCEND_DEVICE_ID:-}" ] && [ -n "${LOCAL_RANK:-}" ]; then
    export ASCEND_DEVICE_ID=$LOCAL_RANK
elif [ -z "${ASCEND_DEVICE_ID:-}" ]; then
    export ASCEND_DEVICE_ID=0
fi

ASCEND_DEVICE_LIST=$(seq -s, 0 $((NUM_NPU - 1)))
export ASCEND_VISIBLE_DEVICES="$ASCEND_DEVICE_LIST"
export HCCL_EXEC_TIMEOUT=1200
export ASCEND_DISABLE_MEM_SWAP=1
export ASCEND_LAUNCH_BLOCKING=0
export NPU_DISABLE_RECORD=1
export PYTHONUNBUFFERED=1
export ASCEND_COMPILE_OPT_LEVEL=O3
export TORCH_NPU_LAZY_COMPILE=1
export PYTHONPRELOAD=torch_npu
export TORCH_NPU_ALLOC_CONF="expandable_segments:True,max_split_size_mb:256,memory_pool:True"
export PYTORCH_NPU_ALLOC_MAX_SIZE=60G
export ASCEND_ENABLE_CACHE=1
export ASCEND_CACHE_POLICY=2
export ASCEND_FUSION_ENABLE=1
export ASCEND_GEMM_DTiling=1
export TORCH_NPU_ENABLE_NUMA=1
export ASCEND_MEMORY_COPY_MODE=1
export ASCEND_HBM_ALLOC_TYPE=1
export ASCEND_OPP_LEVEL=O3
export ASCEND_FUSION_PASS_ENABLE=1
export ASCEND_GEMM_BTiling=1
export ASCEND_GEMM_ATiling=1
export ASCEND_CONV_ALGO_SELECTION=1
export ASCEND_ENABLE_TRANSFORMER_FUSION=1
export ASCEND_MEMORY_REUSE_MODE=2
export ASCEND_ENABLE_PREFETCH=1
export ASCEND_NPU_ENABLE_UNIFIED_MEMORY=1
export ASCEND_OPTIMIZER_AGGRESSIVE_MODE=1
export ASCEND_SYNCHRONIZATION_MODE=0
export PYTORCH_NPU_ENABLE_LARGE_CONCAT=1
export PYTORCH_NPU_ENABLE_TORCHscript=1
export NPU_PERF_MODE=high_performance
export NANOCHAT_DTYPE=bfloat16
export PYTHONWARNINGS="ignore::UserWarning:torch_npu.utils.collect_env,ignore::UserWarning:torch_npu.utils._path_manager"

# ══════════════════════════════════════════════════════════════
#  PRINT CONFIG
# ══════════════════════════════════════════════════════════════

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  QuadMix vs Random — Nanochat Mid-Training Comparison"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "  QuadMix dataset:     $QUADMIX_SAMPLED_DATA"
echo "  Preprocessed dir:    $PREPROCESSED_DATA_DIR"
echo "  Nanochat model dir:  $NANOCHAT_MODEL_DIR"
echo "  Nanochat repo:       $NANOCHAT_REPO"
echo "  Base model tag:      $BASE_MODEL_TAG (source for all runs)"
echo "  Experiment output:   $RESULT_DIR"
if [ -n "$MID_CHECKPOINTS_OUTPUT_DIR" ]; then
    echo "  Mid checkpoint output: $MID_CHECKPOINTS_OUTPUT_DIR"
fi
if [ "$DO_QUALITY" -eq 1 ]; then
    echo "  Quality methods:     ${QUALITY_METHOD_ARRAY[*]}"
else
    echo "  Quality baseline:    DISABLED (set QUALITY_METHODS to enable)"
fi
echo ""
echo "  Mid-training config:"
echo "    target-param-data-ratio: $TARGET_PARAM_DATA_RATIO"
echo "    num-scaling-params:      $NUM_SCALING_PARAMS"
echo "    device-batch-size:       $DEVICE_BATCH_SIZE"
echo "    NPU cards:               $NUM_NPU"
echo "    eval-benchmarks:         $EVAL_BENCHMARKS"
echo ""
echo "  Model tags (save):"
echo "    QuadMix: $QUADMIX_MODEL_TAG"
echo "    Random:  $RANDOM_MODEL_TAG"
if [ "$DO_QUALITY" -eq 1 ]; then
    for method in "${QUALITY_METHOD_ARRAY[@]}"; do
        echo "    Quality ($method): ${BASE_MODEL_TAG}_quality_${method}_${TIMESTAMP}"
    done
fi
echo ""
echo "════════════════════════════════════════════════════════════"
echo ""

mkdir -p "$RESULT_DIR"

DATA_DIR="${PREPARED_COMPARISON_DATA_DIR:-$RESULT_DIR/data}"

# ══════════════════════════════════════════════════════════════
#  STEP 1: DATA PREPARATION
# ══════════════════════════════════════════════════════════════

echo ""
echo "╔══ Step 1: Prepare datasets ══╗"
echo ""

if [ -n "$PREPARED_COMPARISON_DATA_DIR" ]; then
    test -f "$DATA_DIR/dataset_stats.json" || { echo "ERROR: missing dataset_stats.json" >&2; exit 1; }
else
PREP_ARGS=(
    --quadmix-sampled-data "$QUADMIX_SAMPLED_DATA"
    --preprocessed-data-dir "$PREPROCESSED_DATA_DIR"
    --output-dir "$DATA_DIR"
    --tokenizer-pkl "$TOKENIZER_DIR/tokenizer.pkl"
    --data-ratio "$TARGET_PARAM_DATA_RATIO"
    --num-scaling-params "$NUM_SCALING_PARAMS"
    --shard-size "$SHARD_SIZE"
    --val-ratio "$VAL_RATIO"
    --seed "$SEED"
    --max-shards "$MAX_SHARDS"
    --num-npu "${AMT_DATA_WORLD_SIZE:-$RANK_SIZE}"
)
if [ "$DO_QUALITY" -eq 1 ]; then
    PREP_ARGS+=(--quality-method "$QUALITY_METHODS")
fi
python3 "$SCRIPT_DIR/prepare_data.py" "${PREP_ARGS[@]}"

fi
if [ "$PREPARE_ONLY" = "1" ]; then exit 0; fi

cp "$DATA_DIR/dataset_stats.json" "$RESULT_DIR/dataset_stats.json"
STATS_FILE="$RESULT_DIR/dataset_stats.json" DATA_DIR="$DATA_DIR" BASE_MODEL_TAG="$BASE_MODEL_TAG" \
TARGET_PARAM_DATA_RATIO="$TARGET_PARAM_DATA_RATIO" \
NUM_SCALING_PARAMS="$NUM_SCALING_PARAMS" \
DEVICE_BATCH_SIZE="$DEVICE_BATCH_SIZE" \
NUM_NPU="$NUM_NPU" \
TOTAL_BATCH_SIZE="${CKPT_TOTAL_BATCH_SIZE:-524288}" \
TOKENIZER_PKL="$TOKENIZER_DIR/tokenizer.pkl" \
NANOCHAT_REPO="$NANOCHAT_REPO" \
NANOCHAT_MODEL_DIR="$NANOCHAT_MODEL_DIR" \
MID_CHECKPOINTS_OUTPUT_DIR="$MID_CHECKPOINTS_OUTPUT_DIR" \
QUADMIX_GIT_HASH="$(git -C "$QUADMIX_DIR" rev-parse --short HEAD 2>/dev/null || echo 'unknown')" \
NANOCHAT_GIT_HASH="$(git -C "$NANOCHAT_REPO" rev-parse --short HEAD 2>/dev/null || echo 'unknown')" \
EVAL_BENCHMARKS="$EVAL_BENCHMARKS" \
python3 -c "
import os, json
stats_path = os.environ['STATS_FILE']
stats = json.load(open(stats_path))
stats['config'].update({
    'base_model_tag': os.environ['BASE_MODEL_TAG'],
    'target_param_data_ratio': float(os.environ['TARGET_PARAM_DATA_RATIO']),
    'num_scaling_params': int(os.environ['NUM_SCALING_PARAMS']),
    'device_batch_size': int(os.environ['DEVICE_BATCH_SIZE']),
    'total_batch_size': int(os.environ['TOTAL_BATCH_SIZE']),
    'num_npu': int(os.environ['NUM_NPU']),
    'tokenizer_pkl': os.environ.get('TOKENIZER_PKL', ''),
    'nanochat_repo': os.environ.get('NANOCHAT_REPO', ''),
    'nanochat_model_dir': os.environ.get('NANOCHAT_MODEL_DIR', ''),
    'mid_checkpoints_output_dir': os.environ.get('MID_CHECKPOINTS_OUTPUT_DIR', ''),
    'quadmix_git_hash': os.environ.get('QUADMIX_GIT_HASH', ''),
    'nanochat_git_hash': os.environ.get('NANOCHAT_GIT_HASH', ''),
    'eval_benchmarks': os.environ.get('EVAL_BENCHMARKS', ''),
})
with open(stats_path, 'w') as f:
    json.dump(stats, f, indent=2)
"

echo ""
echo "  Dataset stats:"
DATA_DIR="$DATA_DIR" python3 -c "
import os, json
stats = json.load(open(os.path.join(os.environ['DATA_DIR'], 'dataset_stats.json')))
q, r = stats.get('quadmix', {}), stats.get('random', {})
method = stats['config'].get('token_method', 'unknown')
print(f'    Token method: {method}')
print(f'    QuadMix: {q.get(\"train_docs\", 0):,} train docs, {q.get(\"tokens\", 0):,} tokens, {q.get(\"shards\", 0)} shards')
print(f'    Random:  {r.get(\"train_docs\", 0):,} train docs, {r.get(\"tokens\", 0):,} tokens, {r.get(\"shards\", 0)} shards')
for key in stats:
    if key.startswith('quality_'):
        method = key[len('quality_'):]
        ql = stats[key]
        print(f'    Quality ({method}): {ql[\"train_docs\"]:,} train docs, {ql[\"tokens\"]:,} tokens, {ql[\"shards\"]} shards')
print(f'    Shared val: {q.get(\"val_docs\", 0):,} docs')
"
echo ""
echo "╚════════════════════════════════╗"
echo ""

# ══════════════════════════════════════════════════════════════
#  STEP 2: SETUP MID_CHECKPOINTS DIRECTORY
# ══════════════════════════════════════════════════════════════

python3 "$SCRIPT_DIR/distributed_runtime.py" layout \
    --directory "$NANOCHAT_MODEL_DIR" --output "$NANOCHAT_RUNTIME_DIR" \
    --checkpoint-dir "$MID_CHECKPOINTS_OUTPUT_DIR" \
    --eval-bundle "${NANOCHAT_EVAL_BUNDLE_DIR:-}"
if [ -n "${NANOCHAT_EVAL_BUNDLE_DIR:-}" ]; then
    python3 "$SCRIPT_DIR/prepare_offline_eval_bundle.py" "$NANOCHAT_EVAL_BUNDLE_DIR" "$NANOCHAT_RUNTIME_DIR"
fi

# ══════════════════════════════════════════════════════════════
#  PRE-FLIGHT: DISK SPACE CHECK
# ══════════════════════════════════════════════════════════════

echo ""
echo "╔══ Pre-flight: Disk space check ══╗"
echo ""

CKPT_DIR="${MID_CHECKPOINTS_OUTPUT_DIR}"
mkdir -p "$CKPT_DIR"

AVAILABLE_KB=$(df -P "$CKPT_DIR" | awk 'NR==2{print $4}')
AVAILABLE_GB=$((AVAILABLE_KB / 1024 / 1024))
MIN_REQUIRED_GB=60

echo "  Checkpoint dir:  $CKPT_DIR"
echo "  Available space: ${AVAILABLE_GB}GB"
echo "  Minimum needed:  ${MIN_REQUIRED_GB}GB (3+ trainings × ~20GB/ckpt)"

if [ "$AVAILABLE_GB" -lt "$MIN_REQUIRED_GB" ]; then
    echo ""
    echo "  ERROR: Insufficient disk space!"
    echo "  Available: ${AVAILABLE_GB}GB < Required: ${MIN_REQUIRED_GB}GB"
    echo ""
    echo "  Options:"
    echo "    1. Set MID_CHECKPOINTS_OUTPUT_DIR to a partition with more space:"
    echo "       MID_CHECKPOINTS_OUTPUT_DIR=/path/to/larger/disk bash nanochat_mid_compare/run_experiment.sh"
    echo "    2. Free up space on the current partition"
    echo ""
    echo "╚══════════════════════════════════════════════════════════╝"
    exit 1
fi

echo "  ✓ Disk space sufficient"
echo ""
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ══════════════════════════════════════════════════════════════
#  PRE-FLIGHT: DOWNLOAD EVAL DATA
# ══════════════════════════════════════════════════════════════

echo ""
echo "╔══ Pre-flight: Download eval data ══╗"
echo ""
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
pushd "$NANOCHAT_REPO" > /dev/null
if ! python3 -c "import rustbpe" >/dev/null 2>&1; then
    export PYTHONPATH="$SCRIPT_DIR/compat:${PYTHONPATH:-}"
fi
if [ "${NANOCHAT_SKIP_EVAL_DOWNLOAD:-0}" = "1" ]; then
    export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
    if [ "$EVALUATION_ENABLED" = "1" ] || [ "$CORE_METRIC_EVERY" != "-1" ]; then
        python3 "$SCRIPT_DIR/eval_assets.py" --base "$NANOCHAT_RUNTIME_DIR" \
            --repo "$NANOCHAT_REPO" --benchmarks "$EVAL_BENCHMARKS"
    fi
else
    python3 -c "from scripts.base_eval import prepare_eval_data; prepare_eval_data('${EVAL_BENCHMARKS:-all}')"
fi
popd > /dev/null
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ══════════════════════════════════════════════════════════════
#  STEP 3: MID-TRAINING
# ══════════════════════════════════════════════════════════════

QUADMIX_DATA="$DATA_DIR/quadmix_data"
RANDOM_DATA="$DATA_DIR/random_data"

run_mid_training() {
    local DATA_PATH="$1"
    local MODEL_TAG="$2"
    local RUN_NAME="$3"
    local LOG_FILE="$4"
    local DATASET_TOKENS="$5"
    local TRAIN_TOKENS="$6"

    if [ ! -d "$DATA_PATH" ]; then
        echo "    ERROR: Data directory does not exist: $DATA_PATH"
        return 1
    fi

    local PLAN_FILE="$RESULT_DIR/training_plan_$MODEL_TAG.json"
    local TOTAL_BATCH_SIZE MAX_SEQ_LEN NUM_ITERATIONS PLAN_ENV
    PLAN_ENV=$(python3 "$SCRIPT_DIR/distributed_runtime.py" plan \
        --directory "$BASE_CKPT_DIR" --repo "$NANOCHAT_REPO" --devices "$NUM_NPU" \
        --tokens "$TRAIN_TOKENS" --steps "$TRAIN_NUM_ITERATIONS" \
        --device-batch-size "$DEVICE_BATCH_SIZE" \
        --total-batch-size "${TRAIN_TOTAL_BATCH_SIZE:-$CKPT_TOTAL_BATCH_SIZE}" \
        --output "$PLAN_FILE")
    eval "$PLAN_ENV"
    local DATA_CHECK_ARGS=(check-data --directory "$DATA_PATH" --devices "$NUM_NPU")
    if [ "$EVAL_EVERY" != "-1" ]; then DATA_CHECK_ARGS+=(--validation); fi
    python3 "$SCRIPT_DIR/distributed_runtime.py" "${DATA_CHECK_ARGS[@]}"
    local TRACKING_RUN_NAME="$RUN_NAME"
    if [ "$NANOCHAT_DISABLE_WANDB" = "1" ]; then TRACKING_RUN_NAME=dummy; fi

    echo "  Starting mid-training: $RUN_NAME"
    echo "    Data:       $DATA_PATH"
    echo "    Source:     $BASE_MODEL_TAG (base)"
    echo "    Save as:    $MODEL_TAG (mid)"
    echo "    Dataset:    $DATASET_TOKENS tokens"
    echo "    Train:      $TRAIN_TOKENS tokens (budget_cap, ratio=$TARGET_PARAM_DATA_RATIO)"
    echo "    Steps:      $NUM_ITERATIONS"
    echo "    Log:        $LOG_FILE"

    local LINK_DIR="$NANOCHAT_RUNTIME_DIR/base_checkpoints/$MODEL_TAG"

    if [ ! -e "$LINK_DIR" ]; then
        echo "    Creating symlink: $LINK_DIR -> $BASE_CKPT_DIR"
        ln -s "$BASE_CKPT_DIR" "$LINK_DIR"
    fi

    trap 'if [ -L "$LINK_DIR" ]; then echo "    Cleaning up symlink on exit: $LINK_DIR"; rm "$LINK_DIR"; fi' RETURN

    pushd "$NANOCHAT_REPO" > /dev/null
    export PYTHONPATH="$QUADMIX_DIR:${PYTHONPATH:-}"
    python3 -m torch.distributed.run "${TORCHRUN_ARGS[@]}" -m nanochat_mid_compare.run_nanochat_mid_train -- \
        --num-iterations="$NUM_ITERATIONS" \
        --target-param-data-ratio="$TARGET_PARAM_DATA_RATIO" \
        --device-batch-size="$DEVICE_BATCH_SIZE" \
        --total-batch-size="$TOTAL_BATCH_SIZE" \
        --max-seq-len="$MAX_SEQ_LEN" \
        --load-optimizer="$NANOCHAT_LOAD_OPTIMIZER" \
        --loader="$LOADER" \
        --sample-every=-1 \
        --run="$TRACKING_RUN_NAME" \
        --model-tag="$MODEL_TAG" \
        --core-metric-every="$CORE_METRIC_EVERY" \
        --eval-every="$EVAL_EVERY" \
        --eval-benchmarks="$EVAL_BENCHMARKS" \
        --data-dir="$DATA_PATH" \
        2>&1 | tee "$LOG_FILE"
    popd > /dev/null
    python3 "$SCRIPT_DIR/distributed_runtime.py" record \
        --directory "$MID_CHECKPOINTS_OUTPUT_DIR/$MODEL_TAG" --devices "$NUM_NPU" \
        --phase "mid:$MODEL_TAG" --plan-file "$PLAN_FILE" --repo "$NANOCHAT_REPO" --data-directory "$DATA_PATH"
}

STATS_FILE="$DATA_DIR/dataset_stats.json"
BUDGET_CAP=$(STATS_FILE="$STATS_FILE" python3 -c "
import os, json
s = json.load(open(os.environ['STATS_FILE']))
print(s['config'].get('training_budget', s['config'].get('budget_cap', '0')))
")
if [ -n "$TRAIN_TOKEN_BUDGET" ]; then BUDGET_CAP="$TRAIN_TOKEN_BUDGET"; fi
if [ "$BUDGET_CAP" -le 0 ] 2>/dev/null || [ -z "$BUDGET_CAP" ]; then
    echo "ERROR: budget_cap is missing or zero in dataset_stats.json" >&2
    echo "       Delete $DATA_DIR and re-run prepare_data to regenerate." >&2
    exit 1
fi
read -r QUADMIX_TOKENS RANDOM_TOKENS < <(
    STATS_FILE="$STATS_FILE" python3 -c "
import os, json
s = json.load(open(os.environ['STATS_FILE']))
print(*(s.get(key, {}).get('tokens', 0) for key in ('quadmix', 'random')))
"
)
echo "  Common training budget: $BUDGET_CAP tokens (from budget_cap)"

echo ""
echo "╔══ Step 3a: Mid-training on QuadMix data ══╗"
echo ""

QUADMIX_LOG="$RESULT_DIR/mid_train_quadmix.log"
if has_method quadmix; then
    run_mid_training "$QUADMIX_DATA" "$QUADMIX_MODEL_TAG" "quadmix_mid" "$QUADMIX_LOG" "$QUADMIX_TOKENS" "$BUDGET_CAP"
fi

echo ""
echo "╚════════════════════════════════════════════╝"
echo ""

echo ""
echo "╔══ Step 3b: Mid-training on Random data ══╗"
echo ""

RANDOM_LOG="$RESULT_DIR/mid_train_random.log"
if has_method random; then
    run_mid_training "$RANDOM_DATA" "$RANDOM_MODEL_TAG" "random_mid" "$RANDOM_LOG" "$RANDOM_TOKENS" "$BUDGET_CAP"
fi

echo ""
echo "╚═══════════════════════════════════════════╝"
echo ""

if [ "$DO_QUALITY" -eq 1 ]; then
    for method in "${QUALITY_METHOD_ARRAY[@]}"; do
        echo ""
        echo "╔══ Step 3c: Mid-training on Quality Top-K ($method) data ══╗"
        echo ""

        QUALITY_DATA="$DATA_DIR/quality_data_${method}"
        QUALITY_MODEL_TAG="${BASE_MODEL_TAG}_quality_${method}_${TIMESTAMP}"
        QUALITY_LOG="$RESULT_DIR/mid_train_quality_${method}.log"
        QUALITY_TOKENS=$(STATS_FILE="$STATS_FILE" METHOD="$method" python3 -c "
import os, json
s = json.load(open(os.environ['STATS_FILE']))
print(s[f'quality_{os.environ[\"METHOD\"]}']['tokens'])
")
        run_mid_training "$QUALITY_DATA" "$QUALITY_MODEL_TAG" "quality_${method}_mid" "$QUALITY_LOG" "$QUALITY_TOKENS" "$BUDGET_CAP"

        echo ""
        echo "╚════════════════════════════════════════════════╝"
        echo ""
    done
fi

# ══════════════════════════════════════════════════════════════
#  STEP 4: EVALUATION
# ══════════════════════════════════════════════════════════════

if [ "${AMT_TRAIN_ONLY:-0}" = "1" ]; then exit 0; fi
if [ "$NODE_RANK" != "0" ] && [ "$EVALUATION_ENABLED" = "1" ]; then
    mkdir -p "$NANOCHAT_RUNTIME_DIR/eval_checkpoints"
    install_shared_symlink "$NANOCHAT_RUNTIME_DIR/eval_checkpoints" "$NANOCHAT_RUNTIME_DIR/mid_checkpoints"
fi

run_eval() {
    if [ "$EVALUATION_ENABLED" != "1" ]; then
        echo "Evaluation disabled by workflow configuration"
        return 0
    fi
    local MODEL_TAG="$1"
    local MODEL_TYPE="$2"
    local LOG_FILE="$3"
    local CHECKPOINT_STEP

    echo "  Evaluating: $MODEL_TAG ($MODEL_TYPE)"

    CHECKPOINT_STEP=$(python3 "$SCRIPT_DIR/distributed_runtime.py" checkpoint \
        --directory "$NANOCHAT_RUNTIME_DIR/${MODEL_TYPE}_checkpoints/$MODEL_TAG" \
        --phase "$MODEL_TYPE:$MODEL_TAG" --devices "$NUM_NPU")

    python3 "$SCRIPT_DIR/distributed_runtime.py" settle --devices "$NUM_NPU"
    pushd "$NANOCHAT_REPO" > /dev/null
    HCCL_BUFFSIZE="${HCCL_BUFFSIZE:-100}" python3 -m torch.distributed.run "${EVAL_TORCHRUN_ARGS[@]}" -m nanochat_mid_compare.offline_base_eval \
        --eval=core \
        --eval-benchmarks="$EVAL_BENCHMARKS" \
        --device-batch-size=16 \
        --model-tag="$MODEL_TAG" \
        --step="$CHECKPOINT_STEP" \
        --model-type="$MODEL_TYPE" \
        2>&1 | tee "$LOG_FILE"
    popd > /dev/null
}

echo ""
echo "╔══ Step 4: Evaluation ══╗"
echo ""

QUADMIX_EVAL_LOG="$RESULT_DIR/eval_quadmix.log"
if has_method quadmix; then run_eval "$QUADMIX_MODEL_TAG" "mid" "$QUADMIX_EVAL_LOG"; fi

RANDOM_EVAL_LOG="$RESULT_DIR/eval_random.log"
if has_method random; then run_eval "$RANDOM_MODEL_TAG" "mid" "$RANDOM_EVAL_LOG"; fi

if [ "$DO_QUALITY" -eq 1 ]; then
    for method in "${QUALITY_METHOD_ARRAY[@]}"; do
        QUALITY_MODEL_TAG="${BASE_MODEL_TAG}_quality_${method}_${TIMESTAMP}"
        QUALITY_EVAL_LOG="$RESULT_DIR/eval_quality_${method}.log"
        run_eval "$QUALITY_MODEL_TAG" "mid" "$QUALITY_EVAL_LOG"
    done
fi

echo ""
echo "╚══════════════════════════════════════════╝"
echo ""

# ══════════════════════════════════════════════════════════════
#  STEP 5: GENERATE REPORT
# ══════════════════════════════════════════════════════════════

echo ""
echo "╔══ Step 5: Generate experiment report ══╗"
echo ""

if [ "$NODE_RANK" != "0" ]; then exit 0; fi

REPORT_ARGS=(
    --result-dir "$RESULT_DIR"
    --dataset-stats "$RESULT_DIR/dataset_stats.json"
    --quadmix-train-log "$QUADMIX_LOG"
    --random-train-log "$RANDOM_LOG"
    --quadmix-eval-log "$QUADMIX_EVAL_LOG"
    --random-eval-log "$RANDOM_EVAL_LOG"
)
if [ "$DO_QUALITY" -eq 1 ]; then
    QUALITY_TRAIN_LOGS=()
    QUALITY_EVAL_LOGS=()
    for method in "${QUALITY_METHOD_ARRAY[@]}"; do
        QUALITY_TRAIN_LOGS+=("$RESULT_DIR/mid_train_quality_${method}.log")
        QUALITY_EVAL_LOGS+=("$RESULT_DIR/eval_quality_${method}.log")
    done
    REPORT_ARGS+=(--quality-train-log "${QUALITY_TRAIN_LOGS[@]}")
    REPORT_ARGS+=(--quality-eval-log "${QUALITY_EVAL_LOGS[@]}")
fi
python3 "$SCRIPT_DIR/generate_report.py" "${REPORT_ARGS[@]}"

echo ""
echo "╚════════════════════════════════════════╝"
echo ""

# ══════════════════════════════════════════════════════════════
#  SUMMARY
# ══════════════════════════════════════════════════════════════

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  Experiment Complete!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "  Output directory: $RESULT_DIR"
echo ""
echo "  Files:"
echo "    ├── data/                    # Training datasets"
echo "    │   ├── quadmix_data/        # QuadMix-selected shards"
echo "    │   ├── random_data/         # Random baseline shards"
if [ "$DO_QUALITY" -eq 1 ]; then
    for method in "${QUALITY_METHOD_ARRAY[@]}"; do
        echo "    │   ├── quality_data_${method}/  # Quality ($method) shards"
    done
fi
echo "    │   └── dataset_stats.json   # Dataset statistics"
echo "    ├── experiment.log          # Full experiment log (all output)"
echo "    ├── mid_train_quadmix.log    # QuadMix mid-training log"
echo "    ├── mid_train_random.log     # Random mid-training log"
if [ "$DO_QUALITY" -eq 1 ]; then
    for method in "${QUALITY_METHOD_ARRAY[@]}"; do
        echo "    ├── mid_train_quality_${method}.log  # Quality ($method) training log"
    done
fi
echo "    ├── eval_quadmix.log         # QuadMix evaluation log"
echo "    ├── eval_random.log          # Random evaluation log"
if [ "$DO_QUALITY" -eq 1 ]; then
    for method in "${QUALITY_METHOD_ARRAY[@]}"; do
        echo "    ├── eval_quality_${method}.log     # Quality ($method) evaluation log"
    done
fi
echo "    └── experiment_report.md     # Comparison report"
echo ""
echo "  Mid-training checkpoints:"
echo "    $MID_CHECKPOINTS_OUTPUT_DIR/$QUADMIX_MODEL_TAG/"
echo "    $MID_CHECKPOINTS_OUTPUT_DIR/$RANDOM_MODEL_TAG/"
if [ "$DO_QUALITY" -eq 1 ]; then
    for method in "${QUALITY_METHOD_ARRAY[@]}"; do
        echo "    $MID_CHECKPOINTS_OUTPUT_DIR/${BASE_MODEL_TAG}_quality_${method}_${TIMESTAMP}/"
    done
fi
echo ""
echo "════════════════════════════════════════════════════════════"
