"""The Tessa Server entry point.

    tessa-server              run with settings from environment variables

See config/settings.py for the full list of TESSA_SERVER_* env vars.
"""

from __future__ import annotations

from fastapi import FastAPI

from tessa_server import __version__
from tessa_server.api.v1 import router as v1_router
from tessa_server.config.settings import get_settings


def create_app() -> FastAPI:
    app = FastAPI(title="Tessa Server", version=__version__)
    app.include_router(v1_router)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_settings()
    if not settings.tokens:
        raise SystemExit(
            "No auth tokens configured. Set TESSA_SERVER_TOKEN (single user) "
            "or TESSA_SERVER_TOKENS (comma-separated token:user pairs) before starting."
        )
    uvicorn.run(
        "tessa_server.main:app",
        host=settings.host,
        port=settings.port,
        ssl_keyfile=settings.ssl_keyfile,
        ssl_certfile=settings.ssl_certfile,
    )


if __name__ == "__main__":
    run()
