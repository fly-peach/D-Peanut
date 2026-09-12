"""Run state machine (design-architecture §2.2). Transitions enforced from M2."""

from enum import StrEnum


class RunStatus(StrEnum):
    PLANNED = "planned"
    EXECUTING = "executing"
    WAITING_CONFIRM = "waiting_confirm"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
