from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quadmix import DatasetSchema
from quadmix_platform.dataset_inspector import inspect_dataset
from quadmix_platform.service import PlatformService
from auto_mixture_tool.config.pipeline_config import PipelineConfig


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "examples" / "platform" / "sample_dataset.csv"
JSON_DATASET = ROOT / "examples" / "platform" / "sample_dataset.json"
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

    def test_directory_validation_checks_every_shard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "good.csv").write_text(
                "text,domain,relevance,noise,char_count\nhello,math,0.9,0.1,5\n",
                encoding="utf-8",
            )
            (root / "bad.csv").write_text(
                "text,domain,noise,char_count\nworld,physics,0.2,5\n",
                encoding="utf-8",
            )
            report = inspect_dataset(str(root), str(SCHEMA))
        self.assertFalse(report["valid"])
        self.assertEqual(len(report["inspected_files"]), 2)
        self.assertTrue(any("bad.csv" in error and "relevance" in error for error in report["errors"]))

    def test_wrapped_json_uses_the_same_contract_as_unified_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrapped.json"
            path.write_text(
                json.dumps({"samples": [{
                    "text": "hello", "domain": "math", "relevance": 0.9,
                    "noise": 0.1, "char_count": 5,
                }]}),
                encoding="utf-8",
            )
            report = inspect_dataset(str(path), str(SCHEMA))
        self.assertTrue(report["valid"], report["errors"])

    def test_json_rejects_non_object_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text(json.dumps([{"text": "ok"}, "not-an-object"]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON record must be an object"):
                inspect_dataset(str(path), str(SCHEMA))


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.service = PlatformService(self.workspace.name)

    def test_catalog_exposes_switchable_components(self) -> None:
        catalog = self.service.catalog()
        self.assertEqual({item["id"] for item in catalog["datasets"]}, {"quadmix"})
        self.assertEqual({item["id"] for item in catalog["algorithms"]}, {"quadmix"})
        self.assertEqual({item["id"] for item in catalog["trainers"]}, {"nanochat"})
        self.assertEqual({item["id"] for item in catalog["evaluators"]}, {"stem"})
        self.assertIn("local", {item["id"] for item in catalog["executors"]})
        self.assertIn("hpc-cluster", {item["id"] for item in catalog["executors"]})

    def test_job_builds_separate_stages(self) -> None:
        payload = json.loads((ROOT / "examples" / "platform" / "sample_job.json").read_text(encoding="utf-8"))
        payload["dataset_uri"] = str(JSON_DATASET)
        payload["schema_uri"] = str(SCHEMA)
        # Stub the local executor so no real subprocess is spawned.
        self.service.executors.get("local").submit = lambda job: (
            "SUCCEEDED", f"stub-{job.id}", "stubbed submission",
        )
        job = self.service.create_job(payload)
        self.assertEqual(job["status"], "SUCCEEDED")
        self.assertEqual(
            [stage["name"] for stage in job["stages"]],
            ["quadmix-selection", "nanochat-train-evaluate"],
        )
        trainer_stage = job["stages"][1]
        self.assertEqual(trainer_stage["env"]["EVAL_BENCHMARKS"], "stem")
        self.assertEqual(trainer_stage["env"]["STEM_TASKS"], "gsm8k,mmlu_stem,arc_easy")
        self.assertEqual(
            trainer_stage["env"]["STEM_DATA_DIR"], job["request"]["dataset_uri"]
        )
        self.assertEqual(trainer_stage["executable"], "python")
        self.assertTrue(trainer_stage["args"][0].endswith("run_nanochat_validation.py"))

        reloaded = PlatformService(self.workspace.name).get_job(job["id"])
        self.assertEqual(reloaded["id"], job["id"])
        self.assertEqual(reloaded["status"], "SUCCEEDED")

    def test_invalid_dataset_is_never_submitted(self) -> None:
        payload = json.loads((ROOT / "examples" / "platform" / "sample_job.json").read_text(encoding="utf-8"))
        payload["dataset_uri"] = str(ROOT / "missing.csv")
        payload["schema_uri"] = str(SCHEMA)
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.service.create_job(payload)

    def test_current_runtime_rejects_csv_instead_of_scheduling_hidden_conversion(self) -> None:
        report = self.service.inspect_dataset({
            "dataset_uri": str(DATASET),
            "schema_uri": str(SCHEMA),
        })
        self.assertFalse(report["valid"])
        self.assertTrue(any("不会自动转换" in error for error in report["errors"]))

    def test_unknown_component_fails_before_submission(self) -> None:
        payload = json.loads((ROOT / "examples" / "platform" / "sample_job.json").read_text(encoding="utf-8"))
        payload["dataset_uri"] = str(JSON_DATASET)
        payload["schema_uri"] = str(SCHEMA)
        payload["algorithm_id"] = "not-installed"
        with self.assertRaisesRegex(ValueError, "unknown component"):
            self.service.create_job(payload)

    def test_relative_paths_are_resolved_from_workspace(self) -> None:
        workspace = Path(self.workspace.name)
        dataset = workspace / "dataset.json"
        schema = workspace / "schema.yaml"
        dataset.write_text(JSON_DATASET.read_text(encoding="utf-8"), encoding="utf-8")
        schema.write_text(SCHEMA.read_text(encoding="utf-8"), encoding="utf-8")
        report = self.service.inspect_dataset({
            "dataset_uri": "dataset.json",
            "schema_uri": "schema.yaml",
        })
        self.assertTrue(report["valid"], report["errors"])

    def test_legacy_component_fields_are_normalized(self) -> None:
        config = PipelineConfig({
            "dataset_uri": str(DATASET),
            "schema_uri": str(SCHEMA),
            "format_validator_id": "quadmix",
            "algorithm_id": "quadmix",
            "trainer_id": "nanochat",
            "validator_id": "stem",
            "validator_config": {"tasks": ["gsm8k"]},
        }).to_job_request()
        self.assertEqual(config["dataset_id"], "quadmix")
        self.assertEqual(config["evaluator_id"], "stem")
        self.assertEqual(config["evaluator_config"], {"tasks": ["gsm8k"]})
        self.assertNotIn("validator_id", config)
if __name__ == "__main__":
    unittest.main()
