"""KernelRunner protocol - the stable engine-layer seam (interface frozen at end of M1).

kernel_pool is today's implementation; container sandbox (v1) replaces the
implementation without touching this signature.
"""

from typing import Protocol, runtime_checkable

from .kernel_pool import ExecResult


@runtime_checkable
class KernelRunner(Protocol):
    def execute(self, session_id: str, code: str, *, timeout_s: float = 60.0) -> ExecResult: ...

    def interrupt(self, session_id: str) -> None: ...
