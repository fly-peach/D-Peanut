"""Runs control plane: detail + cancel; confirm is a compatibility stub (N3
decision 2: approval continuation rides the second /chat, no confirm endpoint)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..runs.state import RunStatus

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{run_id}")
def get_run(run_id: str, request: Request) -> dict[str, object]:
    row = request.app.state.store.get_run(run_id)
    if row is None:
        raise HTTPException(404, "run not found")
    steps = request.app.state.store.conn.execute(
        "SELECT idx,tool,status,output_digest,retries FROM run_steps WHERE run_id=? ORDER BY idx",
        (run_id,),
    ).fetchall()
    row["steps"] = [dict(s) for s in steps]
    return row


@router.post("/{run_id}/cancel")
def cancel_run(run_id: str, request: Request) -> dict[str, str]:
    store = request.app.state.store
    row = store.get_run(run_id)
    if row is None:
        raise HTTPException(404, "run not found")
    try:  # best-effort interrupt of the session kernel if mid-execution
        request.app.state.session_kernels.interrupt(row["session_id"])
    except Exception:  # noqa: BLE001
        pass
    store.set_run_status(run_id, RunStatus.CANCELLED, error="cancelled by user")
    return {"status": "cancelled"}


@router.post("/{run_id}/confirm")
def confirm_legacy(run_id: str) -> None:
    raise HTTPException(409, "审批续跑请再次 POST /api/sessions/{sid}/chat"
                            "（AI SDK v6 approval 消息）")
