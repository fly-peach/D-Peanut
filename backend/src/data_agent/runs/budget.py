"""Run budget circuit breaker (agent-design §4): token/cost thresholds enforced
after every model request — the model does not decide its own spend cap."""

from __future__ import annotations

from typing import Any


class BudgetExceeded(RuntimeError):
    def __init__(self, kind: str, used: float, limit: float) -> None:
        super().__init__(f"{kind} budget exceeded: {used:g} > {limit:g}")
        self.kind = kind
        self.used = used
        self.limit = limit


def check_budget(usage: Any, *, max_tokens: int, max_usd: float) -> None:
    """usage: pydantic_ai Usage object or duck-typed holder."""
    tokens = int(getattr(usage, "total_tokens", 0) or 0)
    cost = float(getattr(usage, "cost_usd", None) or 0.0)
    if tokens > max_tokens:
        raise BudgetExceeded("tokens", tokens, max_tokens)
    if cost > max_usd:
        raise BudgetExceeded("usd", cost, max_usd)
