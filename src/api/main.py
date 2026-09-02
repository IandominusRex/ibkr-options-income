"""FastAPI application factory.

This process holds NO ib_async connection and therefore no clientId. It cannot reach the
broker, by construction. See design §4.2.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routers import meta
from src.common.config import get_config

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    cfg = get_config()
    app = FastAPI(
        title="IBKR Income System — Web API",
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.research.api.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(404)
    async def _not_found(_request: Request, _exc: Exception) -> JSONResponse:
        """JSON, never HTML: the client parses every response as JSON."""
        return JSONResponse(status_code=404, content={"detail": "Not found"})

    app.include_router(meta.router)
    return app
