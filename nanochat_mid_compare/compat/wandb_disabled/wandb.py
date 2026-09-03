"""Minimal no-op WandB API for NanoChat runs with tracking disabled."""

from __future__ import annotations

from typing import Any


class _DisabledRun:
    def log(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def finish(self, *_args: Any, **_kwargs: Any) -> None:
        return None


run = _DisabledRun()


def init(*_args: Any, **_kwargs: Any) -> _DisabledRun:
    return run


def log(*_args: Any, **_kwargs: Any) -> None:
    return None


def finish(*_args: Any, **_kwargs: Any) -> None:
    return None
