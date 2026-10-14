from __future__ import annotations

import argparse
import json
from pathlib import Path

from nanochat_mid_compare.generate_report import generate_report
from quadmix.sampling.sources import resolve_parquet_source


def test_sampled_directory_ignores_manifest_json(tmp_path: Path) -> None:
    (tmp_path / "shard_00001.parquet").touch()
    (tmp_path / "shard_00000.parquet").touch()
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")

    resolved = resolve_parquet_source(str(tmp_path))

    assert [Path(path).name for path in resolved] == [
        "shard_00000.parquet",
        "shard_00001.parquet",
    ]


def test_multinode_checkpoint_links_are_created_idempotently() -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "nanochat_mid_compare"
        / "run_stem_experiment.sh"
    ).read_text(encoding="utf-8")
    assert 'LINK_PATH="$NANOCHAT_RUNTIME_DIR/mid_checkpoints"' in script
    assert 'install_shared_symlink "$MID_CHECKPOINTS_OUTPUT_DIR" "$LINK_PATH"' in script
    assert 'install_shared_symlink "$BASE_CKPT_DIR" "$LINK_DIR"' in script
    assert 'ln -sfnT "$TARGET" "$LINK"' in script
    assert 'LINK_PATH="$NANOCHAT_MODEL_DIR/mid_checkpoints"' not in script


def test_nanochat_runtime_layout_does_not_modify_modelarts_input() -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "nanochat_mid_compare"
        / "run_stem_experiment.sh"
    ).read_text(encoding="utf-8")
    assert 'export NANOCHAT_BASE_DIR="$NANOCHAT_RUNTIME_DIR"' in script
    assert '"$NANOCHAT_RUNTIME_DIR/base_checkpoints/$BASE_MODEL_TAG"' in script
    assert 'install_shared_symlink "$TOKENIZER_DIR" "$NANOCHAT_RUNTIME_DIR/tokenizer"' in script
    assert '"$NANOCHAT_RUNTIME_DIR/eval_bundle"' in script
    assert 'local LINK_DIR="$NANOCHAT_RUNTIME_DIR/base_checkpoints/$MODEL_TAG"' in script


def test_nanochat_offline_eval_bundle_is_validated() -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "nanochat_mid_compare"
        / "run_stem_experiment.sh"
    ).read_text(encoding="utf-8")
    assert 'NANOCHAT_EVAL_BUNDLE_DIR="${NANOCHAT_EVAL_BUNDLE_DIR:-}"' in script
    assert 'find "$NANOCHAT_EVAL_BUNDLE_DIR" -mindepth 1' in script
    assert "prepare_offline_eval_bundle.py" in script
    assert "nanochat_mid_compare.offline_base_eval" in script


def test_nanochat_script_reports_stage_progress() -> None:
    script = (
        Path(__file__).resolve().parents[1]
        / "nanochat_mid_compare"
        / "run_stem_experiment.sh"
    ).read_text(encoding="utf-8")
    assert 'show_progress 5 "configuration validated"' in script
    assert 'show_progress 55 "QuaDMix dataset training finished"' in script
    assert 'show_progress 57 "starting random dataset training"' in script
    assert 'show_progress 78 "evaluating QuaDMix model"' in script
    assert 'show_progress 95 "generating comparison report"' in script
    assert 'show_progress 100 "NanoChat comparison experiment complete"' in script


def test_rustbpe_fallback_is_limited_to_existing_tokenizers() -> None:
    fallback = (
        Path(__file__).resolve().parents[1]
        / "nanochat_mid_compare"
        / "compat"
        / "rustbpe.py"
    ).read_text(encoding="utf-8")
    script = (
        Path(__file__).resolve().parents[1]
        / "nanochat_mid_compare"
        / "run_stem_experiment.sh"
    ).read_text(encoding="utf-8")
    assert "training a new tokenizer is unavailable" in fallback
    assert 'if ! python3 -c "import rustbpe"' in script
    assert '$SCRIPT_DIR/compat' in script
    assert "NanoChat tokenizer import OK" in script


