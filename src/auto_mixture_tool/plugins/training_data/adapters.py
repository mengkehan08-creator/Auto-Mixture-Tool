"""Adapters between a mixing algorithm output and a trainer input."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from auto_mixture_tool.plugins.base import CommandSpec, TrainingDataAdapter


class NoOpTrainingDataAdapter(TrainingDataAdapter):
    """Keep the algorithm's Parquet output unchanged."""

    id = "none"
    display_name = "Use mixing output without format conversion"

    def prepare(
        self, request: dict[str, Any], workspace: Path, mixed_uri: str
    ) -> tuple[str, list[CommandSpec]]:
        return mixed_uri, []


class ExternalHadoopArtifact(TrainingDataAdapter):
    """Consume a format-converted artifact produced by an external Hadoop job.

    This adapter deliberately does not pretend to submit Hadoop while its API
    contract is unknown.  It is used for a split workflow: finish QuaDMix,
    manually/externally run Hadoop, then submit the training job with the
    resulting artifact mounted locally.
    """

    id = "external-hadoop-artifact"
    display_name = "Existing Hadoop-converted training artifact"

    def prepare(
        self, request: dict[str, Any], workspace: Path, mixed_uri: str
    ) -> tuple[str, list[CommandSpec]]:
        config = request.get("training_data_adapter_config", {})
        prepared_uri = config.get("prepared_uri")
        if not prepared_uri:
            raise ValueError(
                "external-hadoop-artifact requires "
                "training_data_adapter_config.prepared_uri"
            )
        target_format = str(config.get("target_format", "jsonl")).lower()
        if target_format not in {"json", "jsonl", "parquet"}:
            raise ValueError("external Hadoop target_format must be json, jsonl, or parquet")
        return str(prepared_uri), []
