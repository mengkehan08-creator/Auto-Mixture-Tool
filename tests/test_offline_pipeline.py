from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_training_entry_uses_offline_eval_wrapper() -> None:
    source = (ROOT / "nanochat_mid_compare" / "run_stem_experiment.sh").read_text(encoding="utf-8")
    assert "nanochat_mid_compare.offline_base_eval" in source
    assert "prepare_offline_eval_bundle.py" in source
    assert "HF_DATASETS_OFFLINE=1" in source


def test_modelarts_runs_resource_preflight_before_pipeline() -> None:
    source = (ROOT / "modelarts_training_job.py").read_text(encoding="utf-8")
    check = source.index("scripts/offline_resource_check.py")
    run = source.index("auto_mixture_tool.cli run")
    assert check < run


def test_ui_is_explicitly_display_only() -> None:
    html = (ROOT / "src" / "auto_mixture_tool" / "api" / "static" / "index.html").read_text(encoding="utf-8")
    assert "提交功能将在后续版本接入" in html
    assert "代理实验数" in html
    assert "人工配比 × 2" in html
