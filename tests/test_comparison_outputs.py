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
    assert 'install_shared_symlink "$MID_CHECKPOINTS_OUTPUT_DIR" "$LINK_PATH"' in script
    assert 'install_shared_symlink "$BASE_CKPT_DIR" "$LINK_DIR"' in script
    assert 'ln -sfnT "$TARGET" "$LINK"' in script


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
