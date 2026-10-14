"""Training-data format adapters."""

from .adapters import ExternalHadoopArtifact, NoOpTrainingDataAdapter

__all__ = ["NoOpTrainingDataAdapter", "ExternalHadoopArtifact"]
