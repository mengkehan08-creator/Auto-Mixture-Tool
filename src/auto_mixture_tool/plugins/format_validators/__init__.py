"""Data-format validator plugins.

A format validator checks whether a dataset matches a specific on-disk /
schema format standard. The default ``quadmix`` validator enforces the
QuadMix format (required columns, non-empty & expected domain labels, numeric
quality columns, non-empty text). Other standards can be added and swapped in
via ``PlatformService`` registration — see docs/AUTO_MIXTURE_TOOL.md.
"""

from __future__ import annotations

from auto_mixture_tool.plugins.format_validators.quadmix import QuadMixFormatValidator

__all__ = ["QuadMixFormatValidator"]
