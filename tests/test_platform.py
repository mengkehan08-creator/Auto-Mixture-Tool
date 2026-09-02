from __future__ import annotations

import json
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from quadmix import DatasetSchema
from quadmix_platform.dataset_inspector import _data_files, inspect_dataset
from quadmix_platform.service import PlatformService
from quadmix_platform.components import HpcClusterExecutor, LocalExecutor
from quadmix_platform.models import CommandSpec, JobRecord
from auto_mixture_tool.config.pipeline_config import PipelineConfig
from auto_mixture_tool.plugins.algorithms.quadmix import QuadMixAlgorithm
from auto_mixture_tool.plugins.trainers.nanochat import NanoChatTrainer


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

    def test_numeric_shard_range_is_inclusive_and_ignores_zero_padding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("part-00000", "part-00199", "part-00200", "part-001000"):
                (root / name).write_text('{}\n', encoding="utf-8")

            first_200 = _data_files(root, 0, 199)
            through_1000 = _data_files(root, 0, 1000)

        self.assertEqual(
            [path.name for path in first_200],
            ["part-00000", "part-00199"],
        )
        self.assertEqual(
            [path.name for path in through_1000],
            ["part-00000", "part-00199", "part-00200", "part-001000"],
        )


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.service = PlatformService(self.workspace.name)

    def test_catalog_exposes_switchable_components(self) -> None:
        catalog = self.service.catalog()
        self.assertEqual(
            {item["id"] for item in catalog["datasets"]},
            {"quadmix", "stem-json-parquet"},
        )
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
        self.assertEqual(trainer_stage["env"]["SCHEMA_CONFIG"], str(SCHEMA))
        self.assertEqual(trainer_stage["executable"], "bash")
        self.assertTrue(trainer_stage["args"][0].endswith("run_stem_experiment.sh"))
        self.assertEqual(trainer_stage["env"]["COMPARISON_METHODS"], "quadmix")
        self.assertEqual(trainer_stage["env"]["MIX_GENERAL_DATA"], "0")

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

    def test_comparison_config_is_passed_to_nanochat(self) -> None:
        config = PipelineConfig({
            "dataset_uri": str(DATASET),
            "schema_uri": str(SCHEMA),
            "comparison_config": {
                "methods": ["quadmix", "random", "manual"],
                "manual_ratios": {
                    "数学": 0.60,
                    "物理": 0.15,
                    "化学": 0.125,
                    "生物学": 0.125,
                },
            },
        }).to_job_request()
        config.update({
            "job_id": "0123456789ab",
            "evaluator_id": "stem",
            "trainer_config": {"npu_devices": 8},
            "_evaluator_env": {},
        })

        stage = NanoChatTrainer().build(config, ROOT)[0]

        self.assertEqual(stage.env["COMPARISON_METHODS"], "quadmix,random,manual")
        self.assertEqual(
            stage.env["MANUAL_RATIO"],
            "数学=0.6:物理=0.15:化学=0.125:生物学=0.125",
        )
        self.assertEqual(stage.env["AMT_RUN_ID"], "0123456789ab")

    def test_quadmix_adapter_passes_proxy_training_steps(self) -> None:
        request = {
            "job_id": "0123456789ab",
            "dataset_uri": str(DATASET),
            "schema_uri": str(SCHEMA),
            "algorithm_config": {"tiny_steps": 5000},
        }

        stage = QuadMixAlgorithm().build(request, ROOT)[0]

        index = stage.args.index("--tiny-steps")
        self.assertEqual(stage.args[index + 1], "5000")


class ExecutorTests(unittest.TestCase):
    def _job(self, executor: str, executor_config: dict | None = None) -> JobRecord:
        return JobRecord(
            id="0123456789ab",
            status="VALIDATED",
            request={
                "dataset_id": "quadmix",
                "algorithm_id": "quadmix",
                "trainer_id": "nanochat",
                "evaluator_id": "stem",
                "algorithm_config": {"device_type": "npu", "npu_devices": 8},
                "trainer_config": {"npu_devices": 8},
                "executor_config": executor_config or {},
            },
            stages=[CommandSpec("stage", "python", ["run.py"])],
            executor=executor,
        )

    @mock.patch("quadmix_platform.components.subprocess.run")
    def test_local_executor_injects_eight_npu_environment(self, run: mock.Mock) -> None:
        run.return_value.returncode = 0
        job = self._job("local", {"device_type": "npu", "device_count": 8})

        status, external_id, _ = LocalExecutor().submit(job)

        self.assertEqual(status, "SUCCEEDED")
        self.assertEqual(external_id, "local:0123456789ab")
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["NUM_NPU"], "8")
        self.assertEqual(environment["RANK_SIZE"], "8")
        self.assertEqual(environment["ASCEND_VISIBLE_DEVICES"], "0,1,2,3,4,5,6,7")

    def test_local_executor_rejects_inconsistent_device_counts(self) -> None:
        job = self._job("local", {"device_type": "npu", "device_count": 4})
        with self.assertRaisesRegex(ValueError, "must match"):
            LocalExecutor().submit(job)

    @mock.patch.dict("os.environ", {"TEST_HPC_TOKEN": "secret"})
    @mock.patch("quadmix_platform.components.urllib.request.urlopen")
    def test_hpc_executor_submits_resources_and_refreshes_status(self, urlopen: mock.Mock) -> None:
        submit_response = io.BytesIO(json.dumps({"jobId": "hpc-42", "state": "queued"}).encode())
        status_response = io.BytesIO(json.dumps({"state": "completed"}).encode())
        urlopen.side_effect = [submit_response, status_response]
        config = {
            "endpoint": "https://hpc.example/api/jobs",
            "status_endpoint": "https://hpc.example/api/jobs/{job_id}",
            "token_env": "TEST_HPC_TOKEN",
            "job_id_field": "jobId",
            "status_field": "state",
            "status_map": {"queued": "SUBMITTED", "completed": "SUCCEEDED"},
            "queue": "npu-dev",
            "image": "amt:test",
            "resources": {"nodes": 1, "npu": 8},
        }
        job = self._job("hpc-cluster", config)
        executor = HpcClusterExecutor()

        status, external_id, _ = executor.submit(job)
        job.status, job.external_id = status, external_id
        refreshed = executor.refresh(job)

        self.assertEqual((status, external_id), ("SUBMITTED", "hpc-42"))
        self.assertEqual(refreshed, ("SUCCEEDED", "Refreshed from HPC cluster API."))
        submit_request = urlopen.call_args_list[0].args[0]
        payload = json.loads(submit_request.data)
        self.assertEqual(payload["resources"], {"nodes": 1, "npu": 8})
        self.assertEqual(payload["queue"], "npu-dev")
        self.assertEqual(submit_request.get_header("Authorization"), "Bearer secret")
        status_request = urlopen.call_args_list[1].args[0]
        self.assertEqual(status_request.full_url, "https://hpc.example/api/jobs/hpc-42")
        self.assertEqual(status_request.get_method(), "GET")
if __name__ == "__main__":
    unittest.main()
