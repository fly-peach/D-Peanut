"""FastAPI assembly: routes, CORS, optional static hosting (docker/prod)."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .api.sessions import router as sessions_router

app = FastAPI(title="data-agent", version="0.0.1")
app.include_router(sessions_router, prefix="/api")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "version": "0.0.1"}


# In docker the built frontend is copied to /app/static (see backend/Dockerfile).
_static_dir = Path(os.environ.get("DATA_AGENT_STATIC_DIR", ""))
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
