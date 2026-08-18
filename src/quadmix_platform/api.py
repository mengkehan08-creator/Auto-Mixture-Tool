from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .service import PlatformService


class PlatformApiHandler(BaseHTTPRequestHandler):
    service: PlatformService

    def _json(self, status: int, value: object) -> None:
        body = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2 * 1024 * 1024:
            raise ValueError("request body exceeds 2 MiB")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/v1/health":
                self._json(200, {"status": "ok", "service": "quadmix-platform"})
            elif path == "/api/v1/components":
                self._json(200, self.service.catalog())
            elif path.startswith("/api/v1/jobs/"):
                self._json(200, self.service.get_job(path.rsplit("/", 1)[-1]))
            else:
                self._json(404, {"error": "API route not found"})
        except ValueError as exc:
            self._json(404, {"error": str(exc)})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            payload = self._body()
            if path == "/api/v1/datasets/inspect":
                self._json(200, self.service.inspect_dataset(payload))
            elif path == "/api/v1/jobs":
                self._json(201, self.service.create_job(payload))
            else:
                self._json(404, {"error": "API route not found"})
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            self._json(502, {"error": str(exc)})

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[api] {self.address_string()} - {fmt % args}")


def create_server(host: str = "127.0.0.1", port: int = 8080, workspace: str | None = None) -> ThreadingHTTPServer:
    service = PlatformService(workspace)
    handler = type(
        "ConfiguredPlatformApiHandler",
        (PlatformApiHandler,),
        {"service": service},
    )
    return ThreadingHTTPServer((host, port), handler)


def serve(host: str = "127.0.0.1", port: int = 8080, workspace: str | None = None) -> None:
    server = create_server(host, port, workspace)
    print(f"QuadMix virtual platform API: http://{host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
