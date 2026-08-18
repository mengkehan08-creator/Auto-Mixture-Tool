"""QuadMix algorithm plugin.

This is a thin wrapper around the original QuadMix algorithm so that it lives
in the same plugin namespace as Random and Manual Ratio. The actual
implementation remains in ``quadmix_platform.components.QuadMixAlgorithm``.
"""

from __future__ import annotations

from quadmix_platform.components import QuadMixAlgorithm as _QuadMixAlgorithm


class QuadMixAlgorithm(_QuadMixAlgorithm):
    """QuadMix data mixing algorithm, exposed as a swappable plugin."""
