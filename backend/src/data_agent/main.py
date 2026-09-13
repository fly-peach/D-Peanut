"""FastAPI assembly: routes, CORS, optional static hosting (docker/prod)."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api.datasets import router as datasets_router
from .api.sessions import router as sessions_router
from .api.settings import router as settings_router
from .catalog.pipeline import CatalogPipeline
from .catalog.registry import CatalogRepository
from .settings import SettingsService, Workspace


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    workspace = Workspace.from_env()
    workspace.ensure_runtime()
    settings = SettingsService(workspace)
    app.state.workspace = workspace
    app.state.settings = settings
    app.state.catalog = CatalogPipeline(CatalogRepository(workspace.index_db), settings, workspace)
    yield


app = FastAPI(title="data-agent", version="0.0.1", lifespan=lifespan)
app.include_router(sessions_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(datasets_router, prefix="/api")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": "0.0.1"}


# In docker the built frontend is copied to /app/static (see backend/Dockerfile).
_static_dir = Path(os.environ.get("DATA_AGENT_STATIC_DIR", ""))
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
