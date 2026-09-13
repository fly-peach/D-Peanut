"""Structured logging with unified secret redaction (N4)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .secrets_store import SecretsStore

_FMT = "%(asctime)s %(levelname)s %(name)s - %(message)s"


class _RedactFilter(logging.Filter):
    def __init__(self, store: SecretsStore) -> None:
        super().__init__()
        self._store = store

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = self._store.redact(str(record.msg))
            record.args = ()
        except Exception:  # noqa: BLE001 — logging must never raise
            pass
        return True


def setup_logging(store: SecretsStore, level: int = logging.INFO) -> None:
    root = logging.getLogger()
    # per-store idempotency: several stores may be active (tests, multi-workspace)
    if any(isinstance(f, _RedactFilter) and f._store is store for f in root.filters):  # noqa: SLF001
        return
    logging.basicConfig(format=_FMT, level=level)
    root.addFilter(_RedactFilter(store))
