"""Data-format validator plugins.

A format validator checks whether a dataset matches a specific on-disk /
schema format standard. The default ``quadmix`` validator enforces the
QuadMix format (required columns, non-empty & expected domain labels, numeric
quality columns, non-empty text). Other standards can be added and swapped in
via ``PlatformService`` registration — see docs/AUTO_MIXTURE_TOOL.md.
"""

from __future__ import annotations

from quadmix_platform.registry import ComponentRegistry

from auto_mixture_tool.plugins.format_validators.quadmix import QuadMixFormatValidator

__all__ = ["QuadMixFormatValidator", "build_format_registry", "get_format_validator"]


def build_format_registry() -> ComponentRegistry:
    """Return a registry pre-populated with the built-in format validators."""
    registry = ComponentRegistry()
    registry.register(QuadMixFormatValidator())
    return registry


_default_registry = build_format_registry()


def get_format_validator(component_id: str = "quadmix") -> "FormatValidatorAdapter":
    """Look up a format validator by id from the built-in registry."""
    from auto_mixture_tool.plugins.base import FormatValidatorAdapter

    validator = _default_registry.get(component_id)
    if not isinstance(validator, FormatValidatorAdapter):
        raise TypeError(f"component {component_id!r} is not a FormatValidatorAdapter")
    return validator
