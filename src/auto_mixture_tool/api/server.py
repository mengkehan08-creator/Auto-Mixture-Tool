"""FastAPI server for Auto-Mixture-Tool.

Provides an independent, visible REST API for dataset validation, component
catalog, job submission, and result retrieval. The contract is aligned with
``openapi/quadmix-platform.yaml``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from auto_mixture_tool.pipeline import PipelineManager

app = FastAPI(title="Auto-Mixture-Tool API", version="0.1.0")


class InspectRequest(BaseModel):
    dataset_uri: str
    schema_uri: str
    sample_size: int = Field(default=1000, ge=1, le=10000)
    format_validator_id: str = "quadmix"


class JobRequest(BaseModel):
    dataset_uri: str
    schema_uri: str
    output_uri: str | None = None
    algorithm_id: str = "quadmix"
    trainer_id: str = "nanochat-stem"
    validator_id: str = "stem"
    executor_id: str = "local"
    format_validator_id: str = "quadmix"
    algorithm_config: dict[str, Any] = Field(default_factory=dict)
    trainer_config: dict[str, Any] = Field(default_factory=dict)
    validator_config: dict[str, Any] = Field(default_factory=dict)
    executor_config: dict[str, Any] = Field(default_factory=dict)


def _manager() -> PipelineManager:
    workspace = app.state.workspace if hasattr(app.state, "workspace") else None
    return PipelineManager(workspace)


@app.on_event("startup")
def _startup() -> None:
    app.state.workspace = Path(__file__).resolve().parents[3]


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "auto-mixture-tool"}


@app.get("/api/v1/components")
def components() -> dict[str, Any]:
    return _manager().catalog()


@app.post("/api/v1/datasets/inspect")
def inspect(payload: InspectRequest) -> dict[str, Any]:
    try:
        return _manager().validate(
            payload.dataset_uri, payload.schema_uri, payload.sample_size, payload.format_validator_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/v1/jobs")
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
