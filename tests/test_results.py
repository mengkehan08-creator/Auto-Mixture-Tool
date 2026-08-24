from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from auto_mixture_tool.results.analysis import ResultAnalyzer


class ResultAnalyzerTests(unittest.TestCase):
    def test_compare_understands_canonical_summary_and_filters_runs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            run = root / "run-a"
            run.mkdir()
            (run / "pipeline_summary.json").write_text(
                json.dumps({
                    "stages": {
                        "unify": {"size": 10},
                        "mixing": {"selected_size": 4},
                    },
                    "metrics": {"best_predicted_loss": 1.2},
                }),
                encoding="utf-8",
            )
            analyzer = ResultAnalyzer(root)
            report = analyzer.compare_runs(["run-a"])

        self.assertEqual(report["count"], 1)
        self.assertEqual(report["runs"][0]["sampling_ratio"], 0.4)
        self.assertEqual(report["runs"][0]["best_predicted_loss"], 1.2)


if __name__ == "__main__":
    unittest.main()