def test_old_pytorch_and_wandb_have_offline_training_fallbacks() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "nanochat_mid_compare" / "run_stem_experiment.sh").read_text(
        encoding="utf-8"
    )
    compatibility = (
        root / "nanochat_mid_compare" / "compat" / "sitecustomize.py"
    ).read_text(encoding="utf-8")
    assert 'AMT_PYTHON_EXECUTABLE="${AMT_PYTHON_EXECUTABLE:-$(command -v python3)}"' in script
    assert '"$AMT_PYTHON_EXECUTABLE" "$@"' in script
    assert "PyTorch F.rms_norm unavailable" in script
    assert 'TRACKING_RUN_NAME="dummy"' in script
    assert '--run="$TRACKING_RUN_NAME"' in script
    assert 'compat/wandb_disabled' in script
    wandb_fallback = (
        root / "nanochat_mid_compare" / "compat" / "wandb_disabled" / "wandb.py"
    ).read_text(encoding="utf-8")
    assert "def init(" in wandb_fallback
    assert "def log(" in wandb_fallback
    assert "def finish(" in wandb_fallback
    assert 'if not hasattr(functional, "rms_norm")' in compatibility
    assert "torch.rsqrt" in compatibility


def test_nanochat_training_uses_world_size_compatible_optimizer_wrapper() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "nanochat_mid_compare" / "run_stem_experiment.sh").read_text(
        encoding="utf-8"
    )
    assert "nanochat_mid_compare.run_nanochat_mid_train" in script
    assert '--load-optimizer="$NANOCHAT_LOAD_OPTIMIZER"' in script
    assert 'NANOCHAT_LOAD_OPTIMIZER="${NANOCHAT_LOAD_OPTIMIZER:-0}"' in script


def test_adamw_sharding_supports_two_through_sixteen_nodes() -> None:
    from nanochat_mid_compare.run_nanochat_mid_train import shard_layout

    parameter_size = 32768
    for node_count in range(2, 17):
        world_size = node_count * 8
        covered: list[int] = []
        layouts = [
            shard_layout(parameter_size, world_size, rank)
            for rank in range(world_size)
        ]
        for layout in layouts:
            covered.extend(range(layout.start, layout.stop))
            assert layout.padded_size % world_size == 0
            assert layout.padded_size - parameter_size < world_size
        assert covered == list(range(parameter_size))


def test_quadmix_reports_detailed_stage_progress() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "quadmix"
        / "pipeline"
        / "real_pipeline.py"
    ).read_text(encoding="utf-8")
    assert 'self._print_progress(15, "proxy parameter sets sampled")' in source
    assert 'self._print_progress(65, "proxy experiments completed")' in source
    assert 'self._print_progress(100, "QuaDMix report generated")' in source


def test_comparison_report_contains_realized_domain_ratios(tmp_path: Path) -> None:
    stats = {
        "config": {
            "baselines": ["quadmix", "random", "manual_ratio"],
            "base_model_tag": "d24",
        },
        "quadmix": {"domain_ratios": {"数学": 0.7, "物理": 0.3}},
        "random": {"domain_ratios": {"数学": 0.5, "物理": 0.5}},
        "manual_ratio": {
            "label": "Manual Ratio",
            "ratio_map": {"数学": 60, "物理": 40},
            "domain_ratios": {"数学": 0.6, "物理": 0.4},
        },
    }
    stats_path = tmp_path / "dataset_stats.json"
    stats_path.write_text(json.dumps(stats, ensure_ascii=False), encoding="utf-8")
    args = argparse.Namespace(
        result_dir=str(tmp_path),
        dataset_stats=str(stats_path),
        quadmix_train_log=None,
        random_train_log=None,
        manual_ratio_train_log=None,
        quadmix_eval_log=None,
        random_eval_log=None,
        manual_ratio_eval_log=None,
        quality_train_log=None,
        quality_eval_log=None,
    )

    generate_report(args)

    report = (tmp_path / "experiment_report.md").read_text(encoding="utf-8")
    assert "## Sampling Domain Ratios (by token)" in report
    assert "| 数学 | 70.00% | 50.00% | 60.00% |" in report
    assert "Manual target ratio: 数学=60.00%, 物理=40.00%" in report
