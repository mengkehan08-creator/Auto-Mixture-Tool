"""Pipeline configuration helpers.

Loads a single YAML file that describes a full experiment: dataset, schema,
selected plugins, and per-plugin configs. This is the configuration management
layer called out in the architecture diagram.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class PipelineConfig:
    """Normalized experiment configuration for all switchable components."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PipelineConfig":
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
        if not isinstance(data, dict):
            raise ValueError("pipeline config must be a YAML mapping")
        return cls(data)

    @property
    def dataset_uri(self) -> str:
        return str(self._data["dataset_uri"])

    @property
    def schema_uri(self) -> str:
        return str(self._data["schema_uri"])

    @property
    def output_uri(self) -> str | None:
        return self._data.get("output_uri")

    @property
    def algorithm_id(self) -> str:
        return str(self._data.get("algorithm_id", "quadmix"))

    @property
    def trainer_id(self) -> str:
        value = str(self._data.get("trainer_id", "nanochat"))
        return "nanochat" if value == "nanochat-stem" else value

    @property
    def evaluator_id(self) -> str:
        return str(self._data.get("evaluator_id") or self._data.get("validator_id", "stem"))

    @property
    def executor_id(self) -> str:
        return str(self._data.get("executor_id", "local"))

    @property
    def dataset_id(self) -> str:
        return str(self._data.get("dataset_id") or self._data.get("format_validator_id", "quadmix"))

    def to_job_request(self) -> dict[str, Any]:
        """Convert this config into the JSON shape accepted by the API/CLI."""
        sections = {
            "algorithm_config": self._data.get("algorithm_config", {}),
            "trainer_config": self._data.get("trainer_config", {}),
            "evaluator_config": self._data.get(
                "evaluator_config", self._data.get("validator_config", {})
            ),
            "executor_config": self._data.get("executor_config", {}),
        }
        invalid = [name for name, value in sections.items() if not isinstance(value, dict)]
        if invalid:
            raise ValueError(f"pipeline config sections must be mappings: {', '.join(invalid)}")
        full_scan = self._data.get("full_scan", False)
        if not isinstance(full_scan, bool):
            raise ValueError("full_scan must be a boolean")
        return {
            "dataset_uri": self.dataset_uri,
            "schema_uri": self.schema_uri,
            "dataset_id": self.dataset_id,
            "output_uri": self.output_uri,
            "algorithm_id": self.algorithm_id,
            "trainer_id": self.trainer_id,
            "evaluator_id": self.evaluator_id,
            "executor_id": self.executor_id,
            "full_scan": full_scan,
            **sections,
        }
