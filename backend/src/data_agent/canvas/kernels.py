"""Clean-kernel warm pool for replays (N2 day-1 probe: 0.71s cold / 5ms warm /
`%reset -f` leaves no residue — see canvas-assets/design.md).

Exactly `size` kernels live; acquire() blocks until one is free. A kernel that
fails reset / dies is discarded and replaced lazily on the next acquire.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque

from ..exec.kernel_pool import KernelPool

POOL_SIZE_ENV = "REPLAY_POOL_SIZE"
RESET_CODE = "%reset -f"
RESET_TIMEOUT_S = 10.0


class ReplayKernelPool:
    def __init__(self, size: int | None = None, inner: KernelPool | None = None) -> None:
        self.size = size or int(os.environ.get(POOL_SIZE_ENV, "2"))
        self.inner = inner or KernelPool()
        self._idle: deque[str] = deque()
        self._cv = threading.Condition()
        self._spawned = 0
        self._closed = False

    def _new_sid(self) -> str:
        self._spawned += 1
        return f"replay:{self._spawned}"

    def warmup(self) -> None:
        for _ in range(self.size):
            sid = None
            with self._cv:
                sid = self._new_sid()
            self.inner.start(session_id=sid)
            with self._cv:
                self._idle.append(sid)

    def acquire(self, timeout_s: float = 60.0) -> str:
        with self._cv:
            deadline = time.monotonic() + timeout_s
            while True:
                if self._closed:
                    raise RuntimeError("pool closed")
                if self._idle:
                    return self._idle.popleft()
                if self._spawned < self.size:
                    sid = self._new_sid()
                    break  # start outside? lock is reentrant-ish; start under cv so
                    # racing acquirers don't over-spawn
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("no replay kernel available")
                self._cv.wait(remaining)
            # spawn path (holding the condition lock serializes starts):
            self.inner.start(session_id=sid)
            return sid

    def release(self, session_id: str, *, discard: bool = False) -> None:
        with self._cv:
            if discard or self._closed:
                self.inner.shutdown(session_id)
                self._spawned -= 1
            else:
                self._idle.append(session_id)
            self._cv.notify()

    def reset(self, session_id: str) -> bool:
        res = self.inner.execute(session_id, RESET_CODE, timeout_s=RESET_TIMEOUT_S)
        return res.ok

    def shutdown_all(self) -> None:
        with self._cv:
            self._closed = True
            for sid in list(self._idle):
                self.inner.shutdown(sid)
            self._idle.clear()
            self._spawned = 0
        self.inner.shutdown_all()
