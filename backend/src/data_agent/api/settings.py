"""GET|PUT /api/settings — runtime config merged view (secrets masked).

N3 adds the LLM plane: llm_provider/llm_base_url/llm_model/temperature/... live in
the settings table; api key in secrets (masked); POST /llm/test pings the model."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsPatch(BaseModel):
    settings: dict[str, Any] | None = None  # non-sensitive → settings table
    secrets: dict[str, str] | None = None  # sensitive → secrets.json; "" clears a key


@router.get("")
def read_settings(request: Request) -> dict[str, Any]:
    return request.app.state.settings.get_view()


@router.put("")
def write_settings(patch: SettingsPatch, request: Request) -> dict[str, Any]:
    return request.app.state.settings.update(
        settings=patch.settings,
        secrets={k: v for k, v in (patch.secrets or {}).items()},
    )


@router.post("/llm/test")
async def test_llm(request: Request) -> dict[str, Any]:
    """One minimal real request with SAVED settings (frontend saves before testing)."""
    from ..agents.model_factory import ping_model
    from ..runs.stream import settings_to_run_settings

    svc = request.app.state.settings
    rs = settings_to_run_settings(svc)
    return await ping_model(rs, svc.secrets.get("llm.api_key"))
