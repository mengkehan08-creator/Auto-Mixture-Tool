import copy
import json
import shutil
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from test_modelarts_workflow import FakeClient, config
from auto_mixture_tool.modelarts.workflow import ModelArtsWorkflowManager
from auto_mixture_tool.sampling.artifacts import manual_plans


@pytest.fixture
def manager(tmp_path):
    shutil.copyfile(Path(__file__).resolve().parents[1] / "modelarts_training_job.py",
                    tmp_path / "modelarts_training_job.py")
    result = ModelArtsWorkflowManager(tmp_path, FakeClient())
    yield result
    result.close()


def finish(manager, record):
    for _ in range(500):
        value = manager.get(record["id"])
        if value["status"] in {"SUCCEEDED", "FAILED", "NEEDS_ATTENTION"} and record["id"] not in manager._active:
            return value
        threading.Event().wait(0.002)
    raise AssertionError("workflow did not finish")


def test_custom_output_and_idempotency(manager):
    body = config()
    body["request_id"] = "test-request-1234"
    body["output_root_obs_uri"] = "obs://other-bucket/custom-output/"
    with patch("auto_mixture_tool.modelarts.workflow.time.sleep"):
        created = manager.create(body)
        current = finish(manager, created)
        again = manager.create(body)
    assert current["status"] == "SUCCEEDED"
    assert again["id"] == created["id"]
    assert len(manager.client.submissions) == 2
    assert current["outputs"]["sampled"].startswith("obs://other-bucket/custom-output/runs/")
    second = manager.client.submissions[1]["algorithm"]
    sampled = next(x for x in second["inputs"] if x["name"] == "comparison_data_dir")
    assert sampled["remote"]["obs"]["obs_url"] == current["outputs"]["sampled"]
    assert second["outputs"][0]["remote"]["obs"]["obs_url"] == current["run_root_obs_uri"] + "/"


def test_separate_model_and_report_outputs(manager):
    body = config()
    body['training']['output_obs_uri'] = 'obs://models-bucket/checkpoints/'
    body['evaluation']['output_obs_uri'] = 'obs://reports-bucket/comparisons/'
    with patch.object(manager, '_start'):
        created = manager.create(body)
    record = manager.records[created['id']]
    outputs = manager._payload(record, 'training')['algorithm']['outputs']
    for name, root in [('models', 'obs://models-bucket/checkpoints'), ('reports', 'obs://reports-bucket/comparisons')]:
        target = next(item for item in outputs if item['name'] == name + '_output')
        assert target['remote']['obs']['obs_url'] == f"{root}/runs/{created['name']}/"
        assert target['remote']['obs']['obs_url'] == created['outputs'][name]
        assert target['local_dir'].endswith('/' + name + '_output')
    assert len(manager._payload(record, 'mixing')['algorithm']['outputs']) == 1
    assert manager.copy_configuration(created['id'])['training']['output_obs_uri'] == 'obs://models-bucket/checkpoints'
    body['evaluation']['output_obs_uri'] = '/tmp/reports'
    with pytest.raises(ValueError):
        manager.create(body)


def test_ui_parameters_and_credentials_are_isolated(manager):
    body = config()
    body["modelarts"] = {
        "endpoint": "https://modelarts.example/jobs", "region": "test-region",
        "authorization": "test-secret-value", "workspace_id": "workspace-ui",
        "image_url": "registry/image:version", "image_repo_id": "image-ui",
        "flavor_id": "flavor-ui", "pool_id": "pool-ui",
    }
    assert manager.preview(body)["ready"]
    with patch.object(manager, "_start"):
        public = manager.create(body)
    record = manager.records[public["id"]]
    for stage in ("mixing", "training"):
        payload = manager._payload(record, stage)
        assert payload["metadata"]["workspace_id"] == "workspace-ui"
        assert payload["algorithm"]["engine"]["image_repo_id"] == "image-ui"
        assert payload["spec"]["resource"]["pool_id"] == "pool-ui"
        assert "test-secret-value" not in json.dumps(payload)
    assert manager._client(record).headers["Authorization"] == "test-secret-value"
    assert "test-secret-value" not in json.dumps(public)
    copied = manager.copy_configuration(public['id'])
    assert 'authorization' not in copied['modelarts']
    assert 'request_id' not in copied
    copied['training']['base_model_tag'] = 'changed'
    assert record['config']['training'].get('base_model_tag') != 'changed'
    assert "test-secret-value" not in (manager.directory / f"{public['id']}.json").read_text(encoding="utf-8")
    assert "REPLACE_ME_AUTHORIZATION" in (manager.workspace / "modelarts_training_job.py").read_text(encoding="utf-8")
    restored = ModelArtsWorkflowManager(manager.workspace)
    restored.resume()
    assert restored.get(public["id"])["status"] == "WAITING_AUTH"
    with patch.object(restored, "_start") as start:
        restored.renew_authorization(public["id"], "replacement-secret")
        start.assert_called_once_with(public["id"])
    restored.close()


