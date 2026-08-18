"""Layer 7a: Trainer implementations.

``NoOpTrainer`` is the reference (no downstream training). ``CommandDrivenTrainer``
is the Phase-1 bridge wrapping a command-emitting ``TrainerAdapter``
(e.g. ``NanoChatTrainer``) into the canonical :class:`Trainer` contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quadmix_platform.interfaces import Trainer, UnifiedDataset
from quadmix_platform.models import CommandSpec


class NoOpTrainer(Trainer):
    """Reference trainer: skip downstream training (mixing-only experiments)."""

    id = "none-core"
    display_name = "Skip downstream training (reference)"

    def train(self, dataset: UnifiedDataset, output_dir: str | Path) -> dict[str, Any]:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        return {"checkpoint_uri": str(out / "skipped"), "log_uri": "", "status": "skipped"}


class CommandDrivenTrainer(Trainer):
    """Bridge: adapt a command-emitting ``TrainerAdapter`` to this interface."""

    def __init__(self, adapter: Any, workspace: str | Path, job_id: str = "local") -> None:
        self.adapter = adapter
        self.workspace = Path(workspace)
        self.job_id = job_id
        self.id = adapter.id
        self.display_name = getattr(adapter, "display_name", adapter.id)
        self._plan: list[CommandSpec] = []

    def _request(self, dataset: UnifiedDataset) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "workspace": self.workspace,
            "dataset_uri": getattr(dataset, "path", ""),
            "schema_uri": "",
            "output_uri": str(self.workspace / "result" / self.job_id),
            "trainer_config": {},
            "validator_config": {},
        }

    def train(self, dataset: UnifiedDataset, output_dir: str | Path) -> dict[str, Any]:
        self._plan = self.adapter.build(self._request(dataset), self.workspace)
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        uri = str(out / "train_plan.json")
        with open(uri, "w", encoding="utf-8") as f:
            json.dump([s.to_dict() for s in self._plan], f, indent=2, default=str)
        return {"checkpoint_uri": str(out / "checkpoint"), "plan_uri": uri, "status": "planned"}
