#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
# QuadMix Mid-Training — Standalone Quick Validation
# ──────────────────────────────────────────────────────────────
#
# Runs ONLY the QuadMix mid-training + CORE eval.
#
# Usage:
#   bash nanochat_mid_compare/run_quadmix_only.sh \
#     --data-dir /path/to/sampled_dataset
#
# Or reuse previously prepared data:
#   bash nanochat_mid_compare/run_quadmix_only.sh \
#     --data-dir nanochat_mid_compare/results/20250620_120000/data
#
# ──────────────────────────────────────────────────────────────

set -euo pipefail

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


# ══════════════════════════════════════════════════════════════
#  CLI ARGUMENTS
# ══════════════════════════════════════════════════════════════

DATA_DIR=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --data-dir) DATA_DIR="$2"; shift 2 ;;
        *) echo "Unknown argument: $1"; exit 1 ;;
    esac
done

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════

NANOCHAT_MODEL_DIR="${NANOCHAT_MODEL_DIR:-/home/ma-user/work/nanochat_model_dir}"
BASE_MODEL_TAG="${BASE_MODEL_TAG:-d28}"
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

MID_CHECKPOINTS_OUTPUT_DIR="${MID_CHECKPOINTS_OUTPUT_DIR:-$HOME/.cache/nanochat_mid_compare/mid_checkpoints}"
RESULT_DIR="${RESULT_DIR:-$SCRIPT_DIR/results/quadmix_only_$TIMESTAMP}"
if [ "$NODE_RANK" != "0" ]; then
    RESULT_DIR="$RESULT_DIR/node-$NODE_RANK"
fi
mkdir -p "$RESULT_DIR"
exec > >(tee "$RESULT_DIR/experiment.log") 2>&1

TARGET_PARAM_DATA_RATIO="${TARGET_PARAM_DATA_RATIO:-0.5}"
NUM_SCALING_PARAMS="${NUM_SCALING_PARAMS:-}"
DEVICE_BATCH_SIZE="${DEVICE_BATCH_SIZE:-1}"
CORE_METRIC_EVERY="${CORE_METRIC_EVERY:--1}"
EVAL_EVERY="${EVAL_EVERY:--1}"
EVAL_BENCHMARKS="${EVAL_BENCHMARKS:-all}"
SHARD_SIZE="${SHARD_SIZE:-10000}"

QUADMIX_MODEL_TAG="${QUADMIX_MODEL_TAG:-${BASE_MODEL_TAG}_quadmix_${TIMESTAMP}}"

# ══════════════════════════════════════════════════════════════
#  VALIDATION & AUTO-DETECT
# ══════════════════════════════════════════════════════════════

if [ ! -d "$NANOCHAT_REPO" ]; then
    echo "ERROR: Nanochat repo not found: $NANOCHAT_REPO"
    exit 1
fi

BASE_CKPT_DIR="$NANOCHAT_MODEL_DIR/base_checkpoints/$BASE_MODEL_TAG"
if [ ! -d "$BASE_CKPT_DIR" ]; then
    echo "ERROR: Base model checkpoint not found: $BASE_CKPT_DIR"
    exit 1
fi

if [ -z "$NUM_SCALING_PARAMS" ]; then
    MODEL_INFO=$(python3 "$SCRIPT_DIR/get_model_info.py" \
        --ckpt-dir "$BASE_CKPT_DIR" \
        --nanochat-repo "$NANOCHAT_REPO")
    NUM_SCALING_PARAMS=$(echo "$MODEL_INFO" | grep NUM_SCALING_PARAMS | cut -d= -f2)
    CKPT_TOTAL_BATCH_SIZE=$(echo "$MODEL_INFO" | grep TOTAL_BATCH_SIZE | cut -d= -f2)
    echo "  Auto-detected: NUM_SCALING_PARAMS=$NUM_SCALING_PARAMS, TOTAL_BATCH_SIZE=$CKPT_TOTAL_BATCH_SIZE"
else
    CKPT_META_JSON=$(ls "$BASE_CKPT_DIR"/meta_*.json 2>/dev/null | sort | tail -1)
    CKPT_TOTAL_BATCH_SIZE=""
    if [ -n "$CKPT_META_JSON" ]; then
        CKPT_TOTAL_BATCH_SIZE=$(python3 -c "import json; print(json.load(open('$CKPT_META_JSON'))['total_batch_size'])")
    fi
