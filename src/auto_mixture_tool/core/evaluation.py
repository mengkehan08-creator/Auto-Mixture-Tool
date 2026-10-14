"""Layer 7b: Evaluator implementations (kept separate from Trainer).

``StubEvaluator`` is the reference. ``CommandDrivenEvaluator`` is the Phase-1
bridge wrapping a :class:`ValidatorAdapter` (e.g. ``StemValidator``): it
captures the evaluation environment the trainer will use. A full in-process
STEM / Coding evaluator is extracted in Phase 2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quadmix_platform.interfaces import Evaluator, UnifiedDataset


class StubEvaluator(Evaluator):
    """Reference evaluator: returns a placeholder metric without running eval."""

    id = "stub-core"
    display_name = "Stub evaluator (reference)"

    def evaluate(self, checkpoint: dict[str, Any], dataset: UnifiedDataset | None = None) -> dict[str, float]:
        return {"stub_score": 0.0}


class CommandDrivenEvaluator(Evaluator):
    """Bridge: capture a :class:`ValidatorAdapter`'s eval environment.

    The wrapped validator's ``environment(config)`` describes how the trainer
    should evaluate (benchmarks, tasks, data uri). Phase 2 turns this into a
    real ``evaluate()`` that runs STEM / Coding and returns metric scores.
    """

    def __init__(self, validator: Any, config: dict[str, Any] | None = None) -> None:
        self.validator = validator
        self.config = config or {}
        self.id = validator.id
        self.display_name = getattr(validator, "display_name", validator.id)
        self._env: dict[str, str] = {}

    def evaluate(self, checkpoint: dict[str, Any], dataset: UnifiedDataset | None = None) -> dict[str, float]:
        self._env = self.validator.environment(self.config)
        return {}  # real metrics produced by the executor in Phase 2

    def export_env(self, output_dir: str | Path) -> str:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        uri = str(out / "eval_env.json")
        with open(uri, "w", encoding="utf-8") as f:
            json.dump(self._env, f, indent=2, default=str)
        return uri
