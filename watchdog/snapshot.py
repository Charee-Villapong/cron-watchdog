"""Snapshot ingestion (additional module; not part of the test contract).

The collector (an agent-run watchdog cron) writes a JSON snapshot of
``cron.status`` / ``cron.runs`` results in the schema of design.md
section 10.4. This module turns it into :class:`JobState` objects.

Privacy rule: ``result_summary`` is *never* read, copied or stored —
it can contain personal message bodies. Only status metadata and
timestamps are used; ``error_text`` is exposed solely through
:func:`watchdog.masking.sanitize_error` (masked).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from watchdog.definitions import Definition
from watchdog.ledger import JobState


class SnapshotError(ValueError):
    """Raised when a snapshot file is structurally invalid."""


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SnapshotError(f"expected ISO datetime string, got {value!r}")
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise SnapshotError(f"invalid ISO datetime: {value!r}") from exc


def load_snapshot(path: str | Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"cannot read snapshot: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("targets"), dict):
        raise SnapshotError("snapshot must be an object with a 'targets' object")
    return data


def _last_success_from_runs(runs: list) -> datetime | None:
    """Latest finished_at among succeeded runs, or None if there is none."""
    last_success: datetime | None = None
    for run in runs:
        if run.get("status") == "succeeded":
            candidate = _parse_dt(run.get("finished_at"))
            if candidate is not None and (
                last_success is None or candidate > last_success
            ):
                last_success = candidate
    return last_success


def _consecutive_failures(status: dict) -> int:
    consecutive = status.get("consecutive_failures")
    if not isinstance(consecutive, int) or isinstance(consecutive, bool):
        consecutive = 0
    return consecutive


def _is_running(status: dict, runs: list) -> bool:
    return bool(status.get("in_flight")) or any(
        run.get("finished_at") is None and run.get("started_at") is not None
        for run in runs
    )


def _build_available_state(definition: Definition, entry: dict) -> JobState:
    """Build the JobState for a target whose evidence is available."""
    status = entry.get("status") or {}
    runs = entry.get("runs") or []
    last_success = _parse_dt(status.get("last_success_at"))
    if last_success is None:
        last_success = _last_success_from_runs(runs)
    return JobState(
        definition=definition,
        last_success_at=last_success,
        consecutive_failures=_consecutive_failures(status),
        running=_is_running(status, runs),
        evidence_available=True,
    )


def build_job_states(
    definitions: list[Definition],
    snapshot: dict,
) -> list[JobState]:
    """Build one JobState per definition from snapshot metadata only."""
    targets = snapshot.get("targets", {})
    collect_errors = snapshot.get("collect_errors", {})
    states: list[JobState] = []
    for definition in definitions:
        entry = targets.get(definition.name)
        if entry is None or definition.name in collect_errors:
            states.append(JobState(definition=definition, evidence_available=False))
            continue
        states.append(_build_available_state(definition, entry))
    return states


def sanitized_snapshot_errors(snapshot: dict) -> dict[str, str]:
    """Masked error excerpts per target (error_text only, never summaries)."""
    from watchdog.masking import EXCERPT_MAX_LENGTH, mask_sensitive

    out: dict[str, str] = {}
    for name, entry in snapshot.get("targets", {}).items():
        for run in entry.get("runs") or []:
            error_text = run.get("error_text")
            if error_text:
                out[name] = mask_sensitive(
                    str(error_text), max_length=EXCERPT_MAX_LENGTH
                )
                break
    return out
