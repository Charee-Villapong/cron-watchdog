"""Watchdog self heartbeat (kept separate from the ledger).

Two stores, per docs/design.md section 6:

- a plain last-run file written/read by :func:`record_heartbeat` and
  :func:`read_heartbeat` (the test-contract interface);
- an append-only JSONL log (:func:`append_heartbeat_record`) used by
  the CLI so a missing run is itself visible as a gap.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def record_heartbeat(path: str | Path, now: datetime) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(now.isoformat() + "\n", encoding="utf-8")


def read_heartbeat(path: str | Path) -> datetime | None:
    target = Path(path)
    if not target.exists():
        return None
    text = target.read_text(encoding="utf-8").strip()
    if not text:
        return None
    return datetime.fromisoformat(text)


def append_heartbeat_record(path: str | Path, record: dict) -> None:
    """Append one JSONL heartbeat record (design.md section 6 format)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
