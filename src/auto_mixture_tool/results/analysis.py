"""Result analysis and reporting helpers.

Parses the JSON/parquet outputs produced by algorithm and trainer stages and
produces a normalized comparison report.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ResultAnalyzer:
    """Load and compare pipeline results."""

    def __init__(self, result_root: str | Path) -> None:
        self.result_root = Path(result_root)

    def list_runs(self) -> list[dict[str, Any]]:
        """List all run directories under the result root."""
        runs = []
        for path in self.result_root.glob("*"):
            if not path.is_dir():
                continue
            summary_path = path / "pipeline_summary.json"
            if summary_path.exists():
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            else:
                summary = {}
            algo_path = path / "optimal_parameters.json"
            runs.append({
                "run_id": path.name,
                "path": str(path),
                "summary": summary,
                "has_optimal_parameters": algo_path.exists(),
            })
        return runs

    def compare_runs(self) -> dict[str, Any]:
        """Build a comparison table across all discovered runs."""
        rows = []
        for run in self.list_runs():
            summary = run["summary"]
            sampling = summary.get("sampling", {})
            metrics = summary.get("metrics", {})
            rows.append({
                "run_id": run["run_id"],
                "num_original_docs": sampling.get("num_original_docs"),
                "num_selected_docs": sampling.get("num_selected_docs"),
                "sampling_ratio": sampling.get("sampling_ratio"),
                "aggregate_val_r2": metrics.get("aggregate_val_r2"),
                "best_predicted_loss": metrics.get("best_predicted_loss"),
            })
        return {
            "count": len(rows),
            "runs": rows,
        }

    def load_run(self, run_id: str) -> dict[str, Any]:
        """Load full metadata for a single run."""
        path = self.result_root / run_id
        summary_path = path / "pipeline_summary.json"
        params_path = path / "optimal_parameters.json"
        result: dict[str, Any] = {"run_id": run_id, "path": str(path)}
        if summary_path.exists():
            result["summary"] = json.loads(summary_path.read_text(encoding="utf-8"))
        if params_path.exists():
            result["optimal_parameters"] = json.loads(params_path.read_text(encoding="utf-8"))
        return result
