"""Compatibility entry point for the single Auto-Mixture-Tool HTTP API."""

from __future__ import annotations

from pathlib import Path


def serve(
    host: str = "127.0.0.1",
    port: int = 8080,
    workspace: str | None = None,
) -> None:
    """Serve the canonical FastAPI application without a second job store."""
    import uvicorn
    from auto_mixture_tool.api.server import app

    if workspace:
        app.state.workspace = Path(workspace).resolve()
    uvicorn.run(app, host=host, port=port)
