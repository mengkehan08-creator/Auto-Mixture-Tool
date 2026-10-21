"""FastAPI server for Auto-Mixture-Tool.

Provides an independent, visible REST API for dataset validation, component
catalog, job submission, and result retrieval. The contract is aligned with
``openapi/quadmix-platform.yaml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field, StrictInt

from auto_mixture_tool.pipeline import PipelineManager
from auto_mixture_tool.modelarts import ModelArtsWorkflowManager

app = FastAPI(title="Auto-Mixture-Tool API", version="0.1.0")
_STATIC_DIR = Path(__file__).resolve().parent / "static"


class InspectRequest(BaseModel):
    dataset_uri: str
    schema_uri: str
    sample_size: int = Field(default=1000, ge=1, le=10000)
    dataset_id: str = "quadmix"
    format_validator_id: str | None = None
    full_scan: bool = False
    dataset_config: dict[str, Any] = Field(default_factory=dict)


class JobRequest(BaseModel):
    dataset_uri: str
    schema_uri: str
    dataset_id: str = "quadmix"
    output_uri: str | None = None
    algorithm_id: str = "quadmix"
    trainer_id: str = "nanochat"
    training_data_adapter_id: str = "none"
    evaluator_id: str = "stem"
    executor_id: str = "local"
    dataset_config: dict[str, Any] = Field(default_factory=dict)
    algorithm_config: dict[str, Any] = Field(default_factory=dict)
    comparison_config: dict[str, Any] = Field(default_factory=dict)
    trainer_config: dict[str, Any] = Field(default_factory=dict)
    training_data_adapter_config: dict[str, Any] = Field(default_factory=dict)
    evaluator_config: dict[str, Any] = Field(default_factory=dict)
    executor_config: dict[str, Any] = Field(default_factory=dict)
    # Read-only compatibility with configurations written before the component
    # names were unified. New clients should use dataset_id/evaluator_id.
    format_validator_id: str | None = None
    validator_id: str | None = None
    validator_config: dict[str, Any] | None = None
    full_scan: bool = False


class WorkflowRequest(BaseModel):
    execution_mode: str = 'sequential'
    reuse: dict[str, str] | None = None
    request_id: str | None = None
    experiment_name: str | None = None
    input_data_obs_uri: str
    output_root_obs_uri: str
    priority: int = Field(default=1, ge=1, le=3, strict=True)
    mixing_nodes: int = Field(default=2, ge=1, le=16, strict=True)
    training_nodes: int = Field(default=2, ge=1, le=16, strict=True)
    evaluation_nodes: int = Field(default=1, ge=1, le=16, strict=True)
    full_scan: bool = False
    strategies: list[dict[str, Any]]
    training: dict[str, Any]
    evaluation: dict[str, Any]
    resources: dict[str, str]
    commands: dict[str, str] | None = None
    offline_resources: list[dict[str, str]] | None = None
    modelarts: dict[str, str] | None = None
    poll_interval_seconds: int = Field(default=15, ge=2, le=300)


class ModelComparisonRequest(BaseModel):
    model_obs_uri: str = Field(max_length=2048)
    base_model_tag: str = Field(default='d24', max_length=128)
    input_data_obs_uri: str = Field(default='', max_length=2048)
    training_configs: list[dict[str, Any]] = Field(default_factory=list, max_length=32)


class TrainingPlanRequest(BaseModel):
    model_obs_uri: str = Field(max_length=2048)
    training: dict[str, Any]
    nodes: list[StrictInt] = Field(min_length=1, max_length=16)


@app.post('/api/v1/training-plan')
def training_plan_preview(payload: TrainingPlanRequest):
    from auto_mixture_tool.modelarts.training_plan import plan_training_jobs
    try:
        return plan_training_jobs(payload.model_obs_uri, [
            {'nodes': nodes, 'training': payload.training} for nodes in payload.nodes
        ])
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


class ResourceValidationRequest(BaseModel):
    kind: str
    uri: str = Field(max_length=2048)
    force: bool = False


@app.post('/api/v1/resources/validate')
def validate_resource_request(payload: ResourceValidationRequest):
    from auto_mixture_tool.modelarts.input_validation import validate_resource
    try:
        if payload.kind == 'dataset':
            from auto_mixture_tool.modelarts.dataset_checks import start_dataset_check
            return start_dataset_check(payload.uri, payload.force)
        return validate_resource(payload.kind, payload.uri)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get('/api/v1/resources/checks/{check_id}')
def dataset_check_status(check_id: str):
    from auto_mixture_tool.modelarts.dataset_checks import get_dataset_check
    try:
        return get_dataset_check(check_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _manager() -> PipelineManager:
    if not hasattr(app.state, "manager"):
        workspace = app.state.workspace if hasattr(app.state, "workspace") else None
        app.state.manager = PipelineManager(workspace)
    return app.state.manager


def _workflow_manager() -> ModelArtsWorkflowManager:
    if not hasattr(app.state, "workflow_manager"):
        workspace = app.state.workspace if hasattr(app.state, "workspace") else Path.cwd()
        app.state.workflow_manager = ModelArtsWorkflowManager(Path(workspace))
    return app.state.workflow_manager


@app.on_event("startup")
def _startup() -> None:
    if not hasattr(app.state, "workspace"):
        app.state.workspace = Path(__file__).resolve().parents[3]
    _manager()
    _workflow_manager().resume()


@app.on_event("shutdown")
def _shutdown() -> None:
    if hasattr(app.state, "workflow_manager"):
        app.state.workflow_manager.close()


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "auto-mixture-tool"}


@app.get("/ui", include_in_schema=False)
@app.get("/ui/", include_in_schema=False)
def ui() -> FileResponse:
    """Serve the experiment configuration and ModelArts workflow UI."""
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("ui")


@app.get("/ui/style.css", include_in_schema=False)
def ui_style() -> FileResponse:
    return FileResponse(_STATIC_DIR / "style.css", media_type="text/css")


@app.get("/api/v1/components")
def components() -> dict[str, Any]:
    return _manager().catalog()


@app.post("/api/v1/datasets/inspect")
def inspect(payload: InspectRequest) -> dict[str, Any]:
    try:
        return _manager().validate(
            payload.dataset_uri,
            payload.schema_uri,
            payload.sample_size,
            payload.format_validator_id or payload.dataset_id,
            payload.full_scan,
            payload.dataset_config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/jobs", status_code=201)
def create_job(payload: JobRequest) -> dict[str, Any]:
    try:
        return _manager().submit(payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/v1/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    try:
        return _manager().get_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/v1/workflows", status_code=202)
def create_workflow(payload: WorkflowRequest) -> dict[str, Any]:
    try:
        return _workflow_manager().create(payload.model_dump(exclude_none=True))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/v1/workflows/validate")
def validate_workflow(payload: WorkflowRequest) -> dict[str, Any]:
    """Validate configuration without creating or querying a paid cloud job."""
    try:
        return _workflow_manager().preview(payload.model_dump(exclude_none=True))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/workflow-defaults")
def workflow_defaults() -> dict[str, Any]:
    import os
    defaults_path = _workflow_manager().workspace / 'configs/modelarts_ui_defaults.json'
    import json
    settings = json.loads(defaults_path.read_text(encoding='utf-8')) if defaults_path.is_file() else {}
    allowed = {'endpoint', 'region', 'workspace_id', 'workspace_name', 'image_url', 'image_repo_id', 'flavor_id', 'pool_id'}
    return {"auth_mode": "iam" if os.environ.get('AMT_IAM_PROVIDER', '').strip() else "manual",
            "modelarts": {key: value for key, value in settings.items() if key in allowed},
            "commands": {stage: ModelArtsWorkflowManager._command(stage) for stage in ("mixing", "training", "evaluation")}}


@app.post('/api/v1/workflow-commands')
def workflow_commands(payload: dict[str, Any]):
    from auto_mixture_tool.modelarts.command_preview import commands_for_settings
    try:
        return {'commands': commands_for_settings(payload)}
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/workflows/{workflow_id}/authorization")
def renew_workflow_authorization(workflow_id: str, payload: dict[str, str]) -> dict[str, Any]:
    try:
        return _workflow_manager().renew_authorization(workflow_id, payload.get("authorization", ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/workflows")
def list_workflows() -> list[dict[str, Any]]:
    return _workflow_manager().list()


@app.get('/api/v1/models')
def list_models() -> list[dict[str, Any]]:
    from auto_mixture_tool.modelarts.parallel_workflow import models
    return models(_workflow_manager())


@app.post('/api/v1/models/compare')
def compare_models(payload: ModelComparisonRequest) -> list[dict[str, Any]]:
    from auto_mixture_tool.modelarts.parallel_workflow import models
    from auto_mixture_tool.modelarts.model_comparison import compare_catalog
    return compare_catalog(models(_workflow_manager()), payload.model_dump())


@app.post('/api/v1/workflows/{workflow_id}/jobs/{job_key}/retry', status_code=202)
def retry_parallel_job(workflow_id: str, job_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    from auto_mixture_tool.modelarts.parallel_workflow import retry
    try:
        return retry(_workflow_manager(), workflow_id, job_key, payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/workflows/{workflow_id}")
def get_workflow(workflow_id: str) -> dict[str, Any]:
    try:
        return _workflow_manager().get(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/workflows/{workflow_id}/configuration")
def workflow_configuration(workflow_id: str) -> dict[str, Any]:
    try:
        return _workflow_manager().copy_configuration(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get('/api/v1/workflows/{workflow_id}/analysis')
def result_analysis(workflow_id: str) -> dict[str, Any]:
    from auto_mixture_tool.modelarts.result_analysis import workflow_analysis
    manager = _workflow_manager()
    try:
        manager.get(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return workflow_analysis(manager.records[workflow_id])


@app.delete("/api/v1/workflows/{workflow_id}", status_code=202)
def delete_workflow(workflow_id: str, confirmed_not_created: bool = False) -> dict[str, Any]:
    try:
        return _workflow_manager().delete(workflow_id, confirmed_not_created=confirmed_not_created)
    except ValueError as exc:
        raise HTTPException(status_code=404 if str(exc) in {'workflow not found', 'invalid workflow id'} else 400, detail=str(exc)) from exc


def main() -> None:
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Auto-Mixture-Tool API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--workspace", default=None)
    args = parser.parse_args()
    if args.workspace:
        app.state.workspace = Path(args.workspace).resolve()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
