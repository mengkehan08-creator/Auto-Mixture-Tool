from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .models import CommandSpec, JobRecord


class AlgorithmAdapter(ABC):
    id: str
    display_name: str

    @abstractmethod
    def build(self, request: dict[str, Any], workspace: Path) -> list[CommandSpec]: ...


class TrainerAdapter(ABC):
    id: str
    display_name: str

    @abstractmethod
    def build(self, request: dict[str, Any], workspace: Path) -> list[CommandSpec]: ...


class ValidatorAdapter(ABC):
    id: str
    display_name: str

    @abstractmethod
    def environment(self, config: dict[str, Any]) -> dict[str, str]: ...


class FormatValidatorAdapter(ABC):
    """Swappable data-format conformance checker.

    A format validator decides whether a dataset matches a specific on-disk /
    schema format *standard* (e.g. "QuadMix format": required columns present,
    domain labels non-empty and drawn from the declared ``domain_names`` set,
    quality columns numeric and not all-null, text non-empty, ...).

    This is intentionally separate from the statistical ``inspect_dataset``
    checks so that the format standard itself can be swapped without touching
    the rest of the pipeline.

    ``validate`` receives a request dict with at least ``dataset_uri``,
    ``schema_uri`` and ``sample_size`` and returns::

        {
            "valid": bool,
            "errors": list[str],
            "warnings": list[str],
            "details": dict[str, Any],
        }
    """

    id: str
    display_name: str

    @abstractmethod
    def validate(self, request: dict[str, Any]) -> dict[str, Any]: ...

    def prepare(
        self, request: dict[str, Any], workspace: Path
    ) -> tuple[str, list[CommandSpec]]:
        """Return ``(prepared_dataset_uri, preparation_stages)``.

        Dataset plugins that already receive their native format can keep the
        default no-op behavior. Other plugins may compile conversion stages.
        """
        return str(request["dataset_uri"]), []


class ExecutorAdapter(ABC):
    id: str
    display_name: str

    @abstractmethod
    def submit(self, job: JobRecord) -> tuple[str, str, str]:
        """Return (status, external_id, message)."""

    def refresh(self, job: JobRecord) -> tuple[str, str] | None:
        """Return an updated ``(status, message)`` when supported.

        Synchronous executors do not need to implement this hook. Remote
        executors can use it to refresh a persisted job from their API.
        """
        return None


# ============================================================================
# Phase 1 canonical interfaces (per the 9-layer reconstruction spec)
# ----------------------------------------------------------------------------
# The four interfaces below are the *contract* the whole platform is built on.
# They are intentionally independent of any execution mechanism (local script,
# Slurm, REST cluster). The ``*Adapter`` classes (above) are one concrete
# realization strategy: they emit ``CommandSpec``s that an ``ExecutorAdapter``
# ships to a cluster. During Phase 2 the existing QuadMix / NanoChat / STEM
# code is extracted *into* concrete implementations of these interfaces.
# ============================================================================

from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class Sample:
    """Layer 5 primitive: the single internal record shape every algorithm sees.

    Raw datasets arrive in all sorts of shapes (``text/domain``,
    ``content/category``, ``instruction/response/subject`` ...). After entering
    the :class:`UnifiedDataset` they are normalized to this structure so that
    no mixing algorithm, trainer or evaluator ever has to care about the
    original on-disk format.
    """

    id: str
    text: str
    domain: str
    metadata: dict[str, Any] = field(default_factory=dict)


class UnifiedDataset(ABC):
    """Layer 5: Unified Dataset Interface.

    Isolates *raw data format* from *algorithm implementation*. A concrete
    implementation is created from any raw source (CSV / JSONL / Parquet ...)
    together with a :class:`DatasetSchema`, then exposes a uniform iterator of
    :class:`Sample` objects to every downstream component.
    """

    #: schema used to map raw columns onto the :class:`Sample` shape
    schema: Any = None

    @abstractmethod
    def __iter__(self) -> Iterator[Sample]: ...

    @abstractmethod
    def domains(self) -> list[str]:
        """Distinct domain labels present in the dataset."""

    @property
    @abstractmethod
    def size(self) -> int: ...

    @abstractmethod
    def subset(self, indices: list[int]) -> "UnifiedDataset":
        """Return a view containing only the samples at ``indices``."""


class MixingAlgorithm(ABC):
    """Layer 6: data-ratio mixing algorithm interface.

    Every mixing algorithm — QuadMix, Random, Manual, or a future LongTailMix —
    implements this same contract, so the Pipeline can swap algorithms without
    knowing anything about their internals::

        algorithm = registry.get("quadmix")   # or "random" / "longtail_mix"
        algorithm.fit(dataset)
        mixed = algorithm.select(dataset)
        uri = algorithm.export(output_dir)
    """

    id: str
    display_name: str

    @abstractmethod
    def fit(self, dataset: UnifiedDataset) -> None:
        """Learn whatever parameters the algorithm needs from ``dataset``."""

    @abstractmethod
    def select(self, dataset: UnifiedDataset) -> UnifiedDataset:
        """Return the selected / re-weighted subset of ``dataset``."""

    @abstractmethod
    def export(self, output_dir: str | Path, fmt: str = "json") -> str:
        """Persist the mixed dataset; return its URI."""


class Trainer(ABC):
    """Layer 7a: downstream training interface.

    A trainer turns a (mixed) :class:`UnifiedDataset` into a model checkpoint.
    NanoChat, a future Qwen/LLaMA trainer, or a custom trainer all implement
    this interface, so swapping the training framework never touches the
    mixing algorithm or the evaluator.
    """

    id: str
    display_name: str

    @abstractmethod
    def train(self, dataset: UnifiedDataset, output_dir: str | Path) -> dict[str, Any]:
        """Train and return checkpoint info (``checkpoint_uri``, ``log_uri`` ...)."""


class Evaluator(ABC):
    """Layer 7b: evaluation interface — kept *separate* from :class:`Trainer`.

    An evaluator scores a trained checkpoint. STEM, Coding (HumanEval/MBPP),
    MMLU, GSM8K or a custom benchmark all implement this interface, so the
    validation method is independently swappable::

        QuadMix -> NanoChat -> STEM
        QuadMix -> NanoChat -> HumanEval
        LongTailMix -> Qwen -> STEM + MMLU + GSM8K
    """

    id: str
    display_name: str

    @abstractmethod
    def evaluate(self, checkpoint: dict[str, Any], dataset: UnifiedDataset | None = None) -> dict[str, float]:
        """Return a mapping of metric name -> score."""
