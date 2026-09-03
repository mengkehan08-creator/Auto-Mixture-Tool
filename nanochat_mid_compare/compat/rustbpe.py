"""Inference-only fallback for NanoChat environments without ``rustbpe``.

NanoChat imports rustbpe at module load time, but an existing tokenizer.pkl is
decoded with tiktoken and does not use the Rust trainer. This fallback allows
training/evaluation with that existing tokenizer while keeping tokenizer
training explicitly unavailable.
"""


class Tokenizer:
    def __init__(self, *args, **kwargs):
        raise RuntimeError(
            "rustbpe is not installed; training a new tokenizer is unavailable. "
            "Use the mounted NanoChat tokenizer.pkl or install rustbpe in the image."
        )
