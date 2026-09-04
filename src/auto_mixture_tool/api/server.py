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
from pydantic import BaseModel, Field

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
    experiment_name: str | None = None
    input_data_obs_uri: str
    output_root_obs_uri: str
    mixing_nodes: int = Field(default=2, ge=1, le=16)
    training_nodes: int = Field(default=2, ge=1, le=16)
    full_scan: bool = False
    strategies: list[dict[str, Any]]
    training: dict[str, Any]
    evaluation: dict[str, Any]
    resources: dict[str, str]
    poll_interval_seconds: int = Field(default=15, ge=2, le=300)


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
    _workflow_manager()


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
    return RedirectResponse("/ui")


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


@app.get("/api/v1/workflows")
def list_workflows() -> list[dict[str, Any]]:
    return _workflow_manager().list()


@app.get("/api/v1/workflows/{workflow_id}")
def get_workflow(workflow_id: str) -> dict[str, Any]:
    try:
        return _workflow_manager().get(workflow_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