def test_ui_rejects_unsafe_endpoint_and_header(manager):
    body = config()
    body["modelarts"] = {"endpoint": "https://example.com/jobs?token=secret"}
    with pytest.raises(ValueError, match="HTTPS"):
        manager.preview(body)
    body["modelarts"] = {"endpoint": "https://example.com/jobs", "authorization": "x\nInjected: y"}
    with pytest.raises(ValueError, match="换行"):
        manager.preview(body)


def test_remote_error_details_clear_progress(manager):
    manager.client.submit = lambda payload: {"error_code": "ModelArts.2788", "error_msg": "镜像仓库不存在"}
    with patch("auto_mixture_tool.modelarts.workflow.time.sleep"):
        result = finish(manager, manager.create(config()))
    assert result["status"] == "FAILED"
    assert result["progress"] == 0
    assert "ModelArts.2788" in result["message"]
    assert "镜像仓库不存在" in result["message"]
    assert result["outputs"]["sampled"]


def test_response_console_link_and_http_error():
    from auto_mixture_tool.modelarts.workflow import _console_url, _response_data, ModelArtsRejected
    assert _console_url({"metadata": {"console_url": "https://console.example/jobs/123"}}) == "https://console.example/jobs/123"
    assert not _console_url({"job_url": "javascript:alert(1)"})
    response = requests.Response()
    response.status_code = 400
    response._content = b'{"error_code":"BadImage","error_msg":"image not found"}'
    with pytest.raises(ModelArtsRejected, match="BadImage.*image not found"):
        _response_data(response)


def test_training_console_url():
    from auto_mixture_tool.modelarts.workflow import training_console_url
    url = training_console_url("32359996-89c0-4a4d-bf2c-3e18c896fe13", "cn-south-1", "aifm-lmdt-exp_MA_workspace")
    assert url == ("https://console.huaweicloud.com/modelarts/?locale=zh-cn&region=cn-south-1"
                   "#/training/detail/32359996-89c0-4a4d-bf2c-3e18c896fe13?workspaceName=aifm-lmdt-exp_MA_workspace")
    assert training_console_url("", "cn-south-1") == ""
    assert "workspaceName" not in training_console_url("job1", "cn-south-1")
    assert "workspaceName=a%26b" in training_console_url("job1", "cn-south-1", "a&b")


@pytest.mark.parametrize("key,value", [("num_iterations", -1), ("num_iterations", 1.5),
                                      ("device_batch_size", 0), ("eval_every", 0),
                                      ("core_metric_every", -2)])
def test_invalid_training_controls(manager, key, value):
    body = config()
    body["training"][key] = value
    with pytest.raises(ValueError, match=key):
        manager._validate(body)


def test_training_controls_saved_for_copy(manager):
    body = config()
    body['training'].update(num_iterations=15, device_batch_size=2, eval_every=10, core_metric_every=-1)
    with patch.object(manager, '_start'):
        created = manager.create(body)
    copied = manager.copy_configuration(created['id'])
    assert copied['training']['num_iterations'] == 15
    assert copied['training']['device_batch_size'] == 2


def test_custom_commands_are_used_and_copied(manager):
    body = config()
    body['commands'] = {'mixing': 'bash custom_mix.sh', 'training': 'bash custom_train.sh'}
    with patch.object(manager, '_start'):
        created = manager.create(body)
    record = manager.records[created['id']]
    for stage in ('mixing', 'training'):
        assert manager._payload(record, stage)['algorithm']['command'] == body['commands'][stage]
    assert manager.copy_configuration(created['id'])['commands'] == body['commands']


@pytest.mark.parametrize('commands', [{}, {'mixing': 'x'}, {'mixing': '', 'training': 'y'},
                                     {'mixing': 'x', 'training': 'bad\x00command'}])
def test_invalid_commands_rejected(manager, commands):
    body = config()
    body['commands'] = commands
    with pytest.raises(ValueError, match='command'):
        manager._validate(body)


def test_command_defaults_match_runtime():
    from auto_mixture_tool.api.server import workflow_defaults
    assert workflow_defaults()['commands'] == {
        stage: ModelArtsWorkflowManager._command(stage) for stage in ('mixing', 'training')
    }


