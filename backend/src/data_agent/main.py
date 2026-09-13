"""FastAPI assembly: routes, CORS, optional static hosting (docker/prod)."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api.assets import router as assets_router
from .api.datasets import router as datasets_router
from .api.sessions import router as sessions_router
from .api.settings import router as settings_router
from .canvas.assets import AssetService
from .canvas.kernels import ReplayKernelPool
from .canvas.replay import ReplayService
from .catalog.pipeline import CatalogPipeline
from .catalog.registry import CatalogRepository
from .settings import SettingsService, Workspace


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    workspace = Workspace.from_env()
    workspace.ensure_runtime()
    settings = SettingsService(workspace)
    repo = CatalogRepository(workspace.index_db)
    app.state.workspace = workspace
    app.state.settings = settings
    app.state.catalog = CatalogPipeline(repo, settings, workspace)
    app.state.replay_pool = ReplayKernelPool()
    app.state.canvas = SimpleNamespace(
        assets=AssetService(workspace.assets_dir, workspace.index_db),
        repo=repo,
        replay=None,  # filled below (needs the assets service it does not own)
    )
    app.state.canvas.replay = ReplayService(
        app.state.canvas.assets, repo, settings.secrets, app.state.replay_pool
    )
    try:
        yield
    finally:
        app.state.replay_pool.shutdown_all()


app = FastAPI(title="data-agent", version="0.0.1", lifespan=lifespan)
app.include_router(sessions_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(datasets_router, prefix="/api")
app.include_router(assets_router, prefix="/api")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": "0.0.1"}


# In docker the built frontend is copied to /app/static (see backend/Dockerfile).
_static_dir = Path(os.environ.get("DATA_AGENT_STATIC_DIR", ""))
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
