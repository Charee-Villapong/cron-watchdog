"""Cumulative state store (design.md section 5.4).

Observed ``last_success_at`` values are merged monotonically: cron run
history may be truncated (``history_may_be_truncated``), so a success
once observed by the watchdog must never be lost or moved backwards.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class StoredJob:
    last_success_at: datetime | None = None
    consecutive_failures: int = 0


@dataclass
class StateStore:
    jobs: dict[str, StoredJob] = field(default_factory=dict)


def load_state(path: str | Path) -> StateStore:
    target = Path(path)
    if not target.exists():
        return StateStore()
    data = json.loads(target.read_text(encoding="utf-8"))
    jobs = {}
    for name, raw in data.get("jobs", {}).items():
        last = raw.get("last_success_at")
        jobs[name] = StoredJob(
            last_success_at=datetime.fromisoformat(last) if last else None,
            consecutive_failures=int(raw.get("consecutive_failures", 0)),
        )
    return StateStore(jobs=jobs)


def save_state(path: str | Path, store: StateStore) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "jobs": {
            name: {
                "last_success_at": (
                    job.last_success_at.isoformat() if job.last_success_at else None
                ),
                "consecutive_failures": job.consecutive_failures,
            }
            for name, job in sorted(store.jobs.items())
        }
    }
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def merge_observations(store: StateStore, states) -> StateStore:
    """Merge freshly observed JobStates; last_success only moves forward."""
    for state in states:
        current = store.jobs.get(state.definition.name, StoredJob())
        last = current.last_success_at
        if state.last_success_at is not None and (
            last is None or state.last_success_at > last
        ):
            last = state.last_success_at
        store.jobs[state.definition.name] = StoredJob(
            last_success_at=last,
            consecutive_failures=state.consecutive_failures,
        )
    return store


def apply_store(store: StateStore, states) -> list:
    """Fill each JobState's last_success_at with the stored (newer) value."""
    from dataclasses import replace

    merged = []
    for state in states:
        stored = store.jobs.get(state.definition.name)
        if (
            stored
            and stored.last_success_at is not None
            and (
                state.last_success_at is None
                or stored.last_success_at > state.last_success_at
            )
        ):
            state = replace(state, last_success_at=stored.last_success_at)
        merged.append(state)
    return merged
