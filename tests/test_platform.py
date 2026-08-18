from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quadmix import DatasetSchema
from quadmix_platform.dataset_inspector import inspect_dataset
from quadmix_platform.service import PlatformService


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "examples" / "platform" / "sample_dataset.csv"
SCHEMA = ROOT / "examples" / "platform" / "sample_schema.yaml"


class DatasetInspectionTests(unittest.TestCase):
    def test_public_schema_export_is_still_available(self) -> None:
        self.assertEqual(DatasetSchema.from_yaml(str(SCHEMA)).text_col, "text")

    def test_valid_dataset_passes(self) -> None:
        report = inspect_dataset(str(DATASET), str(SCHEMA))
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["sampled_rows"], 5)

    def test_missing_quality_column_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.csv"
            path.write_text("text,domain,char_count\nhello,math,5\n", encoding="utf-8")
            report = inspect_dataset(str(path), str(SCHEMA))
        self.assertFalse(report["valid"])
        self.assertTrue(any("relevance" in error for error in report["errors"]))


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = PlatformService(ROOT)

    def test_catalog_exposes_switchable_components(self) -> None:
        catalog = self.service.catalog()
        self.assertIn("stem", {item["id"] for item in catalog["validators"]})
        self.assertIn("core", {item["id"] for item in catalog["validators"]})
        self.assertIn("local", {item["id"] for item in catalog["executors"]})
        self.assertIn("hpc-cluster", {item["id"] for item in catalog["executors"]})

    def test_job_builds_separate_stages(self) -> None:
        payload = json.loads((ROOT / "examples" / "platform" / "sample_job.json").read_text(encoding="utf-8"))
        payload["dataset_uri"] = str(DATASET)
        payload["schema_uri"] = str(SCHEMA)
        # Stub the local executor so no real subprocess is spawned.
        self.service.executors.get("local").submit = lambda job: (
            "SUCCEEDED", f"stub-{job.id}", "stubbed submission",
        )
        job = self.service.create_job(payload)
        self.assertEqual(job["status"], "SUCCEEDED")
        self.assertEqual([stage["name"] for stage in job["stages"]], ["quadmix-selection", "nanochat-train-evaluate"])
        self.assertEqual(job["stages"][1]["env"]["EVAL_BENCHMARKS"], "stem")
        self.assertEqual(job["stages"][1]["env"]["STEM_TASKS"], "gsm8k,mmlu_stem,arc_easy")
        self.assertEqual(job["stages"][1]["env"]["STEM_DATA_DIR"], str(DATASET))
        self.assertEqual(job["stages"][1]["executable"], "python")
        self.assertTrue(job["stages"][1]["args"][0].endswith("run_nanochat_validation.py"))

    def test_invalid_dataset_is_never_submitted(self) -> None:
        payload = json.loads((ROOT / "examples" / "platform" / "sample_job.json").read_text(encoding="utf-8"))
        payload["dataset_uri"] = str(ROOT / "missing.csv")
        payload["schema_uri"] = str(SCHEMA)
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.service.create_job(payload)


if __name__ == "__main__":
    unittest.main()
