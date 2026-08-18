"""Custom evaluation plugin.

Allows an arbitrary downstream evaluation command to be plugged in. The only
contract is that the trainer/script understands ``EVAL_COMMAND`` and
``VALIDATION_DATA_URI`` environment variables.
"""

from __future__ import annotations

from typing import Any

from auto_mixture_tool.plugins.base import ValidatorAdapter


class CustomValidator(ValidatorAdapter):
    id = "custom"
    display_name = "Custom evaluator"

    def environment(self, config: dict[str, Any]) -> dict[str, str]:
        env: dict[str, str] = {}
        if config.get("validation_data_uri"):
            env["VALIDATION_DATA_URI"] = str(config["validation_data_uri"])
        if config.get("eval_command"):
            env["EVAL_COMMAND"] = str(config["eval_command"])
        if config.get("benchmarks"):
            env["EVAL_BENCHMARKS"] = str(config["benchmarks"])
        return env
