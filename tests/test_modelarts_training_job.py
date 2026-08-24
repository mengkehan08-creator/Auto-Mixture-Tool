from __future__ import annotations

import io
import json
import os
import unittest
from unittest import mock

import modelarts_training_job as modelarts


ENVIRONMENT = {
    "MODELARTS_AUTHORIZATION": "test-token",
    "MODELARTS_ENDPOINT": "https://modelarts.example/v2/project/training-jobs",
    "MODELARTS_REGION": "cn-test-1",
    "MODELARTS_WORKSPACE_ID": "workspace",
    "MODELARTS_IMAGE_URL": "registry/amt:latest",
    "MODELARTS_IMAGE_REPO_ID": "image-repo",
    "MODELARTS_CODE_OBS_URL": "/bucket/amt/",
    "MODELARTS_DATA_OBS_URL": "/bucket/data/",
    "MODELARTS_NANOCHAT_REPO_OBS_URL": "/bucket/nanochat/",
    "MODELARTS_NANOCHAT_MODEL_OBS_URL": "/bucket/model/",
    "MODELARTS_OUTPUT_OBS_URL": "/bucket/output/",
    "MODELARTS_FLAVOR_ID": "8xnpu",
    "MODELARTS_NODE_COUNT": "1",
    "MODELARTS_POOL_ID": "pool",
    "MODELARTS_RESOURCE_POLICY": "regular",
}


class ModelArtsJobTests(unittest.TestCase):
    @mock.patch.dict(os.environ, ENVIRONMENT, clear=True)
    def test_builds_complete_pipeline_job(self) -> None:
        job = modelarts.build_job_data("amt-test")
        self.assertEqual(job["metadata"]["name"], "amt-test")
        self.assertIn("auto-mixture run", job["algorithm"]["command"])
        self.assertIn("modelarts_pipeline.yaml", job["algorithm"]["command"])
        self.assertEqual(job["spec"]["resource"]["node_count"], 1)
        self.assertEqual(len(job["algorithm"]["inputs"]), 3)
        self.assertNotIn("volumes", job["spec"])

    @mock.patch.dict(os.environ, ENVIRONMENT, clear=True)
    @mock.patch("modelarts_training_job.urllib.request.urlopen")
    def test_submits_and_reads_nested_job_id(self, urlopen: mock.Mock) -> None:
        urlopen.return_value = io.BytesIO(
            json.dumps({"metadata": {"id": "job-42", "name": "amt-test"}}).encode()
        )
        value = modelarts.submit_job(modelarts.build_job_data("amt-test"))
        self.assertEqual(modelarts.response_job(value), ("job-42", "amt-test"))
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "test-token")
        payload = json.loads(request.data)
        self.assertNotIn("Authorization", json.dumps(payload))

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_missing_configuration_fails_before_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "MODELARTS_WORKSPACE_ID"):
            modelarts.build_job_data("amt-test")


if __name__ == "__main__":
    unittest.main()
