"""GET|PUT /api/settings — runtime config merged view (secrets masked).

N1 skeleton: budgets/privacy defaults now; LLM form + POST /settings/llm/test land
with N3 model_factory (N1/N2 are zero-AI paths, users must not be forced to set keys).
"""

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
