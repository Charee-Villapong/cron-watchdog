"""Notification payload construction (generation only, never sends).

Shadow mode is the default operating mode: detections are recorded in
the payload but ``should_notify`` stays False with an explicit
``"shadow"`` suppression reason.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from watchdog.ledger import LedgerRow
from watchdog.status import Status


@dataclass(frozen=True)
class NotificationPayload:
    should_notify: bool
    text: str
    suppressed_reason: str | None
    detections: tuple[LedgerRow, ...]


def build_notification(
    rows: Iterable[LedgerRow],
    *,
    shadow_mode: bool = False,
) -> NotificationPayload | None:
    detections = tuple(row for row in rows if row.status == Status.FAILURE)
    if shadow_mode:
        if detections:
            names = ", ".join(row.name for row in detections)
            text = f"期限超過を検出しました（シャドー中につき未送信）: {names}"
        else:
            text = "異常なし（シャドー中につき未送信）"
        return NotificationPayload(
            should_notify=False,
            text=text,
            suppressed_reason="shadow mode: notifications suppressed",
            detections=detections,
        )
    if not detections:
        return NotificationPayload(
            should_notify=False,
            text="異常なし",
            suppressed_reason=None,
            detections=(),
        )
    lines = ["期限超過を検出しました:"]
    for row in detections:
        lines.append(f"- {row.name} (周期 {row.period})")
    return NotificationPayload(
        should_notify=True,
        text="\n".join(lines),
        suppressed_reason=None,
        detections=detections,
    )


def read_notify_flag(path: str | Path) -> bool:
    """Return True only if the flag file explicitly enables notify.

    Missing file or any parse problem means shadow (fail-safe: the
    default is *not* to notify), per design.md section 9.
    """
    target = Path(path)
    if not target.exists():
        return False
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("notify") is True
