"""Sessions REST (v0). M0 scaffold stub; full control plane lands in M2."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/sessions")
def list_sessions() -> list[dict]:
    return []
