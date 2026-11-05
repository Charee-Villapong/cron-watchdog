"""Ledger rows, next-due computation and overdue detection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from watchdog.definitions import Definition
from watchdog.status import Status, evaluate_status


@dataclass(frozen=True)
class RunRecord:
    finished_at: datetime
    succeeded: bool


@dataclass(frozen=True)
class JobState:
    definition: Definition
    last_success_at: datetime | None = None
    consecutive_failures: int = 0
    running: bool = False
    evidence_available: bool = True


@dataclass(frozen=True)
class LedgerRow:
    name: str
    period: str
    last_success_at: datetime | None
    consecutive_failures: int
    next_due_at: datetime | None
    status: Status


def compute_next_due(
    definition: Definition,
    last_success_at: datetime | None,
) -> datetime | None:
    if last_success_at is None:
        return None
    return last_success_at + definition.period_timedelta


def count_consecutive_failures(runs: Iterable[RunRecord]) -> int:
    count = 0
    for run in reversed(list(runs)):
        if run.succeeded:
            break
        count += 1
    return count


def build_ledger_row(state: JobState, now: datetime) -> LedgerRow:
    status = evaluate_status(
        state.definition,
        state.last_success_at,
        now,
        running=state.running,
        evidence_available=state.evidence_available,
    )
    return LedgerRow(
        name=state.definition.name,
        period=state.definition.period,
        last_success_at=state.last_success_at,
        consecutive_failures=state.consecutive_failures,
        next_due_at=compute_next_due(state.definition, state.last_success_at),
        status=status,
    )


def detect_overdue(states: Iterable[JobState], now: datetime) -> list[LedgerRow]:
    rows = [build_ledger_row(state, now) for state in states]
    return [row for row in rows if row.status == Status.FAILURE]
