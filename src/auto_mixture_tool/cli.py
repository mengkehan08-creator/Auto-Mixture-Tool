"""CLI entry point for Auto-Mixture-Tool.

Layer 1 exposes exactly two ways to run the platform:

* ``serve``  -- launch the HTTP API (FastAPI).
* ``run --config <yaml>`` -- execute a pipeline from a YAML config file.

Dataset inspection, JSON job submission, and component catalog are exposed
only through the HTTP API (see ``auto_mixture_tool.api.server``).
"""

from __future__ import annotations

import argparse
import json

from auto_mixture_tool.config.pipeline_config import PipelineConfig
from auto_mixture_tool.pipeline import PipelineManager


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-Mixture-Tool CLI")
    parser.add_argument("--workspace", default=None, help="repository root")
    sub = parser.add_subparsers(dest="command", required=True)

    serve_parser = sub.add_parser("serve", help="start the HTTP API server")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8080)

    run_parser = sub.add_parser("run", help="run from a YAML pipeline config")
    run_parser.add_argument("config", help="path to the YAML config file")

    args = parser.parse_args()

    if args.command == "serve":
        from auto_mixture_tool.api.server import main as api_main

        import sys
        sys.argv = ["auto-mixture", "--host", args.host, "--port", str(args.port)]
        if args.workspace:
            sys.argv.extend(["--workspace", args.workspace])
        api_main()
        return

    # args.command == "run"
    manager = PipelineManager(args.workspace)
    config = PipelineConfig.from_yaml(args.config)
    value = manager.submit(config.to_job_request())
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
