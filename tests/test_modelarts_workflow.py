import tempfile
import shutil
import threading
import unittest
import pytest
pytestmark = pytest.mark.usefixtures('mock_resource_preflight')
from pathlib import Path
from unittest.mock import patch

from auto_mixture_tool.modelarts.workflow import ModelArtsWorkflowManager, _state


class FakeClient:
    def __init__(self):
        self.submissions = []
        self.events = []

    def submit(self, payload):
        self.submissions.append(payload)
        job_id = f"job-{len(self.submissions)}"
        self.events.append(f"submit:{job_id}")
        return {"metadata": {"id": job_id}}

    def get(self, job_id):
        self.events.append(f"get:{job_id}")
        return {"metadata": {"status": "Completed"}}


def config():
    return {
        "experiment_name": "two-stage-test",
        "input_data_obs_uri": "obs://bucket/data/",
        "output_root_obs_uri": "obs://bucket/output/",
        "mixing_nodes": 2,
        "training_nodes": 3,
        "poll_interval_seconds": 2,
        "strategies": [
            {"id": "quadmix", "type": "quadmix", "name": "QuaDMix"},
            {"id": "manual_a", "type": "manual", "name": "Manual A", "ratios": {"数学": 1.0}},
        ],
        "training": {"base_model_tag": "d24", "devices_per_node": 8},
        "evaluation": {"datasets": ["stem"]},
        "resources": {
            "code_obs_uri": "obs://bucket/code/",
            "nanochat_repo_obs_uri": "obs://bucket/nanochat/",
            "nanochat_model_obs_uri": "obs://bucket/model/",
            "quadmix_tokenizer_obs_uri": "obs://bucket/tokenizer/",
            "proxy_validation_obs_uri": "obs://bucket/proxy/",
            "eval_bundle_obs_uri": "obs://bucket/eval/",
            "python_wheels_obs_uri": "obs://bucket/wheels/",
        },
    }


class WorkflowTests(unittest.TestCase):
    def test_state_reads_nested_modelarts_response(self):
        self.assertEqual(_state({"metadata": {"status": "Completed"}}), "Completed")
        self.assertEqual(
            _state({"status": {"phase": "Pending", "secondary_phase": "OSQueuing"}}),
            "Pending",
        )

    @patch("auto_mixture_tool.modelarts.workflow.time.sleep", return_value=None)
    def test_second_job_is_submitted_only_after_first_succeeds(self, _sleep):
        fake = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            shutil.copyfile(Path(__file__).resolve().parents[1] / "modelarts_training_job.py",
                            Path(directory) / "modelarts_training_job.py")
            manager = ModelArtsWorkflowManager(Path(directory), fake)
            created = manager.create(config())
            for _ in range(100):
                current = manager.get(created["id"])
                if current["status"] in {"SUCCEEDED", "FAILED"}:
                    break
                threading.Event().wait(0.001)
            self.assertEqual(current["status"], "SUCCEEDED")
            self.assertEqual(fake.events, [
                "submit:job-1", "get:job-1", "submit:job-2", "get:job-2", "submit:job-3", "get:job-3"
            ])
            self.assertEqual(current["jobs"][0]["nodes"], 2)
            self.assertEqual(current["jobs"][1]["nodes"], 3)
            self.assertTrue(current["outputs"]["sampled"].endswith("/sampled/"))
            mixing_inputs = {
                item["name"] for item in fake.submissions[0]["algorithm"]["inputs"]
            }
            training_inputs = {
                item["name"] for item in fake.submissions[1]["algorithm"]["inputs"]
            }
            self.assertIn("data_dir", mixing_inputs)
            self.assertNotIn("eval_bundle_dir", mixing_inputs)
            self.assertNotIn("data_dir", training_inputs)
            self.assertIn("comparison_data_dir", training_inputs)
            self.assertIn("eval_bundle_dir", training_inputs)


if __name__ == "__main__":
    unittest.main()
