from __future__ import annotations

import argparse
import json

from auto_mixture_tool.config.pipeline_config import PipelineConfig
from .api import serve
from .service import PlatformService


def main() -> None:
    parser = argparse.ArgumentParser(description="QuaDMix virtual platform")
    parser.add_argument("--workspace", default=None, help="QuaDMix repository root")
    sub = parser.add_subparsers(dest="command", required=True)
    serve_parser = sub.add_parser("serve", help="start the HTTP API server")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8080)
    run_parser = sub.add_parser("run", help="run from a YAML pipeline config")
    run_parser.add_argument("config", help="path to the YAML config file")
    args = parser.parse_args()

    if args.command == "serve":
        serve(args.host, args.port, args.workspace)
        return

    # args.command == "run"
    service = PlatformService(args.workspace)
    config = PipelineConfig.from_yaml(args.config)
    value = service.create_job(config.to_job_request())
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
