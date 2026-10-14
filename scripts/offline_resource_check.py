"""Fail fast with one report when a ModelArts offline resource is incomplete."""

from __future__ import annotations

import argparse
import importlib.util
import sys
import zipfile
from pathlib import Path

import yaml


def _need_file(errors: list[str], label: str, value: object) -> Path:
    if value is None or str(value).strip() == "":
        errors.append(f"{label}: path is not configured")
        return Path("/__auto_mixture_missing__")
    path = Path(str(value or ""))
    if not path.is_file():
        errors.append(f"{label}: file not found: {path}")
    return path


def _need_dir(errors: list[str], label: str, value: object) -> Path:
    if value is None or str(value).strip() == "":
        errors.append(f"{label}: path is not configured")
        return Path("/__auto_mixture_missing__")
    path = Path(str(value or ""))
    if not path.is_dir():
        errors.append(f"{label}: directory not found: {path}")
    return path


def check(config_path: Path) -> list[str]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    _need_file(errors, "schema_uri", config.get("schema_uri"))
    dataset = _need_dir(errors, "dataset_uri", config.get("dataset_uri"))
    if dataset.is_dir() and not next(dataset.rglob("*.parquet"), None):
        errors.append(f"dataset_uri: no parquet files found under {dataset}")

    algorithm = config.get("algorithm_config", {})
    tokenizer = _need_dir(errors, "algorithm tokenizer_path", algorithm.get("tokenizer_path"))
    if tokenizer.is_dir() and not any(
        next(tokenizer.rglob(name), None) is not None
        for name in ("tokenizer.json", "tokenizer_config.json")
    ):
        errors.append(f"algorithm tokenizer_path: tokenizer metadata missing under {tokenizer}")
    _need_file(errors, "proxy_validation_path", algorithm.get("proxy_validation_path"))

    trainer = config.get("trainer_config", {})
    if trainer.get("skip_eval_download") is not True:
        errors.append("trainer_config.skip_eval_download must be true for production")
    repo = _need_dir(errors, "nanochat_repo", trainer.get("nanochat_repo"))
    for relative in ("scripts/base_eval.py", "scripts/base_train.py"):
        if repo.is_dir() and not (repo / relative).is_file():
            errors.append(f"nanochat_repo: missing {relative}")
    model_dir = _need_dir(errors, "model_dir", trainer.get("model_dir"))
    if model_dir.is_dir():
        if not (model_dir / "tokenizer" / "tokenizer.pkl").is_file():
            errors.append("model_dir: missing tokenizer/tokenizer.pkl")
        tag = str(trainer.get("base_model_tag", ""))
        if tag and not (model_dir / "base_checkpoints" / tag).is_dir():
            errors.append(f"model_dir: missing base_checkpoints/{tag}")
    bundle = _need_dir(errors, "eval_bundle_dir", trainer.get("eval_bundle_dir"))
    if bundle.is_dir():
        entries = list(bundle.iterdir())
        if not entries:
            errors.append("eval_bundle_dir: directory is empty")
        for archive in bundle.rglob("*.zip"):
            if not zipfile.is_zipfile(archive):
                errors.append(f"eval_bundle_dir: invalid zip: {archive}")
        benchmarks = str(config.get("evaluator_config", {}).get("benchmarks", "stem"))
        if "stem" in benchmarks.lower():
            names = [path.name.lower() for path in bundle.rglob("*")]
            if not any("stem" in name for name in names):
                errors.append(
                    "eval_bundle_dir: STEM evaluation selected but no eval_stem "
                    "directory/archive was found"
                )

    comparison = config.get("comparison_config", {})
    strategies = []
    random_strategy = comparison.get("random_strategy", {})
    if isinstance(random_strategy, dict) and random_strategy.get("script_path"):
        strategies.append(("random strategy", random_strategy["script_path"]))
    for plan in comparison.get("manual_plans", []):
        strategy = plan.get("strategy", {}) if isinstance(plan, dict) else {}
        if strategy.get("script_path"):
            strategies.append((f"manual strategy {plan.get('id', '?')}", strategy["script_path"]))
    for label, value in strategies:
        path = _need_file(errors, label, value)
        if path.is_file() and path.suffix.lower() != ".py":
            errors.append(f"{label}: strategy must be a .py file")
        elif path.is_file():
            spec = importlib.util.spec_from_file_location("_amt_preflight_strategy", path)
            if spec is None or spec.loader is None:
                errors.append(f"{label}: cannot load strategy")
            else:
                try:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    if getattr(module, "STRATEGY_API_VERSION", None) != "1" or not callable(getattr(module, "select", None)):
                        errors.append(f"{label}: requires STRATEGY_API_VERSION='1' and select()")
                except Exception as exc:
                    errors.append(f"{label}: import failed: {type(exc).__name__}: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    args = parser.parse_args()
    errors = check(Path(args.config))
    if errors:
        print("ERROR: offline resource preflight failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("Offline resource preflight OK; production stages require no network downloads")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
