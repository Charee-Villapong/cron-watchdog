"""Status judgement (test-contract module ``watchdog.status``).

Rule (per the test contract, which takes precedence over the
schedule-based judgement sketched in docs/design.md):

    now <= last_success_at + period + tolerance  ->  SUCCESS
    otherwise                                    ->  FAILURE

The exact deadline instant counts as SUCCESS. RUNNING and UNKNOWN are
never mixed into FAILURE.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from watchdog.definitions import Definition, DefinitionError


class Status(str, Enum):
    NOT_RUN = "未実行"
    RUNNING = "実行中"
    SUCCESS = "成功"
    FAILURE = "失敗"
    UNKNOWN = "判定不能"


def evaluate_status(
    definition: Definition,
    last_success_at: datetime | None,
    now: datetime,
    *,
    running: bool = False,
    evidence_available: bool = True,
) -> Status:
    if not evidence_available:
        return Status.UNKNOWN
    if running:
        return Status.RUNNING
    if last_success_at is None:
        return Status.NOT_RUN
    try:
        period = definition.period_timedelta
    except DefinitionError:
        return Status.UNKNOWN
    deadline = (
        last_success_at + period + timedelta(seconds=definition.tolerance_seconds)
    )
    if now <= deadline:
        return Status.SUCCESS
    return Status.FAILURE
