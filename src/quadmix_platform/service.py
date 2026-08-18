from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from auto_mixture_tool.plugins.algorithms.manual import ManualRatioAlgorithm
from auto_mixture_tool.plugins.algorithms.quadmix import QuadMixAlgorithm
from auto_mixture_tool.plugins.algorithms.random import RandomAlgorithm
from auto_mixture_tool.plugins.format_validators.quadmix import QuadMixFormatValidator
from auto_mixture_tool.plugins.validators.custom import CustomValidator
from .components import (
    HpcClusterExecutor, LocalExecutor, NanoChatCoreValidator, NanoChatTrainer, NoTrainer,
    StemValidator,
)
from .dataset_inspector import inspect_dataset
from .models import JobRecord
from .registry import ComponentRegistry


class PlatformService:
    def __init__(self, workspace: str | Path | None = None) -> None:
        self.workspace = Path(workspace or Path(__file__).resolve().parents[2]).resolve()
        self.algorithms = ComponentRegistry()
        self.validators = ComponentRegistry()
        self.trainers = ComponentRegistry()
        self.executors = ComponentRegistry()
        self.format_validators = ComponentRegistry()
        self.jobs: dict[str, JobRecord] = {}

        # Algorithm plugins: QuadMix plus swappable baselines.
        self.algorithms.register(QuadMixAlgorithm())
        self.algorithms.register(RandomAlgorithm())
        self.algorithms.register(ManualRatioAlgorithm())

        # Validator plugins: CORE / STEM / custom.
        core = NanoChatCoreValidator()
        stem = StemValidator()
        custom = CustomValidator()
        self.validators.register(core)
        self.validators.register(stem)
        self.validators.register(custom)

        # Trainer plugins. Reusing NanoChat for multiple validator combinations.
        self.trainers.register(NoTrainer())
        self.trainers.register(NanoChatTrainer(core))
        stem_trainer = NanoChatTrainer(stem)
        stem_trainer.id = "nanochat-stem"
        stem_trainer.display_name = "NanoChat mid-training + STEM"
        self.trainers.register(stem_trainer)
        custom_trainer = NanoChatTrainer(custom)
        custom_trainer.id = "nanochat-custom"
        custom_trainer.display_name = "NanoChat mid-training + custom eval"
        self.trainers.register(custom_trainer)

        # Executor plugins: local subprocess (dev) + HPC cluster API (production).
        self.executors.register(LocalExecutor())
        self.executors.register(HpcClusterExecutor())

        # Format validator plugins: check dataset matches a format standard.
        self.format_validators.register(QuadMixFormatValidator())

    def catalog(self) -> dict[str, Any]:
        return {
            "algorithms": self.algorithms.catalog(),
            "trainers": self.trainers.catalog(),
            "validators": self.validators.catalog(),
            "executors": self.executors.catalog(),
            "format_validators": self.format_validators.catalog(),
        }

    def inspect_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        return inspect_dataset(payload["dataset_uri"], payload["schema_uri"], int(payload.get("sample_size", 100)))

    def create_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        required = ["dataset_uri", "schema_uri", "algorithm_id", "trainer_id", "validator_id", "executor_id"]
        missing = [name for name in required if not payload.get(name)]
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")

        # Gate 1: structural / statistical validation.
        inspection = self.inspect_dataset(payload)
        if not inspection["valid"]:
            raise ValueError("dataset validation failed: " + "; ".join(inspection["errors"]))

        # Gate 2: swappable data-format conformance check.
        format_validator_id = str(payload.get("format_validator_id", "quadmix"))
        format_check = self.format_validators.get(format_validator_id).validate(payload)
        if not format_check["valid"]:
            raise ValueError("dataset format check failed: " + "; ".join(format_check["errors"]))

        job_id = uuid.uuid4().hex[:12]
        request = dict(payload)
        request["job_id"] = job_id
        algorithm = self.algorithms.get(request["algorithm_id"])
        validator = self.validators.get(request["validator_id"])
        trainer = self.trainers.get(request["trainer_id"])
        if isinstance(trainer, NanoChatTrainer) and trainer.validator.id != validator.id:
            trainer = NanoChatTrainer(validator)
        stages = algorithm.build(request, self.workspace) + trainer.build(request, self.workspace)
        job = JobRecord(job_id, "VALIDATED", request, stages, request["executor_id"])
        self.jobs[job_id] = job
        try:
            status, external_id, message = self.executors.get(job.executor).submit(job)
            job.status, job.external_id, job.message = status, external_id, message
        except Exception as exc:
            job.status, job.message = "FAILED", str(exc)
            raise
        return job.to_dict()

    def get_job(self, job_id: str) -> dict[str, Any]:
        if job_id not in self.jobs:
            raise ValueError(f"job not found: {job_id}")
        return self.jobs[job_id].to_dict()
