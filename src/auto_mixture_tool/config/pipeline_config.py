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
    """Experiment configuration with four plugin-specific sections."""

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
        return str(self._data.get("trainer_id", "none"))

    @property
    def validator_id(self) -> str:
        return str(self._data.get("validator_id", "core"))

    @property
    def executor_id(self) -> str:
        return str(self._data.get("executor_id", "local"))

    @property
    def format_validator_id(self) -> str:
        return str(self._data.get("format_validator_id", "quadmix"))

    def to_job_request(self) -> dict[str, Any]:
        """Convert this config into the JSON shape accepted by the API/CLI."""
        return {
            "dataset_uri": self.dataset_uri,
            "schema_uri": self.schema_uri,
            "output_uri": self.output_uri,
            "algorithm_id": self.algorithm_id,
            "trainer_id": self.trainer_id,
            "validator_id": self.validator_id,
            "executor_id": self.executor_id,
            "format_validator_id": self.format_validator_id,
            "algorithm_config": self._data.get("algorithm_config", {}),
            "trainer_config": self._data.get("trainer_config", {}),
            "validator_config": self._data.get("validator_config", {}),
            "executor_config": self._data.get("executor_config", {}),
        }