def test_offline_resources_custom_names_and_mounts(manager):
    body = config()
    roles = ['code_obs_uri', 'quadmix_tokenizer_obs_uri', 'proxy_validation_obs_uri', 'eval_bundle_obs_uri', 'python_wheels_obs_uri']
    body['offline_resources'] = [{'role': role, 'name': 'resource_' + str(i), 'uri': body['resources'][role]}
                                 for i, role in enumerate(roles)]
    body['offline_resources'].append({'name': 'extra_data', 'uri': 'obs://extra-bucket/data'})
    with patch.object(manager, '_start'):
        created = manager.create(body)
    inputs = manager._payload(manager.records[created['id']], 'mixing')['algorithm']['inputs']
    renamed = next(item for item in inputs if item['name'] == 'resource_2')
    assert renamed['local_dir'].endswith('proxy_validation_dir_5')
    extra = next(item for item in inputs if item['name'] == 'extra_data')
    assert extra['local_dir'].endswith('/custom/extra_data')
    assert manager.copy_configuration(created['id'])['offline_resources'] == manager._validate(body)['offline_resources']
    body['offline_resources'] = []
    with pytest.raises(ValueError, match='删除默认'):
        manager._validate(body)


@pytest.mark.parametrize("uri", ["https://console.example/obs", "obs://", "obs://bucket/a?token=x", "obs://bucket/../x"])
def test_invalid_obs_rejected_before_submission(manager, uri):
    body = config()
    body["output_root_obs_uri"] = uri
    with pytest.raises(ValueError):
        manager.create(body)
    assert manager.client.submissions == []


def test_failed_mixing_never_starts_training(manager):
    manager.client.get = lambda _: {"status": "Failed"}
    with patch("auto_mixture_tool.modelarts.workflow.time.sleep"):
        result = finish(manager, manager.create(config()))
    assert result["status"] == "FAILED"
    assert len(manager.client.submissions) == 1


def test_transient_query_does_not_resubmit(manager):
    with patch.object(manager.client, "get", side_effect=[requests.ConnectionError(), {"status": "Completed"}, {"status": "Completed"}]), patch("auto_mixture_tool.modelarts.workflow.time.sleep"):
        result = finish(manager, manager.create(config()))
    assert result["status"] == "SUCCEEDED"
    assert len(manager.client.submissions) == 2


def test_resume_uses_existing_job_id(manager):
    with patch.object(manager, "_start"):
        created = manager.create(config())
    record = manager.records[created["id"]]
    record["jobs"][0].update(id="existing-job", status="RUNNING")
    record["status"] = "MIXING_RUNNING"
    manager._store(record)
    restored = ModelArtsWorkflowManager(manager.workspace, FakeClient())
    with patch("auto_mixture_tool.modelarts.workflow.time.sleep"):
        restored.resume()
        result = finish(restored, created)
    assert result["status"] == "SUCCEEDED"
    assert len(restored.client.submissions) == 1
    assert restored.client.events[0] == "get:existing-job"
    restored.close()


def test_uncertain_create_is_not_retried(manager):
    with patch.object(manager.client, "submit", side_effect=requests.Timeout()), patch("auto_mixture_tool.modelarts.workflow.time.sleep"):
        result = finish(manager, manager.create(config()))
    assert result["status"] == "NEEDS_ATTENTION"
    restored = ModelArtsWorkflowManager(manager.workspace, FakeClient())
    restored.resume()
    assert restored.client.submissions == []


def test_preview_reports_missing_configuration_without_creating(manager):
    result = manager.preview(config())
    assert not result["ready"]
    assert "Authorization" in result["missing_settings"]
    assert manager.client.submissions == []
    assert "REPLACE_ME" not in json.dumps(result)


def test_manual_manifest_relocates_between_jobs(tmp_path):
    data = tmp_path / "manual_ratio_data"
    data.mkdir()
    (data / "part.parquet").write_bytes(b"test fixture")
    manifest = [{"id": "manual_a", "label": "A", "tokens": 100,
                 "data_dir": "/home/ma-user/modelarts/outputs/output_dir_0/sampled/data/manual_ratio_data"}]
    (tmp_path / "manual_plans_manifest.json").write_text(json.dumps(manifest))
    assert manual_plans(tmp_path)[0]["data_dir"] == str(data.resolve())


def test_api_validation_and_submission_use_real_routes(manager):
    from fastapi.testclient import TestClient
    from auto_mixture_tool.api.server import app
    with patch.object(app.state, "workflow_manager", manager, create=True), TestClient(app) as client:
        assert client.get("/ui").status_code == 200
        checked = client.post("/api/v1/workflows/validate", json=config())
        assert checked.status_code == 200
        assert not checked.json()["ready"]
        assert manager.client.submissions == []
        with patch("auto_mixture_tool.modelarts.workflow.time.sleep"):
            response = client.post("/api/v1/workflows", json=config())
            assert response.status_code == 202
            completed = finish(manager, response.json())
        assert completed["status"] == "SUCCEEDED"
        assert client.get("/api/v1/workflows").json()[0]["id"] == completed["id"]
