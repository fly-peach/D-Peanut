"""Agent assembly — n5: official pydantic-ai-harness configuration (agent-design v3 §1).

The harness is now the OFFICIAL pydantic_ai_harness capability stack; our data
product (catalog/canvas/kernel) rides on top as registered tools ("外派"给
coding harness)。Coder-as-a-bundle is deliberately written out block by block —
the docs themselves bless this as the same agent ("written out block by
block") — so the trust contract survives:

- FileSystem: READ-ONLY over DATA_ROOT. Processor writes must go through
  write_processor (三导出契约 + schema gate), never raw files.
- Shell: orientation only — no interpreters (python would bypass the AST
  verifier) and no content readers (cat/head/grep would read workspace
  secrets); content access stays with query_data/inspect_profile.
- ClearToolResults omitted: ProcessHistory (frozen N4 semantics, asset-ID
  survival) owns folding; two compaction layers would fight.
- SubAgents omitted: harness binds the child model at build time, breaking the
  "model is never baked in / per-run override" invariant (model_factory).

The model is NOT baked in: ChatRunner supplies it per run via
agent.override(model=model_factory.build_model(...)).

output_type includes DeferredToolRequests so approval runs end cleanly with the
adapter emitting approval frames (AI SDK v6 semantics, verified on 2.43)."""

from __future__ import annotations

import os
from typing import Any

from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai_harness import (
    LLM_API_KEY_ENV_PATTERNS,
    FileSystem,
    Planning,
    Shell,
    ToolOutputLimits,
    WarnNearLimits,
)

from .deps import AgentDeps
from .output import FinalAnswer
from .prompts import STATIC_INSTRUCTIONS
from .tools import register_all

_DATA_ROOT = os.environ.get("DATA_ROOT", "./data")

# 官方 Shell 的命令白名单：只保留"看结构"的只读工具，杜绝 verifier 绕过面。
_ORIENTATION_COMMANDS = ["ls", "du", "wc", "find"]


def _harness_capabilities() -> list[Any]:
    return [
        FileSystem(_DATA_ROOT, read_only=True),
        Shell(
            cwd=_DATA_ROOT,
            allowed_commands=_ORIENTATION_COMMANDS,
            denied_env_patterns=LLM_API_KEY_ENV_PATTERNS,
        ),
        Planning(),
        WarnNearLimits(max_total_tokens=200_000, max_iterations=12),
        ToolOutputLimits(),
    ]


def build_agent() -> Agent[AgentDeps, Any]:
    from ..memory.compaction import make_capability

    agent = Agent(
        "test",  # placeholder model; ChatRunner overrides per run
        deps_type=AgentDeps,
        output_type=[FinalAnswer, DeferredToolRequests],
        instructions=STATIC_INSTRUCTIONS,
        retries=2,
        end_strategy="graceful",
        capabilities=[*_harness_capabilities(), make_capability()],
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
