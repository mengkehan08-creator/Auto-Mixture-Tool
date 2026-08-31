from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from auto_mixture_tool.plugins.algorithms.quadmix import QuadMixAlgorithm
from auto_mixture_tool.plugins.format_validators.quadmix import QuadMixFormatValidator
from auto_mixture_tool.plugins.format_validators.stem_json_parquet import (
    StemJsonParquetDataset,
)
from auto_mixture_tool.plugins.trainers.nanochat import NanoChatTrainer
from auto_mixture_tool.plugins.training_data import (
    ExternalHadoopArtifact,
    NoOpTrainingDataAdapter,
)
from auto_mixture_tool.plugins.validators.stem import StemValidator
from auto_mixture_tool.data.validator import audit_dataset, validate_dataset
from .components import HpcClusterExecutor, LocalExecutor
from .models import CommandSpec, JobRecord
from .registry import ComponentRegistry


class PlatformService:
    def __init__(self, workspace: str | Path | None = None) -> None:
        self.workspace = Path(workspace or Path(__file__).resolve().parents[2]).resolve()
        self.job_dir = self.workspace / "result" / ".jobs"
        self.algorithms = ComponentRegistry()
        self.trainers = ComponentRegistry()
        self.training_data_adapters = ComponentRegistry()
        self.evaluators = ComponentRegistry()
        self.executors = ComponentRegistry()
        self.datasets = ComponentRegistry()
        self.jobs: dict[str, JobRecord] = {}

        # One registration point for every user-switchable component family.
        self.datasets.register(QuadMixFormatValidator())
        self.datasets.register(StemJsonParquetDataset())
        self.algorithms.register(QuadMixAlgorithm())
        self.trainers.register(NanoChatTrainer())
        self.training_data_adapters.register(NoOpTrainingDataAdapter())
        self.training_data_adapters.register(ExternalHadoopArtifact())
        self.evaluators.register(StemValidator())
        self.executors.register(LocalExecutor())
        self.executors.register(HpcClusterExecutor())

    def catalog(self) -> dict[str, Any]:
        return {
            "datasets": self.datasets.catalog(),
            "algorithms": self.algorithms.catalog(),
            "trainers": self.trainers.catalog(),
            "training_data_adapters": self.training_data_adapters.catalog(),
            "evaluators": self.evaluators.catalog(),
            "executors": self.executors.catalog(),
        }

    def inspect_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(
            payload.get("dataset_id") or payload.get("format_validator_id") or "quadmix"
        )
        dataset = self.datasets.get(dataset_id)
        report = validate_dataset(
            self._resolve_local_path(payload["dataset_uri"]),
            self._resolve_local_path(payload["schema_uri"]),
            int(payload.get("sample_size", 1000)),
            format_validator=dataset,
            dataset_config=payload.get("dataset_config", {}),
        )
        if payload.get("full_scan"):
            report["full_audit"] = audit_dataset(
                self._resolve_local_path(payload["dataset_uri"]),
                self._resolve_local_path(payload["schema_uri"]),
                payload.get("dataset_config", {}),
            )
            report["valid"] = report["valid"] and report["full_audit"]["valid"]
            report["errors"] = sorted(
                set(report["errors"]) | set(report["full_audit"]["errors"])
            )
        return report

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        required = ["dataset_uri", "schema_uri"]
        missing = [name for name in required if not payload.get(name)]
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")

        request = dict(payload)
        request["dataset_uri"] = self._resolve_local_path(payload["dataset_uri"])
        request["schema_uri"] = self._resolve_local_path(payload["schema_uri"])
        if request.get("output_uri"):
            request["output_uri"] = self._resolve_local_path(request["output_uri"])
        request["dataset_id"] = str(
            payload.get("dataset_id") or payload.get("format_validator_id") or "quadmix"
        )
        request["algorithm_id"] = str(payload.get("algorithm_id") or "quadmix")
        trainer_id = str(payload.get("trainer_id") or "nanochat")
        request["trainer_id"] = "nanochat" if trainer_id == "nanochat-stem" else trainer_id
        request["training_data_adapter_id"] = str(
            payload.get("training_data_adapter_id") or "none"
        )
        request["evaluator_id"] = str(
            payload.get("evaluator_id") or payload.get("validator_id") or "stem"
        )
        request["executor_id"] = str(payload.get("executor_id") or "local")
        request.pop("format_validator_id", None)
        request.pop("validator_id", None)
        for name in (
            "dataset_config", "algorithm_config", "trainer_config", "executor_config",
            "training_data_adapter_config",
        ):
            value = request.get(name, {})
            if not isinstance(value, dict):
                raise ValueError(f"{name} must be an object")
            request[name] = value
        evaluator_config = request.get("evaluator_config") or request.get("validator_config") or {}
        if not isinstance(evaluator_config, dict):
            raise ValueError("evaluator_config must be an object")
        request["evaluator_config"] = evaluator_config
        request.pop("validator_config", None)

        # Resolve every selected component before doing the potentially expensive
        # dataset scan, so configuration errors fail fast and consistently.
        dataset = self.datasets.get(request["dataset_id"])
        algorithm = self.algorithms.get(request["algorithm_id"])
        trainer = self.trainers.get(request["trainer_id"])
        training_data_adapter = self.training_data_adapters.get(
            request["training_data_adapter_id"]
        )
        evaluator = self.evaluators.get(request["evaluator_id"])
        executor = self.executors.get(request["executor_id"])

        inspection = self.inspect_dataset(request)
        if not inspection["valid"]:
            raise ValueError("dataset validation failed: " + "; ".join(inspection["errors"]))

        job_id = uuid.uuid4().hex[:12]
        request["job_id"] = job_id
        prepared_uri, dataset_stages = dataset.prepare(request, self.workspace)
        build_request = dict(request)
        build_request["dataset_uri"] = prepared_uri
        build_request["schema_uri"] = dataset.prepared_schema_uri(
            request, self.workspace
        )
        build_request["_evaluator_env"] = evaluator.environment(
            request["evaluator_config"]
        )
        algorithm_stages = algorithm.build(build_request, self.workspace)
        mixed_uri = str(Path(request.get("output_uri") or self.workspace / "result" / job_id / "quadmix") / "sampled_dataset")
        training_uri, training_data_stages = training_data_adapter.prepare(
            build_request, self.workspace, mixed_uri
        )
        build_request["_training_dataset_uri"] = training_uri
        stages = dataset_stages + algorithm_stages + training_data_stages + trainer.build(
            build_request, self.workspace
        )
        job = JobRecord(job_id, "VALIDATED", request, stages, request["executor_id"])
        self.jobs[job_id] = job
        self._save_job(job)
        try:
            status, external_id, message = executor.submit(job)
            job.status, job.external_id, job.message = status, external_id, message
        except Exception as exc:
            job.status, job.message = "FAILED", str(exc)
            self._save_job(job)
            raise
        self._save_job(job)
        return job.to_dict()

    def get_job(self, job_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{12}", job_id):
            raise ValueError(f"invalid job id: {job_id}")
        if job_id not in self.jobs:
            path = self.job_dir / f"{job_id}.json"
            if path.exists():
                value = json.loads(path.read_text(encoding="utf-8"))
                self.jobs[job_id] = JobRecord(
                    id=value["id"],
                    status=value["status"],
                    request=value["request"],
                    stages=[CommandSpec(**stage) for stage in value["stages"]],
                    executor=value["executor"],
                    external_id=value.get("external_id"),
                    message=value.get("message", ""),
                )
            else:
                raise ValueError(f"job not found: {job_id}")
        job = self.jobs[job_id]
        if job.status not in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            refreshed = self.executors.get(job.executor).refresh(job)
            if refreshed is not None:
                job.status, job.message = refreshed
                self._save_job(job)
        return job.to_dict()

    def _save_job(self, job: JobRecord) -> None:
        self.job_dir.mkdir(parents=True, exist_ok=True)
        path = self.job_dir / f"{job.id}.json"
        temporary = self.job_dir / f".{job.id}.tmp"
        temporary.write_text(
            json.dumps(job.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _resolve_local_path(self, value: Any) -> str:
        path = Path(str(value)).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        return str(path.resolve())
