"""STEM evaluation plugin with customizable task list and validation data.

Produces the environment variables consumed by the NanoChat STEM experiment
scripts. ``tasks`` and ``validation_data_uri`` are forwarded verbatim so the
benchmark set can be changed without touching the trainer code.
"""

from __future__ import annotations

from typing import Any

from auto_mixture_tool.plugins.base import ValidatorAdapter


class StemValidator(ValidatorAdapter):
    id = "stem"
    display_name = "Customizable STEM evaluation"

    def environment(self, config: dict[str, Any]) -> dict[str, str]:
        env = {"EVAL_BENCHMARKS": str(config.get("benchmarks", "stem"))}
        if config.get("validation_data_uri"):
            env["STEM_VALIDATION_DATA"] = str(config["validation_data_uri"])
        if config.get("tasks"):
            tasks = config["tasks"]
            if isinstance(tasks, list) and not all(
                isinstance(task, str) and task.strip() for task in tasks
            ):
                raise ValueError("stem tasks must be non-empty strings")
            env["STEM_TASKS"] = ",".join(tasks) if isinstance(tasks, list) else str(tasks)
        return env