fi

if [ -z "$CKPT_TOTAL_BATCH_SIZE" ]; then
    CKPT_TOTAL_BATCH_SIZE=524288
    echo "  WARNING: CKPT_TOTAL_BATCH_SIZE not found, using default 524288"
fi

# ══════════════════════════════════════════════════════════════
#  DATA PREPARATION
# ══════════════════════════════════════════════════════════════

TOKENIZER_PKL="$NANOCHAT_MODEL_DIR/tokenizer/tokenizer.pkl"

if [ -z "$DATA_DIR" ]; then
    DATA_DIR="$(ls -dt "$SCRIPT_DIR"/results/*/data 2>/dev/null | head -1)"
    DATA_DIR="${DATA_DIR:-}"
fi

if [ -z "$DATA_DIR" ]; then
    echo "ERROR: No data source specified."
    echo "  Usage: $0 --data-dir /path/to/sampled_dataset"
    echo "     or: $0 --data-dir /path/to/prepared/data/dir"
    exit 1
fi

PREPARED_DATA_DIR=""

DATA_SOURCE="$DATA_DIR"

if { [ -f "$DATA_DIR" ] && [[ "$DATA_DIR" == *.parquet ]]; } || \
   { [ -d "$DATA_DIR" ] && find "$DATA_DIR" -maxdepth 1 -name '*.parquet' -print -quit | grep -q .; }; then
    echo "╔══ Preparing training data from parquet ══╗"
    echo ""
    echo "  Source: $DATA_DIR"

    PREPARED_DATA_DIR="$RESULT_DIR/data"
    QUADMIX_DATA="$PREPARED_DATA_DIR/quadmix_data"
    mkdir -p "$QUADMIX_DATA"

    QUADMIX_TOKENS=$(DATA_DIR="$DATA_DIR" TOKENIZER_PKL="$TOKENIZER_PKL" SHARD_SIZE="$SHARD_SIZE" \
        NUM_NPU="$RANK_SIZE" QUADMIX_DATA="$QUADMIX_DATA" PREPARED_DATA_DIR="$PREPARED_DATA_DIR" \
        SCRIPT_DIR="$SCRIPT_DIR" MAX_CHARS="${MAX_CHARS:-1000000}" \
        MAX_CHAR_REPEAT_RATIO="${MAX_CHAR_REPEAT_RATIO:-0.3}" \
        python3 -c "
import os, sys, json, multiprocessing as mp, pyarrow.parquet as pq, pyarrow as pa
from tqdm import tqdm
sys.path.insert(0, os.environ['SCRIPT_DIR'])
from prepare_data import count_tokens_mp, _filter_docs_chunk, _SPAWN_CTX
from quadmix.sampling.sources import resolve_parquet_source

src = os.environ['DATA_DIR']
out_dir = os.environ['QUADMIX_DATA']
stats_dir = os.environ['PREPARED_DATA_DIR']
shard_size = int(os.environ['SHARD_SIZE'])
num_npu = int(os.environ['NUM_NPU'])
tokenizer_pkl = os.environ['TOKENIZER_PKL']
max_chars = int(os.environ['MAX_CHARS'])
max_char_repeat_ratio = float(os.environ['MAX_CHAR_REPEAT_RATIO'])

print(f'  Reading {src}...')
# A sampled-dataset directory also contains manifest.json. Passing the whole
# directory to PyArrow makes it try to parse that JSON file as Parquet.
table = pq.read_table(resolve_parquet_source(src), columns=['text'])
raw_texts = table['text'].to_pylist()

num_workers = min(mp.cpu_count(), 128) or 1
chunk_size = max(1, len(raw_texts) // (num_workers * 4))
chunks = [raw_texts[i:i + chunk_size] for i in range(0, len(raw_texts), chunk_size)]
filter_tasks = [(c, max_chars, max_char_repeat_ratio) for c in chunks]
texts = []
n_empty = 0
n_too_long = 0
n_repeat = 0
with _SPAWN_CTX.Pool(num_workers) as pool:
    for valid, ne, tl, tr in tqdm(
        pool.imap_unordered(_filter_docs_chunk, filter_tasks, chunksize=1),
        total=len(filter_tasks),
        desc=f'  Filtering ({num_workers} processes)',
    ):
        texts.extend(valid)
        n_empty += ne
        n_too_long += tl
        n_repeat += tr
n_filtered = n_empty + n_too_long + n_repeat
if n_filtered > 0:
    print(f'  Filtered {n_empty:,} docs (empty), '
          f'{n_too_long:,} docs (>{max_chars:,} chars), '
          f'{n_repeat:,} docs (single char >{max_char_repeat_ratio*100:.0f}% repetition)')
print(f'  Valid docs: {len(texts):,}')

token_method = 'char_count // 4 (estimate)'
if os.path.exists(tokenizer_pkl):
    token_method = 'nanochat tokenizer'

if os.path.exists(tokenizer_pkl):
    print(f'  Counting tokens ({token_method}, multiprocessing)...')
    token_counts = count_tokens_mp(texts, tokenizer_pkl)
else:
    print(f'  Estimating tokens ({token_method})...')
    token_counts = [len(t) // 4 for t in texts]

total_tokens = sum(token_counts)
print(f'  Total tokens: {total_tokens:,}')

n_shards = max(1, (len(texts) + shard_size - 1) // shard_size)
rg_size = max(1, shard_size // (num_npu * 2))
for i in range(n_shards):
    start = i * shard_size
    end = min(start + shard_size, len(texts))
    shard_texts = texts[start:end]
    shard_table = pa.table({'text': shard_texts})
    out_path = os.path.join(out_dir, f'shard_{i:05d}.parquet')
    pq.write_table(shard_table, out_path, row_group_size=rg_size)

dummy_val = pa.table({'text': ['dummy']})
val_path = os.path.join(out_dir, f'shard_{n_shards:05d}.parquet')
pq.write_table(dummy_val, val_path, row_group_size=1)

stats = {
    'quadmix': {
        'train_docs': len(texts),
        'val_docs': 0,
        'tokens': total_tokens,
        'shards': n_shards,
    },
    'config': {
        'seed': 42,
        'shard_size': shard_size,
        'val_ratio': 0,
        'token_method': token_method,
        'quadmix_source': src,
        'tokenizer_pkl': tokenizer_pkl,
        'baselines': ['quadmix'],
    }
}
stats_path = os.path.join(stats_dir, 'dataset_stats.json')
with open(stats_path, 'w') as f:
    json.dump(stats, f, indent=2)

print(f'  Wrote {n_shards} train shards + 1 dummy val -> {out_dir}')
print(f'  Stats -> {stats_path}')
print(f'  Token method: {token_method}')
print(f'  Docs: {len(texts):,}, Tokens: {total_tokens:,}')
")

    DATA_DIR="$PREPARED_DATA_DIR"
    echo ""
    echo "╚══════════════════════════════════════════╝"
    echo ""

elif [ -d "$DATA_DIR/quadmix_data" ] && [ -f "$DATA_DIR/dataset_stats.json" ]; then
    echo "  Using prepared data: $DATA_DIR"
else
    echo "ERROR: Invalid data source: $DATA_DIR"
    echo "  Expected: .parquet file or directory with quadmix_data/ + dataset_stats.json"
    exit 1
fi

QUADMIX_DATA="$DATA_DIR/quadmix_data"

if [ ! -d "$QUADMIX_DATA" ]; then
    echo "  ERROR: QuadMix data directory not found: $QUADMIX_DATA"
    exit 1
fi

cp "$DATA_DIR/dataset_stats.json" "$RESULT_DIR/dataset_stats.json"
STATS_FILE="$RESULT_DIR/dataset_stats.json" DATA_DIR="$DATA_DIR" BASE_MODEL_TAG="$BASE_MODEL_TAG" \
TARGET_PARAM_DATA_RATIO="$TARGET_PARAM_DATA_RATIO" \
NUM_SCALING_PARAMS="$NUM_SCALING_PARAMS" \
DEVICE_BATCH_SIZE="$DEVICE_BATCH_SIZE" \
NUM_NPU="$NUM_NPU" \
TOTAL_BATCH_SIZE="${CKPT_TOTAL_BATCH_SIZE:-524288}" \
NANOCHAT_REPO="$NANOCHAT_REPO" \
NANOCHAT_MODEL_DIR="$NANOCHAT_MODEL_DIR" \
MID_CHECKPOINTS_OUTPUT_DIR="$MID_CHECKPOINTS_OUTPUT_DIR" \
QUADMIX_GIT_HASH="$(git -C "$QUADMIX_DIR" rev-parse --short HEAD 2>/dev/null || echo 'unknown')" \
NANOCHAT_GIT_HASH="$(git -C "$NANOCHAT_REPO" rev-parse --short HEAD 2>/dev/null || echo 'unknown')" \
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
})
with open(stats_path, 'w') as f:
    json.dump(stats, f, indent=2)
"

# ══════════════════════════════════════════════════════════════
#  NPU ENVIRONMENT SETUP
# ══════════════════════════════════════════════════════════════

export OMP_NUM_THREADS=1
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
export ASCEND_RT_VISIBLE_DEVICES="$ASCEND_DEVICE_LIST"
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
echo "  QuadMix Mid-Training — Quick Validation"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "  Data source:         $DATA_SOURCE"
if [ "$DATA_SOURCE" != "$DATA_DIR" ]; then
    echo "  Data dir (prepared): $DATA_DIR"
fi
echo "  Nanochat model dir:  $NANOCHAT_MODEL_DIR"
echo "  Nanochat repo:       $NANOCHAT_REPO"
echo "  Base model tag:      $BASE_MODEL_TAG"
echo "  Model tag (save):    $QUADMIX_MODEL_TAG"
echo "  Output dir:          $RESULT_DIR"
if [ -n "$MID_CHECKPOINTS_OUTPUT_DIR" ]; then
    echo "  Mid checkpoint out:  $MID_CHECKPOINTS_OUTPUT_DIR"
fi
echo ""
echo "  Mid-training config:"
echo "    target-param-data-ratio: $TARGET_PARAM_DATA_RATIO"
echo "    num-scaling-params:      $NUM_SCALING_PARAMS"
echo "    device-batch-size:       $DEVICE_BATCH_SIZE"
echo "    NPU cards:               $NUM_NPU"
echo "    eval-benchmarks:         $EVAL_BENCHMARKS"
echo ""
echo "════════════════════════════════════════════════════════════"
echo ""

mkdir -p "$RESULT_DIR"

# ══════════════════════════════════════════════════════════════
#  SETUP MID_CHECKPOINTS DIRECTORY
# ══════════════════════════════════════════════════════════════

python3 "$SCRIPT_DIR/distributed_runtime.py" layout \
    --directory "$NANOCHAT_MODEL_DIR" --output "$NANOCHAT_RUNTIME_DIR" \
    --checkpoint-dir "$MID_CHECKPOINTS_OUTPUT_DIR" \
    --eval-bundle "${NANOCHAT_EVAL_BUNDLE_DIR:-}"
if [ -n "${NANOCHAT_EVAL_BUNDLE_DIR:-}" ]; then
    python3 "$SCRIPT_DIR/prepare_offline_eval_bundle.py" "$NANOCHAT_EVAL_BUNDLE_DIR" "$NANOCHAT_RUNTIME_DIR"
fi

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
#  PRE-FLIGHT: DISK SPACE CHECK
# ══════════════════════════════════════════════════════════════

echo ""
echo "╔══ Pre-flight: Disk space check ══╗"
echo ""

CKPT_DIR="${MID_CHECKPOINTS_OUTPUT_DIR}"
mkdir -p "$CKPT_DIR"

AVAILABLE_KB=$(df -P "$CKPT_DIR" | awk 'NR==2{print $4}')
AVAILABLE_GB=$((AVAILABLE_KB / 1024 / 1024))
MIN_REQUIRED_GB=20

echo "  Checkpoint dir:  $CKPT_DIR"
echo "  Available space: ${AVAILABLE_GB}GB"
echo "  Minimum needed:  ${MIN_REQUIRED_GB}GB (1 training × ~20GB/ckpt)"

if [ "$AVAILABLE_GB" -lt "$MIN_REQUIRED_GB" ]; then
    echo ""
    echo "  ERROR: Insufficient disk space!"
    echo "  Available: ${AVAILABLE_GB}GB < Required: ${MIN_REQUIRED_GB}GB"
    echo ""
    echo "  Options:"
    echo "    1. Set MID_CHECKPOINTS_OUTPUT_DIR to a partition with more space:"
    echo "       MID_CHECKPOINTS_OUTPUT_DIR=/path/to/larger/disk bash nanochat_mid_compare/run_quadmix_only.sh"
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
#  MID-TRAINING
# ══════════════════════════════════════════════════════════════

QUADMIX_TOKENS=$(DATA_DIR="$DATA_DIR" python3 -c "
import os, json
s = json.load(open(os.path.join(os.environ['DATA_DIR'], 'dataset_stats.json')))
print(s['quadmix']['tokens'])
")

TARGET_TOKENS=$(python3 -c "print(int($TARGET_PARAM_DATA_RATIO * $NUM_SCALING_PARAMS))")
BUDGET_CAP=$(( TARGET_TOKENS * 11 / 10 ))
if [ -n "$TRAIN_TOKEN_BUDGET" ]; then BUDGET_CAP="$TRAIN_TOKEN_BUDGET"; fi
PLAN_FILE="$RESULT_DIR/training_plan_$QUADMIX_MODEL_TAG.json"
PLAN_ENV=$(python3 "$SCRIPT_DIR/distributed_runtime.py" plan \
    --directory "$BASE_CKPT_DIR" --repo "$NANOCHAT_REPO" --devices "$NUM_NPU" \
    --tokens "$BUDGET_CAP" --steps "$TRAIN_NUM_ITERATIONS" \
    --device-batch-size "$DEVICE_BATCH_SIZE" \
    --total-batch-size "${TRAIN_TOTAL_BATCH_SIZE:-$CKPT_TOTAL_BATCH_SIZE}" --output "$PLAN_FILE")
eval "$PLAN_ENV"

echo "╔══ Mid-training on QuadMix data ══╗"
echo ""
echo "  Data:       $QUADMIX_DATA"
echo "  Source:     $BASE_MODEL_TAG (base)"
echo "  Save as:    $QUADMIX_MODEL_TAG (mid)"
echo "  Dataset:    $QUADMIX_TOKENS tokens"
echo "  Train:      $BUDGET_CAP tokens (budget_cap = target × 1.1, ratio=$TARGET_PARAM_DATA_RATIO)"
echo "  Steps:      $NUM_ITERATIONS"

QUADMIX_LOG="$RESULT_DIR/mid_train_quadmix.log"
DATA_CHECK_ARGS=(check-data --directory "$QUADMIX_DATA" --devices "$NUM_NPU")
if [ "$EVAL_EVERY" != "-1" ]; then
    DATA_CHECK_ARGS+=(--validation)
fi
python3 "$SCRIPT_DIR/distributed_runtime.py" "${DATA_CHECK_ARGS[@]}"

LINK_DIR="$NANOCHAT_RUNTIME_DIR/base_checkpoints/$QUADMIX_MODEL_TAG"
if [ ! -e "$LINK_DIR" ]; then
    echo "  Creating symlink: $LINK_DIR -> $BASE_CKPT_DIR"
    ln -s "$BASE_CKPT_DIR" "$LINK_DIR"
fi

trap 'if [ -L "$LINK_DIR" ]; then echo "  Cleaning up symlink on exit: $LINK_DIR"; rm "$LINK_DIR"; fi' EXIT

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
    --run="$(if [ "$NANOCHAT_DISABLE_WANDB" = "1" ]; then echo dummy; else echo quadmix_mid; fi)" \
    --model-tag="$QUADMIX_MODEL_TAG" \
    --core-metric-every="$CORE_METRIC_EVERY" \
    --eval-every="$EVAL_EVERY" \
    --eval-benchmarks="$EVAL_BENCHMARKS" \
    --data-dir="$QUADMIX_DATA" \
    2>&1 | tee "$QUADMIX_LOG"
popd > /dev/null
python3 "$SCRIPT_DIR/distributed_runtime.py" record \
    --directory "$MID_CHECKPOINTS_OUTPUT_DIR/$QUADMIX_MODEL_TAG" --devices "$NUM_NPU" \
    --phase "mid:$QUADMIX_MODEL_TAG" --plan-file "$PLAN_FILE" --repo "$NANOCHAT_REPO" --data-directory "$QUADMIX_DATA"
if [ "${AMT_TRAIN_ONLY:-0}" = "1" ] || [ "$EVALUATION_ENABLED" != "1" ]; then exit 0; fi


echo ""
echo "╚══════════════════════════════════════════╗"
echo ""

# ══════════════════════════════════════════════════════════════
#  EVALUATION
# ══════════════════════════════════════════════════════════════

echo "╔══ Evaluation ══╗"
echo ""
echo "  Evaluating: $QUADMIX_MODEL_TAG (mid)"

QUADMIX_EVAL_LOG="$RESULT_DIR/eval_quadmix.log"
EVAL_CHECKPOINT_DIR="$MID_CHECKPOINTS_OUTPUT_DIR/$QUADMIX_MODEL_TAG"
if [ "$NODE_RANK" != "0" ]; then
    EVAL_CACHE="${TMPDIR:-/tmp}/auto-mixture-$TIMESTAMP/node-$NODE_RANK/eval_model"
    mkdir -p "$EVAL_CACHE/mid_checkpoints"
    for ASSET in tokenizer eval_bundle; do
        ln -sfn "$NANOCHAT_RUNTIME_DIR/$ASSET" "$EVAL_CACHE/$ASSET"
    done
    export NANOCHAT_BASE_DIR="$EVAL_CACHE"
    EVAL_CHECKPOINT_DIR="$EVAL_CACHE/mid_checkpoints/$QUADMIX_MODEL_TAG"
fi
CHECKPOINT_STEP=$(python3 "$SCRIPT_DIR/distributed_runtime.py" checkpoint \
    --directory "$EVAL_CHECKPOINT_DIR" \
    --phase "mid:$QUADMIX_MODEL_TAG" --devices "$NUM_NPU")

python3 "$SCRIPT_DIR/distributed_runtime.py" settle --devices "$NUM_NPU"
pushd "$NANOCHAT_REPO" > /dev/null
HCCL_BUFFSIZE="${HCCL_BUFFSIZE:-100}" python3 -m torch.distributed.run "${EVAL_TORCHRUN_ARGS[@]}" -m nanochat_mid_compare.offline_base_eval \
    --eval=core \
    --eval-benchmarks="$EVAL_BENCHMARKS" \
    --device-batch-size=32 \
    --model-tag="$QUADMIX_MODEL_TAG" \
    --step="$CHECKPOINT_STEP" \
    --model-type="mid" \
    2>&1 | tee "$QUADMIX_EVAL_LOG"
popd > /dev/null

echo ""
echo "╚════════════════════════════════════╝"
echo ""

# ══════════════════════════════════════════════════════════════
#  REPORT
# ══════════════════════════════════════════════════════════════

echo "╔══ Generating Report ══╗"
echo ""

if [ "$NODE_RANK" != "0" ]; then
    echo "  node-$NODE_RANK finished distributed training/evaluation; report is generated by node-0"
    exit 0
fi

export QUADMIX_LOG QUADMIX_EVAL_LOG QUADMIX_MODEL_TAG BASE_MODEL_TAG \
    RESULT_DIR DATA_DIR DATA_SOURCE TOKENIZER_PKL NANOCHAT_REPO \
    NANOCHAT_MODEL_DIR MID_CHECKPOINTS_OUTPUT_DIR \
    TARGET_PARAM_DATA_RATIO NUM_SCALING_PARAMS \
    DEVICE_BATCH_SIZE TOTAL_BATCH_SIZE NUM_NPU \
    QUADMIX_TOKENS BUDGET_CAP NUM_ITERATIONS
export QUADMIX_GIT_HASH="$(git -C "$QUADMIX_DIR" rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
export NANOCHAT_GIT_HASH="$(git -C "$NANOCHAT_REPO" rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
python3 "$SCRIPT_DIR/generate_quadmix_report.py"

echo ""
echo "╚══════════════════════════════════════════╝"
echo ""

# ══════════════════════════════════════════════════════════════
#  SUMMARY
# ══════════════════════════════════════════════════════════════

echo ""
echo "════════════════════════════════════════════════════════════"
echo "  QuadMix Quick Validation Complete!"
echo "════════════════════════════════════════════════════════════"
echo ""
echo "  Output:          $RESULT_DIR"
echo "  Report:          $RESULT_DIR/midtrain_validation_report.md"
echo "  Experiment log:  $RESULT_DIR/experiment.log"
echo "  Training log:    $QUADMIX_LOG"
echo "  Eval log:        $QUADMIX_EVAL_LOG"
echo "  Checkpoint:      $MID_CHECKPOINTS_OUTPUT_DIR/$QUADMIX_MODEL_TAG/"
echo ""
echo "════════════════════════════════════════════════════════════"
