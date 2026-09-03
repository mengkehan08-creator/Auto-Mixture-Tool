from __future__ import annotations

import io
import types
import unittest
from contextlib import redirect_stderr
from unittest import mock

from scripts import modelarts_runtime_check


class ModelArtsRuntimeCheckTests(unittest.TestCase):
    def test_reports_all_import_failures_in_one_run(self) -> None:
        def fake_import(name: str) -> object:
            if name in {"missing_one", "broken_two"}:
                raise ImportError(f"cannot import {name}")
            return types.SimpleNamespace()

        stderr = io.StringIO()
        with (
            mock.patch.object(
                modelarts_runtime_check,
                "REQUIRED_MODULES",
                ("missing_one", "broken_two"),
            ),
            mock.patch.dict("os.environ", {"NANOCHAT_DISABLE_WANDB": "0"}),
            mock.patch.object(
                modelarts_runtime_check.importlib,
                "import_module",
                side_effect=fake_import,
            ),
            redirect_stderr(stderr),
        ):
            result = modelarts_runtime_check.main()

        self.assertEqual(result, 1)
        output = stderr.getvalue()
        self.assertIn("missing_one: ImportError", output)
        self.assertIn("broken_two: ImportError", output)


if __name__ == "__main__":
    unittest.main()
