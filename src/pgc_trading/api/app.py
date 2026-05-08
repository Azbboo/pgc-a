"""FastAPI application factory for the PGC HTTP API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pgc_trading.api.routes import register_routes
from pgc_trading.api.services import ApiServices
from pgc_trading.api.settings import ApiSettings


class ApiDependencyError(RuntimeError):
    """Raised when optional API dependencies are not installed."""


def create_app(settings: ApiSettings | None = None, services: ApiServices | None = None) -> Any:
    """Create the FastAPI app used by HTTP entrypoints."""

    FastAPI = _load_fastapi()
    resolved_settings = settings or ApiSettings.from_env()

    app = FastAPI(
        title="PGC Trading API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = resolved_settings
    app.state.services = services or ApiServices()
    register_routes(app)
    _mount_dashboard(app)
    return app


def _load_fastapi() -> Any:
    try:
        from fastapi import FastAPI
    except ModuleNotFoundError as exc:
        if exc.name == "fastapi":
            raise ApiDependencyError(
                "FastAPI is required to create the HTTP API app. "
                "Install it with: python3 -m pip install -e '.[api]'"
            ) from exc
        raise
    return FastAPI


def _mount_dashboard(app: Any) -> None:
    dashboard_dir = Path(__file__).resolve().parents[3] / "web" / "dashboard"
    index_path = dashboard_dir / "index.html"
    if not index_path.exists():
        return

    from fastapi.responses import FileResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles

    @app.get("/dashboard", include_in_schema=False)
    def dashboard_index_redirect() -> Any:
        return RedirectResponse(url="/dashboard/", status_code=307)

    @app.get("/dashboard/", include_in_schema=False)
    def dashboard_index() -> Any:
        return FileResponse(index_path)

    app.mount(
        "/dashboard/assets",
        StaticFiles(directory=dashboard_dir),
        name="pgc_dashboard_assets",
    )
