"""FastAPI application factory for VideoDrop."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from .config import SECURITY_HEADERS_ENABLED, SITE_DESCRIPTION, SITE_NAME, STATIC_DIR
from .routers import router
from .security import add_security_headers


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(title=SITE_NAME, description=SITE_DESCRIPTION, version="1.0.0")

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        response = await call_next(request)
        if SECURITY_HEADERS_ENABLED:
            return add_security_headers(response, request)
        return response

    app.include_router(router)
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()

