from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CommandSpec:
    name: str
    executable: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class JobRecord:
    id: str
    status: str
    request: dict[str, Any]
    stages: list[CommandSpec]
    executor: str
    external_id: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["stages"] = [stage.to_dict() for stage in self.stages]
        return value
