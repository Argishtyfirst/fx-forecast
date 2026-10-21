"""FastAPI app: the read-only API under /api, plus the built frontend when present.

    uv run uvicorn fxf.api.main:app --port 8000

When <repo>/frontend/dist exists, it is served at / with a fallback to index.html for
client-side routes, so one service hosts both API and UI. /api routes always win.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import OperationalError

from fxf import __version__
from fxf.api.routes import router
from fxf.config import BACKEND_DIR, REPO_DIR
from fxf.logging_setup import get_logger

log = get_logger(__name__)


def _frontend_dist() -> Path:
    """backend/public on Vercel (written by scripts/vercel_build.sh), else frontend/dist."""
    for candidate in (BACKEND_DIR / "public", REPO_DIR / "frontend" / "dist"):
        if (candidate / "index.html").is_file():
            return candidate
    return REPO_DIR / "frontend" / "dist"


FRONTEND_DIST = _frontend_dist()
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
IMMUTABLE = "public, max-age=31536000, immutable"


async def _db_unavailable(request: Request, exc: Exception) -> JSONResponse:
    log.error("database unavailable", extra={"path": request.url.path, "error": str(exc)})
    return JSONResponse(status_code=503, content={"detail": "database unavailable"})


def _mount_spa(app: FastAPI, dist: Path) -> None:
    root = dist.resolve()
    index = root / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        if full_path:
            candidate = (root / full_path).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                hashed = candidate.parent == root / "assets"
                return FileResponse(
                    candidate, headers={"Cache-Control": IMMUTABLE} if hashed else None
                )
            if "." in Path(full_path).name:
                # A missing file, not a client-side route: never answer a .js request with HTML.
                raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app(frontend_dist: Path | None = FRONTEND_DIST) -> FastAPI:
    app = FastAPI(
        title="FX Forecast Tool API",
        version=__version__,
        description="Read-only API for EUR/USD and USD/AMD forecast bands. "
        "Statistical estimate. Not financial advice.",
        docs_url="/api/docs",
        swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.add_exception_handler(OperationalError, _db_unavailable)
    app.include_router(router)
    if frontend_dist is not None and (frontend_dist / "index.html").is_file():
        _mount_spa(app, frontend_dist)
    return app


app = create_app()
