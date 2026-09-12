"""Run store. M0: in-memory; M2 swaps SQLite behind the same interface."""

from dataclasses import dataclass, field

from .state import RunStatus


@dataclass
class Run:
    run_id: str
    session_id: str
    status: RunStatus = RunStatus.PLANNED
    steps: list[dict] = field(default_factory=list)
    tokens: int = 0
    cost: float = 0.0


class RunStore:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def create(self, run_id: str, session_id: str) -> Run:
        run = Run(run_id=run_id, session_id=session_id)
        self._runs[run_id] = run
        return run

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)
