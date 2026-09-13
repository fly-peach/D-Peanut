"""Sessions control plane + the /chat UIMessage stream entry.

Approval continuation = a second /chat carrying the full message list (AI SDK v6
approval parts; adapter converts via deferred_tool_results). AI toggle off -> 409.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/sessions", tags=["sessions"])


class SessionCreate(BaseModel):
    title: str = ""


@router.post("", status_code=201)
def create_session(body: SessionCreate, request: Request) -> dict[str, str]:
    sid = request.app.state.store.create_session(body.title)
    return {"id": sid}


@router.get("")
def list_sessions(request: Request, limit: int = 50) -> list[dict]:
    return request.app.state.store.list_sessions(limit)


@router.delete("/{sid}", status_code=204)
def delete_session(sid: str, request: Request) -> None:
    request.app.state.store.delete_session(sid)


@router.post("/{sid}/chat")
async def chat(sid: str, request: Request) -> StreamingResponse:
    deps = request.app.state
    if not bool(deps.settings.get_setting("ai_enabled", True)):
        raise HTTPException(409, "AI toggle 已关闭：/chat 不可用（画布/表单/重放不受影响）")
    body = await request.body()
    runner = deps.chat_runner
    return StreamingResponse(
        runner.stream(sid, body),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
