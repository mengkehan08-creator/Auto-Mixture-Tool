"""Runtime compatibility for the pinned Ascend PyTorch environment."""

from __future__ import annotations

import torch
import torch.nn.functional as functional


if not hasattr(functional, "rms_norm"):

    def rms_norm(input, normalized_shape, weight=None, eps=None):
        """Differentiable RMSNorm fallback matching ``torch.nn.functional``."""
        shape = tuple(normalized_shape)
        if not shape or tuple(input.shape[-len(shape):]) != shape:
            raise ValueError(
                f"normalized_shape={shape} does not match input shape={tuple(input.shape)}"
            )
        dimensions = tuple(range(input.ndim - len(shape), input.ndim))
        epsilon = torch.finfo(input.dtype).eps if eps is None else eps
        float_input = input.float()
        output = float_input * torch.rsqrt(
            float_input.square().mean(dim=dimensions, keepdim=True) + epsilon
        )
        output = output.to(dtype=input.dtype)
        if weight is not None:
            output = output * weight
        return output

    functional.rms_norm = rms_norm
