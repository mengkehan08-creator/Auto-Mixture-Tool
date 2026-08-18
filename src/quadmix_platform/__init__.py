"""Platform-facing integration layer for QuaDMix and pluggable validators.

The heavy ``PlatformService`` (which pulls in QuadMix / NanoChat / STEM plugins
and requires numpy / pandas) is exposed lazily via ``__getattr__`` so that the
lightweight contract modules (``quadmix_platform.interfaces``,
``quadmix_platform.models``) and the Phase-1 canonical core remain importable
on a stdlib-only environment — and so importing this package never triggers a
circular import with ``auto_mixture_tool``.
"""

from __future__ import annotations

__version__ = "0.1.0"


def __getattr__(name: str):
    if name == "PlatformService":
        from .service import PlatformService

        return PlatformService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["PlatformService"]
