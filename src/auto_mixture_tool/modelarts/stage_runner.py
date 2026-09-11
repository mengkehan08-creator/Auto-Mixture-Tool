"""Entrypoint executed inside each ModelArts job container."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .config_transport import read_config
from .preflight import check_mounted_assets
from .strategy_upload import materialize_scripts


WORKSPACE = Path("/home/ma-user/modelarts/user-job-dir/Auto-Mixture-Tool")
OUTPUT = Path("/home/ma-user/modelarts/outputs/output_dir_0")


def _config() -> dict[str, Any]:
    return read_config(os.environ)


def _comparison(config: dict[str, Any]) -> dict[str, Any]:
    strategies = config.get("strategies", [])
    methods: list[str] = []
    manual_plans: list[dict[str, Any]] = []
    random_strategy: dict[str, Any] = {"script_path": "", "config": {}}
    for strategy in strategies:
        kind = str(strategy.get("type", "")).lower()
        if kind not in methods:
            methods.append(kind)
        if kind == "manual":
            manual_plans.append({
                "id": strategy["id"],
                "label": strategy.get("name") or strategy["id"],
                "ratios": strategy.get("ratios", {}),
                "strategy": {
                    "script_path": strategy.get("local_script_path", ""),
                    "config": strategy.get("script_config", {}),
                },
            })
        elif kind == "random":
            random_strategy = {
                "script_path": strategy.get("local_script_path", ""),
                "config": strategy.get("script_config", {}),
            }
    return {
        "methods": methods,
        "manual_plans": manual_plans,
        "random_strategy": random_strategy,
    }


def run_mixing(config: dict[str, Any]) -> None:
    from auto_mixture_tool.pipeline import PipelineManager
    quadmix = next((item for item in config["strategies"] if item["type"] == "quadmix"), None)
    if quadmix is None:
        return run_baseline_mixing(config)
    request = {
        "dataset_uri": "/home/ma-user/modelarts/inputs/data_dir_0",
        "schema_uri": str(WORKSPACE / "configs/schema_stem_quadmix_parquet.yaml"),
        "dataset_id": "quadmix",
        "output_uri": str(OUTPUT / "mixing"),
        "algorithm_id": "quadmix",
        "trainer_id": "nanochat",
        "evaluator_id": "stem",
        "executor_id": "local",
        "full_scan": bool(config.get("full_scan", False)),
        "algorithm_config": {
            "num_experiments": quadmix.get("proxy_experiments", 16),
            "tiny_steps": quadmix.get("proxy_steps", 15),
            "num_search": quadmix.get("search_count", 5000),
            "seed": quadmix.get("seed", 42),
            "device_type": "npu",
            "npu_devices": quadmix.get("devices_per_node", 8),
            "algorithm_nodes": "auto",
            "proxy_validation_set": "stem_v2",
            "proxy_validation_path": (
                "/home/ma-user/modelarts/inputs/proxy_validation_dir_5/"
                "stem_v2_tokenized.pt"
            ),
            "tokenizer_path": "/home/ma-user/modelarts/inputs/quadmix_tokenizer_dir_4",
        },
        "comparison_config": _comparison(config),
        "trainer_config": {
            "npu_devices": quadmix.get("devices_per_node", 8),
            "target_param_data_ratio": config["training"].get(
                "target_param_data_ratio", 0.5
            ),
            "nanochat_repo": "/home/ma-user/modelarts/inputs/nanochat_npu_dir_3",
            "model_dir": "/home/ma-user/modelarts/inputs/nanochat_model_dir_1",
            "result_dir": str(OUTPUT / "sampled"),
            "base_model_tag": config["training"].get("base_model_tag", "d24"),
            "prepare_only": True,
            "disable_wandb": True,
            "mix_general_data": False,
        },
        "evaluator_config": {"benchmarks": "stem"},
        "executor_config": {"device_type": "npu", "device_count": quadmix.get('devices_per_node', 8)},
    }
    result = PipelineManager(WORKSPACE).submit(request)
    if result.get("status") != "SUCCEEDED":
        raise RuntimeError(result.get("message") or "mixing stage failed")


def run_baseline_mixing(config):
    """Run the existing sampling implementation without launching proxy experiments."""
    if int(os.environ.get('VC_TASK_INDEX', '0')) != 0:
        print('人工/随机采样由首节点写出；本节点无需重复采样。')
        return
    from auto_mixture_tool.pipeline import PipelineManager
    data = '/home/ma-user/modelarts/inputs/data_dir_0'
    schema = str(WORKSPACE / 'configs/schema_stem_quadmix_parquet.yaml')
    report = PipelineManager(WORKSPACE).validate(data, schema, full_scan=config.get('full_scan', False))
    if not report['valid']:
        raise ValueError('数据格式不符合算法要求：' + '; '.join(report.get('errors', [])))
    comparison = _comparison(config)
    training = config['training']
    env = dict(os.environ, PREPARE_ONLY='1', COMPARISON_METHODS=','.join(comparison['methods']),
               STEM_DATA_DIR=data, SCHEMA_CONFIG=schema,
               NANOCHAT_REPO='/home/ma-user/modelarts/inputs/nanochat_npu_dir_3',
               NANOCHAT_MODEL_DIR='/home/ma-user/modelarts/inputs/nanochat_model_dir_1',
               BASE_MODEL_TAG=training.get('base_model_tag', 'd24'),
               TARGET_PARAM_DATA_RATIO=str(training.get('target_param_data_ratio', 0.5)),
               RESULT_DIR=str(OUTPUT / 'sampled'), MID_CHECKPOINTS_OUTPUT_DIR=str(OUTPUT / 'unused_checkpoints'),
               NUM_NPU=str(config['strategies'][0].get('devices_per_node', 8)),
               SEED=str(config['strategies'][0].get('seed', 42)),
               NANOCHAT_DISABLE_WANDB='1', MIX_GENERAL_DATA='0',
               MANUAL_RATIO='')
    plans = comparison['manual_plans']
    if plans:
        first = plans[0]
        env.update(MANUAL_RATIO=':'.join(f'{k}={v}' for k, v in first['ratios'].items()),
                   MANUAL_STRATEGY_PATH=first['strategy']['script_path'],
                   MANUAL_STRATEGY_CONFIG_JSON=json.dumps(first['strategy']['config']),
                   MANUAL_PLANS_JSON=json.dumps([{'id': p['id'], 'label': p['label'], 'ratios': p['ratios'],
                       'strategy_path': p['strategy']['script_path'], 'strategy_config': p['strategy']['config']}
                       for p in plans], ensure_ascii=False))
    random = comparison['random_strategy']
    env.update(RANDOM_STRATEGY_PATH=random['script_path'], RANDOM_STRATEGY_CONFIG_JSON=json.dumps(random['config']))
    subprocess.run(['bash', str(WORKSPACE / 'nanochat_mid_compare/run_stem_experiment.sh')],
                   cwd=WORKSPACE, env=env, check=True)


def _prepared_data_dir() -> Path:
    mounted = Path("/home/ma-user/modelarts/inputs/comparison_data_dir_8")
    candidates = (mounted / "data", mounted)
    for candidate in candidates:
        if (candidate / "dataset_stats.json").is_file():
            return candidate
    raise ValueError(
        "数据格式不符合训练要求: sampled OBS output is missing dataset_stats.json"
    )


def run_training(config: dict[str, Any]) -> None:
    data_dir = _prepared_data_dir()
    comparison = _comparison(config)
    # Validate every selected subset before paying for any model training.
    for method in comparison["methods"]:
        if method in {"quadmix", "random"}:
            path = data_dir / f"{method}_data"
            if not path.is_dir() or not any(path.glob("*.parquet")):
                raise ValueError(f"数据格式不符合训练要求：缺少 {method} 的 Parquet 采样集")
        elif method == "manual":
            from auto_mixture_tool.sampling.artifacts import manual_plans
            plans = manual_plans(data_dir)
            if {p["id"] for p in plans} != {p["id"] for p in comparison["manual_plans"]}:
                raise ValueError("人工采样清单与本次所选方案不一致")
    env = os.environ.copy()
    env.update({
        "AMT_TRAIN_ONLY": "1" if config.get('split_evaluation') else "0",
        "PREPARED_COMPARISON_DATA_DIR": str(data_dir),
        "COMPARISON_METHODS": ",".join(comparison["methods"]),
        "MANUAL_PLANS_JSON": json.dumps(
            comparison["manual_plans"], ensure_ascii=False, separators=(",", ":")
        ),
        "NANOCHAT_REPO": "/home/ma-user/modelarts/inputs/nanochat_npu_dir_3",
        "NANOCHAT_MODEL_DIR": "/home/ma-user/modelarts/inputs/nanochat_model_dir_1",
        "NANOCHAT_EVAL_BUNDLE_DIR": "/home/ma-user/modelarts/inputs/eval_bundle_dir_6",
        "NANOCHAT_SKIP_EVAL_DOWNLOAD": "1",
        "NANOCHAT_DISABLE_WANDB": "1",
        "NANOCHAT_LOAD_OPTIMIZER": "0",
        "BASE_MODEL_TAG": str(config["training"].get("base_model_tag", "d24")),
        "TARGET_PARAM_DATA_RATIO": str(
            config["training"].get("target_param_data_ratio", 0.5)
        ),
        "NUM_NPU": str(config["training"].get("devices_per_node", 8)),
        "TRAIN_NUM_ITERATIONS": str(config["training"].get("num_iterations", 0)),
        "TRAIN_TOKEN_BUDGET": str(config["training"].get("token_budget", "")),
        "DEVICE_BATCH_SIZE": str(config["training"].get("device_batch_size", 1)),
        "EVAL_EVERY": str(config["training"].get("eval_every", -1)),
        "CORE_METRIC_EVERY": str(config["training"].get("core_metric_every", -1)),
        "RESULT_DIR": str(OUTPUT / "training/results" if config.get('split_evaluation') else OUTPUT.parent / "reports_output" if config["evaluation"].get("output_obs_uri") else OUTPUT / "training/results"),
        "MID_CHECKPOINTS_OUTPUT_DIR": str(OUTPUT.parent / "models_output" if config["training"].get("output_obs_uri") else OUTPUT / "training/checkpoints"),
        "EVAL_BENCHMARKS": ",".join(config["evaluation"].get("datasets") or ["stem"]),
        "EVALUATION_ENABLED": "1" if not config.get('split_evaluation') and config["evaluation"].get("datasets", ["stem"]) else "0",
        "MIX_GENERAL_DATA": "0",
    })
    identity = None
    if config.get('split_evaluation') and int(os.environ.get('VC_TASK_INDEX', '0')) == 0:
        from .model_comparison import build_identity
        identity = build_identity(env['NANOCHAT_MODEL_DIR'], env['BASE_MODEL_TAG'])
    subprocess.run(
        ["bash", str(WORKSPACE / "nanochat_mid_compare/run_stem_experiment.sh")],
        cwd=WORKSPACE,
        env=env,
        check=True,
    )
    if config.get('split_evaluation') and int(os.environ.get('VC_TASK_INDEX', '0')) == 0:
        from .evaluation_job import publish_models
        publish_models(config, Path(env['MID_CHECKPOINTS_OUTPUT_DIR']), data_dir, identity=identity)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("mixing", "training", "evaluation"))
    args = parser.parse_args()
    config = _config()
    check_mounted_assets(config, args.stage)
    if args.stage == "mixing":
        with tempfile.TemporaryDirectory(prefix='amt-strategies-') as directory:
            materialize_scripts(config, directory)
            run_mixing(config)
    elif args.stage == 'training':
        run_training(config)
    else:
        from .evaluation_job import run_evaluation
        run_evaluation(config)


if __name__ == "__main__":
    main()
