"""ChatRunner: the /chat SSE plane via VercelAIAdapter granular flow (N3).

build_run_input(body) -> adapter(agent, run_input) -> run_stream(deps, model,
usage_limits requests=max_steps, output includes DeferredToolRequests) -> wrap the
chunk stream to drain per-run data-asset-changed events (and a final data-run
summary) BEFORE the finish chunk -> encode_stream -> SSE lines ending [DONE].
"""

from __future__ import annotations

import ast
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from pydantic_ai import DeferredToolRequests, UsageLimits
from pydantic_ai.ui.vercel_ai import VercelAIAdapter
from pydantic_ai.ui.vercel_ai.response_types import DataChunk

from ..agents.data_agent import get_agent
from ..agents.deps import AgentDeps, RunSettings, RunState
from ..agents.model_factory import build_model
from ..agents.model_factory import model_settings as build_model_settings
from ..agents.output import FinalAnswer
from ..settings import SettingsService
from .state import RunStatus
from .store import RunStore

logger = logging.getLogger(__name__)


def settings_to_run_settings(svc: SettingsService) -> RunSettings:
    s = svc.get_view()["settings"]
    return RunSettings(
        provider=str(s.get("llm_provider", "test")),
        base_url=str(s.get("llm_base_url", "") or ""),
        model_name=str(s.get("llm_model", "") or ""),
        temperature=float(s.get("temperature", 0.2)),
        max_tokens=int(s.get("max_tokens", 4096)),
        kernel_timeout_s=float(s.get("kernel_timeout_s", 60.0)),
        max_steps=int(s.get("max_steps", 12)),
        budget_tokens=int(s.get("budget_tokens", 200_000)),
        budget_usd=float(s.get("budget_usd", 2.0)),
        privacy_default=bool(s.get("privacy_mode_default", False)),
        supports_forced_tool_choice=bool(s.get("llm_supports_forced_tool_choice", True)),
        language=str(s.get("language", "zh")),
        timezone=str(s.get("timezone", "Asia/Shanghai")),
    )


def _parse_vars(stdout: str) -> list[str]:
    try:
        v = ast.literal_eval(stdout.strip())
        return [str(x) for x in v] if isinstance(v, list) else []
    except (ValueError, SyntaxError):
        return []


def _drain_assets(state: RunState, run_status: str | None = None) -> list[DataChunk]:
    out = [DataChunk(type="data-asset-changed", data=ev) for ev in state.asset_events]
    state.asset_events.clear()
    if run_status is not None:
        out.append(DataChunk(type="data-run", data={
            "run_id": state.run_id, "status": run_status,
            "reflects_used": state.reflects,
            "tokens": state.usage_tokens, "cost_usd": state.usage_cost,
        }))
    return out


