"""Minimal per-session kernel pool: one ipykernel subprocess per session.

M0 Spike B scope: start / execute / capture / interrupt / DataFrame persistence
across execute() calls. Production concerns (restart, limits, container isolation)
land in M1+/v1. Note: both stdout and stderr streams are captured into
ExecResult.stdout; error is reserved for cell errors and interrupts.
"""

from __future__ import annotations

import re
import sys
import time
import uuid

from jupyter_client.client import KernelClient
from jupyter_client.kernelspec import KernelSpec, KernelSpecManager
from jupyter_client.manager import KernelManager

_IPYKERNEL_LAUNCHER = ["-m", "ipykernel_launcher", "-f", "{connection_file}"]


class _CurrentEnvSpecManager(KernelSpecManager):
    """Resolve python3 to the interpreter running this process (the backend venv).

    Machine-wide kernelspecs are fragile (PATH-dependent argv, wrong interpreter,
    missing deps); the design requires kernel = backend venv so pandas/duckdb are
    importable. This manager removes that environmental variance.
    """

    def get_kernel_spec(self, name: str) -> KernelSpec:
        if name in ("python", "python3"):
            return KernelSpec(
                argv=[sys.executable, *_IPYKERNEL_LAUNCHER],
                display_name="Python 3 (data-agent)",
                language="python",
            )
        return super().get_kernel_spec(name)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class ExecResult:
    __slots__ = ("ok", "stdout", "error", "elapsed_s")

    def __init__(self, ok: bool, stdout: str = "", error: str = "", elapsed_s: float = 0.0) -> None:
        self.ok = ok
        self.stdout = stdout
        self.error = error
        self.elapsed_s = elapsed_s

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"ExecResult(ok={self.ok}, stdout={self.stdout[:60]!r}, error={self.error[:60]!r})"


class KernelPool:
    """Owns one kernel subprocess per session id."""

    def __init__(self) -> None:
        self._kernels: dict[str, KernelManager] = {}
        self._clients: dict[str, KernelClient] = {}

    def start(self, session_id: str | None = None, ready_timeout_s: float = 60.0) -> str:
        sid = session_id or uuid.uuid4().hex
        if sid in self._kernels:
            raise ValueError(f"kernel already running for session {sid}")
        km = KernelManager(kernel_name="python3", kernel_spec_manager=_CurrentEnvSpecManager())
        km.start_kernel()
        kc = km.client()
        kc.start_channels()
        try:
            kc.wait_for_ready(timeout=ready_timeout_s)
        except Exception:
            kc.stop_channels()
            km.shutdown_kernel(now=True)
            raise
        self._kernels[sid] = km
        self._clients[sid] = kc
        return sid

    def _km(self, session_id: str) -> KernelManager:
        try:
            return self._kernels[session_id]
        except KeyError as exc:
            raise KeyError(f"no kernel for session {session_id}") from exc

    def _kc(self, session_id: str) -> KernelClient:
        try:
            return self._clients[session_id]
        except KeyError as exc:
            raise KeyError(f"no kernel client for session {session_id}") from exc

    def execute(self, session_id: str, code: str, timeout_s: float = 60.0) -> ExecResult:
        kc = self._kc(session_id)
        msg_id = kc.execute(code)
        start = time.monotonic()
        out: list[str] = []
        errors: list[str] = []
        interrupted = False
        deadline = start + timeout_s

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 and not interrupted:
                self.interrupt(session_id)
                interrupted = True
                deadline = time.monotonic() + 10.0  # grace period for KeyboardInterrupt
                errors.append(f"TimeoutError: execution exceeded {timeout_s:.0f}s, interrupted")
                continue
            if remaining <= 0:
                errors.append("KernelError: kernel unresponsive after interrupt")
                return ExecResult(False, "".join(out), "\n".join(errors), time.monotonic() - start)
            try:
                msg = kc.get_iopub_msg(timeout=min(remaining, 2.0))
            except Exception:  # queue.Empty while waiting on iopub
                continue
            if msg.get("parent_header", {}).get("msg_id") != msg_id:
                continue
            msg_type, content = msg["msg_type"], msg["content"]
            if msg_type == "stream":
                out.append(content.get("text", ""))
            elif msg_type == "error":
                ename = content.get("ename", "Error")
                evalue = content.get("evalue", "")
                tb = _strip_ansi("\n".join(content.get("traceback", [])))
                errors.append(f"{ename}: {evalue}\n{tb}".strip())
            elif msg_type == "status" and content.get("execution_state") == "idle":
                break

        return ExecResult(not errors, "".join(out), "\n".join(errors), time.monotonic() - start)

    def interrupt(self, session_id: str) -> None:
        self._km(session_id).interrupt_kernel()

    def shutdown(self, session_id: str) -> None:
        kc = self._clients.pop(session_id, None)
        if kc is not None:
            try:
                kc.stop_channels()
            except Exception:  # best-effort teardown
                pass
        km = self._kernels.pop(session_id, None)
        if km is not None:
            try:
                # now=True: SIGKILL the kernel process. Graceful shutdown can leave
                # busy kernels lingering and holding pipes; kernel state is disposable
                # at session teardown.
                km.shutdown_kernel(now=True)
            except Exception:  # best-effort teardown
                pass

    def shutdown_all(self) -> None:
        for sid in list(self._kernels):
            self.shutdown(sid)
