"""CLI: definitions + snapshot + state store -> ledger rows.

Subcommands:
  check          judge all targets, print ledger rows (JSON or CSV),
                 merge the state store, record a heartbeat, and *log*
                 the notification payload (never sends anything).
  heartbeat      record a heartbeat only.
  shadow-status  show whether notifications are enabled by the flag.

Exit codes: 0 = ok, 2 = some targets UNKNOWN (partial), 1 = failure.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

from watchdog.clock import resolve_now
from watchdog.definitions import load_definitions_file
from watchdog.heartbeat import append_heartbeat_record, record_heartbeat
from watchdog.ledger import build_ledger_row, extract_overdue
from watchdog.notify import build_notification, read_notify_flag
from watchdog.snapshot import build_job_states, load_snapshot
from watchdog.state import apply_store, load_state, merge_observations, save_state
from watchdog.status import Status

DEFAULT_DATA_DIR = Path.home() / "workspace" / "cron-watchdog-data"

# Single definition of the ledger-row serialization shape: the key
# order here is both the JSON key order and the CSV column order.
ROW_FIELDS = (
    "name",
    "period",
    "last_success_at",
    "consecutive_failures",
    "next_due_at",
    "status",
)


def _row_dict(row) -> dict:
    values = {
        "name": row.name,
        "period": row.period,
        "last_success_at": (
            row.last_success_at.isoformat() if row.last_success_at else None
        ),
        "consecutive_failures": row.consecutive_failures,
        "next_due_at": row.next_due_at.isoformat() if row.next_due_at else None,
        "status": row.status.value,
    }
    return {field: values[field] for field in ROW_FIELDS}


def _rows_json(rows) -> str:
    return json.dumps([_row_dict(r) for r in rows], ensure_ascii=False, indent=2)


def _build_rows(args: argparse.Namespace, now: datetime):
    """Load inputs, apply the state store and build the ledger rows."""
    definitions = load_definitions_file(args.definitions)
    snapshot = load_snapshot(args.snapshot)
    store = load_state(args.state)
    states = apply_store(store, build_job_states(definitions, snapshot))
    rows = [build_ledger_row(state, now) for state in states]
    return store, states, rows


def _persist_state(args: argparse.Namespace, store, states) -> None:
    merge_observations(store, states)
    save_state(args.state, store)


def _emit_rows(args: argparse.Namespace, rows) -> None:
    """Write the optional --out file and print the rows to stdout."""
    if args.out:
        Path(args.out).write_text(_rows_json(rows) + "\n", encoding="utf-8")
    if args.format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(ROW_FIELDS))
        writer.writeheader()
        for row in rows:
            writer.writerow(_row_dict(row))
        sys.stdout.write(buffer.getvalue())
    else:
        print(_rows_json(rows))


def _record_check_heartbeat(
    data_dir: Path, args: argparse.Namespace, now: datetime, rows
) -> tuple[list[str], list[str]]:
    """Record the heartbeat in both stores; return (anomalies, unknown)."""
    # Heartbeat: JSONL log + plain last-run file, both outside the ledger.
    record_heartbeat(data_dir / "last-run.txt", now)
    anomalies = [r.name for r in extract_overdue(rows)]
    unknown = [r.name for r in rows if r.status == Status.UNKNOWN]
    append_heartbeat_record(
        data_dir / "watchdog-heartbeat.jsonl",
        {
            "run_id": str(uuid.uuid4()),
            "mode": "check",
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "result": "partial" if unknown else "ok",
            "targets_checked": len(rows),
            "anomalies": anomalies,
            "snapshot": str(args.snapshot),
        },
    )
    return anomalies, unknown


def _log_notification(data_dir: Path, now: datetime, rows) -> tuple[bool, Path]:
    """Generate the notification payload and log it; return (enabled, outbox)."""
    # Notification: generate + log only. Sending is never done here;
    # shadow is in effect unless the flag file explicitly enables it.
    notify_enabled = read_notify_flag(data_dir / "notify-flag.json")
    payload = build_notification(rows, shadow_mode=not notify_enabled)
    outbox = data_dir / "outbox" / "notifications.jsonl"
    outbox.parent.mkdir(parents=True, exist_ok=True)
    with outbox.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "at": now.isoformat(),
                    "would_notify": bool(payload and payload.should_notify),
                    "suppressed_reason": payload.suppressed_reason if payload else None,
                    "text": payload.text if payload else None,
                    "detections": (
                        [r.name for r in payload.detections] if payload else []
                    ),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return notify_enabled, outbox


def _cmd_check(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    now = resolve_now(args.now)
    store, states, rows = _build_rows(args, now)

    _persist_state(args, store, states)
    _emit_rows(args, rows)

    anomalies, unknown = _record_check_heartbeat(data_dir, args, now, rows)
    notify_enabled, outbox = _log_notification(data_dir, now, rows)

    print(
        f"[watchdog] checked={len(rows)} overdue={anomalies} "
        f"unknown={unknown} notify_enabled={notify_enabled} "
        f"notification logged to {outbox} (not sent)",
        file=sys.stderr,
    )
    return 2 if unknown else 0


def _cmd_heartbeat(args: argparse.Namespace) -> int:
    now = resolve_now(args.now)
    path = Path(args.data_dir) / "last-run.txt"
    record_heartbeat(path, now)
    print(f"heartbeat recorded: {path} {now.isoformat()}")
    return 0


def _cmd_shadow_status(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    enabled = read_notify_flag(data_dir / "notify-flag.json")
    mode = "notify enabled" if enabled else "shadow (notifications suppressed)"
    print(f"notify-flag: {data_dir / 'notify-flag.json'}")
    print(f"mode: {mode}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="watchdog")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check")
    p_check.add_argument("--definitions", required=True)
    p_check.add_argument("--snapshot", required=True)
    p_check.add_argument("--state", required=True)
    p_check.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    p_check.add_argument("--out")
    p_check.add_argument("--format", choices=["json", "csv"], default="json")
    p_check.add_argument("--now", help="ISO datetime override (testing)")
    p_check.set_defaults(func=_cmd_check)

    p_hb = sub.add_parser("heartbeat")
    p_hb.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    p_hb.add_argument("--now")
    p_hb.set_defaults(func=_cmd_heartbeat)

    p_shadow = sub.add_parser("shadow-status")
    p_shadow.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    p_shadow.set_defaults(func=_cmd_shadow_status)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # CLI boundary: report, exit 1
        print(f"[watchdog] error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
