"""Pipeline manager for Auto-Mixture-Tool.

Wires together dataset validation, algorithm selection, trainer/validator
selection, and executor submission. This is the orchestration layer that both
the CLI and API use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from auto_mixture_tool.data.validator import validate_dataset


class PipelineManager:
    """High-level pipeline orchestrator.

    The manager uses ``PlatformService`` for component discovery and command
    generation, and adds an explicit validation step with extended statistics
    before any job is created.
    """

    def __init__(self, workspace: str | Path | None = None) -> None:
        self.workspace = Path(workspace or Path(__file__).resolve().parents[2]).resolve()
        # Lazy import: ``quadmix_platform.service`` pulls in the numpy / pandas
        # heavy path, so we only import it when a PipelineManager is actually
        # constructed (avoids a circular import with ``auto_mixture_tool``).
        from quadmix_platform.service import PlatformService

        self.service = PlatformService(self.workspace)

    def catalog(self) -> dict[str, Any]:
        """Return the catalog of switchable components."""
        return self.service.catalog()

    def validate(
        self,
        dataset_uri: str,
        schema_uri: str,
        sample_size: int = 1000,
        format_validator_id: str = "quadmix",
    ) -> dict[str, Any]:
        """Validate a dataset against a schema with extended statistics.

        ``format_validator_id`` selects the swappable data-format conformance
        checker (default ``quadmix``).
        """
        return validate_dataset(dataset_uri, schema_uri, sample_size, format_validator_id)

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate data and submit a pipeline job."""
        return self.service.create_job(payload)

    def get_job(self, job_id: str) -> dict[str, Any]:
        """Return the state of a previously submitted job."""
        return self.service.get_job(job_id)