class ChatRunner:
    def __init__(self, settings: SettingsService, store: RunStore, pipeline, repo,
                 canvas_assets, canvas_replay, session_kernels) -> None:
        self.settings = settings
        self.store = store
        self.pipeline = pipeline
        self.repo = repo
        self.canvas_assets = canvas_assets
        self.canvas_replay = canvas_replay
        self.kernels = session_kernels

    def build_deps(self, session_id: str, run) -> tuple[AgentDeps, RunState]:
        rs = settings_to_run_settings(self.settings)
        state = RunState(run_id=run.run_id, session_id=session_id)
        deps = AgentDeps(
            kernel=self.kernels, catalog=self.pipeline, repo=self.repo,
            canvas_assets=self.canvas_assets, canvas_replay=self.canvas_replay,
            store=self.store, settings=rs, state=state,
            ai_enabled=bool(self.settings.get_setting("ai_enabled", True)),
        )
        deps._chat_runner = self  # dynamic-instructions hook for kernel var sniffing
        # NB: adapter.run_stream converts the dataclass deps into a dispatch dict
        # internally; callers must keep their own reference to the RunState object.
        return deps, state

    def kernel_vars(self, session_id: str) -> list[str]:
        try:
            self.kernels.start(session_id=session_id)
        except ValueError:
            pass
        except Exception:  # noqa: BLE001 — sniffing is best-effort
            return []
        res = self.kernels.execute(
            session_id, "[k for k in list(globals()) if not k.startswith('_')]", timeout_s=10
        )
        return _parse_vars(res.stdout) if res.ok else []

    async def stream(self, session_id: str, body: bytes) -> AsyncIterator[str]:
        self.store.ensure_session(session_id)
        run_input = VercelAIAdapter.build_run_input(body)
        adapter = VercelAIAdapter(get_agent(), run_input)
        run = self.store.create_run(session_id, _last_user_text(body))
        deps, state = self.build_deps(session_id, run)
        try:
            model = build_model(deps.settings, self.settings.secrets.get("llm.api_key"))
        except ValueError as e:
            async for line in self._error_stream(adapter, deps, str(e)):
                yield line
            return

        # Restore copies are rebuilt from the emitted chunk stream (works even when
        # the run ends paused on approval, where on_complete never fires).
        collected: list[dict[str, Any]] = []

        def _absorb(chunk: Any) -> None:
            try:
                data = chunk.model_dump(by_alias=True, exclude_none=True)
            except Exception:  # noqa: BLE001
                return
            t = data.get("type")
            if t == "text-delta":
                if collected and collected[-1]["type"] == "text":
                    collected[-1]["text"] += data.get("delta", "")
                else:
                    collected.append({"type": "text", "text": data.get("delta", "")})
            elif t == "reasoning-delta":
                # thinking models (deepseek-flash etc.): keep 思考内容 in restore copies
                if collected and collected[-1]["type"] == "reasoning":
                    collected[-1]["text"] += data.get("delta", "")
                else:
                    collected.append({"type": "reasoning", "text": data.get("delta", "")})
            elif t == "tool-input-available":
                collected.append({"type": f"tool-{data.get('toolName', '?')}",
                                  "toolCallId": data.get("toolCallId"),
                                  "state": "input-available", "input": data.get("input")})
            elif t == "tool-output-available":
                call_id = data.get("toolCallId")
                for p in reversed(collected):
                    if p.get("toolCallId") == call_id:
                        p["output"] = data.get("output")
                        p["state"] = "output-available"
                        break
            elif t == "tool-output-error":
                call_id = data.get("toolCallId")
                for p in reversed(collected):
                    if p.get("toolCallId") == call_id:
                        p["errorText"] = data.get("errorText")
                        p["state"] = "output-error"
                        break
            elif t in ("data-asset-changed", "data-run"):
                collected.append({"type": t, "data": data.get("data")})

        def _persist() -> None:
            msgs: list[dict[str, Any]] = [
                {"role": "user", "parts": [{"type": "text", "text": run.message}]},
                {"role": "assistant", "parts": collected},
            ]
            self.store.replace_messages(session_id, run.run_id, msgs)

        msettings = build_model_settings(deps.settings)
        raw = adapter.run_stream(
            deps=deps,
            model=model,
            model_settings=msettings,
            output_type=[FinalAnswer, DeferredToolRequests],
            usage_limits=UsageLimits(
                request_limit=deps.settings.max_steps,
                total_tokens_limit=deps.settings.budget_tokens,
                cost_limit=__import__("decimal").Decimal(deps.settings.budget_usd),
            ),
        )

        status = "done"

        async def wrapped() -> AsyncIterator[Any]:
            nonlocal status
            try:
                async for chunk in raw:
                    _absorb(chunk)
                    if getattr(chunk, "type", "") == "finish":
                        # the run summary must precede finish/[DONE] on the wire
                        for note in _drain_assets(state, status):
                            yield note
                    else:
                        for note in _drain_assets(state):
                            yield note
                    yield chunk
            except Exception as e:  # noqa: BLE001 — stream must end in-band, not as a 500
                logger.exception("chat run %s failed mid-stream", run.run_id)
                status = "failed"
                for note in _drain_assets(state, "failed"):
                    yield note
                yield DataChunk(type="data-run", data={
                    "run_id": run.run_id, "status": "failed",
                    "error": f"{type(e).__name__}: {str(e)[:300]}",
                })
            finally:
                try:
                    _persist()
                except Exception:  # noqa: BLE001 — restore copies must never break a run
                    pass
                self.store.finish_run(run.run_id,
                                      RunStatus.DONE if status == "done" else RunStatus.FAILED,
                                      {"tokens": state.usage_tokens}, state.usage_cost)

        self.store.set_run_status(run.run_id, RunStatus.EXECUTING)
        async for line in adapter.encode_stream(wrapped()):
            yield line

    async def _error_stream(self, adapter, deps, msg: str):
        bad_run = deps.state.run_id

        async def one() -> AsyncIterator[Any]:
            yield DataChunk(type="data-run", data={"run_id": bad_run, "status": "failed",
                                                   "error": msg})
        async for line in adapter.encode_stream(one()):
            yield line
        self.store.finish_run(bad_run, RunStatus.FAILED, {}, 0.0, error=msg[:300])


def _last_user_text(body: bytes) -> str:
    try:
        data = json.loads(body)
        for m in reversed(data.get("messages", [])):
            if m.get("role") == "user":
                return " ".join(p.get("text", "") for p in m.get("parts", [])
                                if p.get("type") == "text")[:500]
    except (ValueError, AttributeError):
        pass
    return ""
