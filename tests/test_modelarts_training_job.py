from __future__ import annotations

import unittest
from unittest import mock

import modelarts_training_job as modelarts


class _Response:
    def json(self) -> dict[str, object]:
        return {"metadata": {"id": "job-42", "name": "amt-test"}}


class ModelArtsJobTests(unittest.TestCase):
    def test_job_data_matches_multinode_mount_contract(self) -> None:
        job = modelarts.job_data
        self.assertIn("auto_mixture_tool.cli run", job["algorithm"]["command"])
        self.assertIn("command -v python3.11", job["algorithm"]["command"])
        self.assertIn("python_wheels_dir_7", job["algorithm"]["command"])
        self.assertIn("scripts/modelarts_runtime_check.py", job["algorithm"]["command"])
        self.assertIn("export AMT_PYTHON_EXECUTABLE=$PY311", job["algorithm"]["command"])
        self.assertIn("exec $PY311 -m auto_mixture_tool.cli", job["algorithm"]["command"])
        self.assertNotIn("AMT_PYTHON_EXECUTABLE", job["algorithm"]["environments"])
        self.assertEqual(job["spec"]["resource"]["node_count"], 2)
        inputs = {item["name"]: item for item in job["algorithm"]["inputs"]}
        self.assertEqual(len(inputs), 8)
        self.assertEqual(
            inputs["quadmix_tokenizer_dir"]["local_dir"],
            "/home/ma-user/modelarts/inputs/quadmix_tokenizer_dir_4",
        )
        self.assertEqual(
            inputs["proxy_validation_dir"]["local_dir"],
            "/home/ma-user/modelarts/inputs/proxy_validation_dir_5",
        )
        self.assertEqual(
            inputs["eval_bundle_dir"]["local_dir"],
            "/home/ma-user/modelarts/inputs/eval_bundle_dir_6",
        )
        self.assertEqual(
            inputs["python_wheels_dir"]["local_dir"],
            "/home/ma-user/modelarts/inputs/python_wheels_dir_7",
        )
        self.assertTrue(all(item["access_method"] == "env" for item in inputs.values()))

    def test_update_parameter_updates_or_appends(self) -> None:
        parameters = [{"name": "nodes", "value": "1"}]
        modelarts.update_parameter(parameters, "nodes", "2")
        modelarts.update_parameter(parameters, "new", "value")
        self.assertEqual(parameters[0]["value"], "2")
        self.assertEqual(parameters[1], {"name": "new", "value": "value"})

    @mock.patch("modelarts_training_job.requests.post", return_value=_Response())
    def test_main_posts_sample_structure(self, post: mock.Mock) -> None:
        with mock.patch.dict(
            modelarts.headers,
            {"region": "cn-test-1", "Authorization": "test-token"},
        ):
            modelarts.main()
        request = post.call_args
        self.assertIs(request.kwargs["json"], modelarts.job_data)
        self.assertFalse(request.kwargs["verify"])
        self.assertNotIn("Authorization", str(request.kwargs["json"]))


if __name__ == "__main__":
    unittest.main()
