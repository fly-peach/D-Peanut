"""Agent assembly (agent-design v3 §1). The model is NOT baked in: ChatRunner
supplies it per run via agent.override(model=model_factory.build_model(...)).

output_type includes DeferredToolRequests so approval runs end cleanly with the
adapter emitting approval frames (AI SDK v6 semantics, verified on 2.43)."""

from __future__ import annotations

from typing import Any

from pydantic_ai import Agent, DeferredToolRequests

from .deps import AgentDeps
from .output import FinalAnswer
from .prompts import STATIC_INSTRUCTIONS
from .tools import register_all


def build_agent() -> Agent[AgentDeps, Any]:
    agent = Agent(
        "test",  # placeholder model; ChatRunner overrides per run
        deps_type=AgentDeps,
        output_type=[FinalAnswer, DeferredToolRequests],
        instructions=STATIC_INSTRUCTIONS,
        retries=2,
        end_strategy="graceful",
    )

    @agent.instructions
    def _dynamic(ctx: Any) -> str:
        # ctx.deps is AgentDeps; kernel sniffing is best-effort (never fails a run)
        try:
            from .prompts import render_dynamic_prompt

            runner = getattr(ctx.deps, "_chat_runner", None)
            kernel_vars: list[str] = []
            if runner is not None:
                kernel_vars = runner.kernel_vars(ctx.deps.state.session_id)
            return render_dynamic_prompt(ctx.deps, kernel_vars)
        except Exception:  # noqa: BLE001 — dynamic context must never break the run
            return ""

    register_all(agent)
    return agent


_agent: Agent[AgentDeps, Any] | None = None


def get_agent() -> Agent[AgentDeps, Any]:
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent
