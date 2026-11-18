"""Regression tests: naive/aware datetime mixing used to raise TypeError.

Verified failure paths (2026-11-18 review):
1. a naive ``--now`` compared against an aware ``last_success_at``
   in ``watchdog.status``;
2. the default aware "now" compared against a naive snapshot
   ``last_success_at``;
3. a naive stored ``last_success_at`` merged with an aware observed
   value in ``watchdog.state``.

Parse boundaries (``resolve_now``, snapshot ``_parse_dt`` and
``load_state``) now attach Asia/Tokyo to naive values, so all values
reaching a comparison are aware. Aware input is never converted.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

JST = timezone(timedelta(hours=9))
TOKYO = ZoneInfo("Asia/Tokyo")


def _definition(name="job-a"):
    from watchdog.definitions import load_definitions

    return load_definitions(
        [
            {
                "name": name,
                "evidence_type": "log_success",
                "period": "1d",
                "tolerance_seconds": 7200,
                "timezone": "Asia/Tokyo",
            }
        ]
    )[0]


def test_resolve_now_attaches_tokyo_to_naive_override():
    from watchdog.clock import resolve_now

    resolved = resolve_now("2026-11-05T12:00:00")

    assert resolved == datetime(2026, 11, 5, 12, 0, tzinfo=TOKYO)
    assert resolved.utcoffset() == timedelta(hours=9)


def test_resolve_now_keeps_aware_override_unchanged():
    from watchdog.clock import resolve_now

    resolved = resolve_now("2026-11-05T03:00:00+00:00")

    assert resolved.utcoffset() == timedelta(0)


def test_snapshot_naive_last_success_compares_with_aware_now():
    from watchdog.snapshot import build_job_states
    from watchdog.status import Status, evaluate_status

    definition = _definition()
    snapshot = {
        "targets": {
            "job-a": {
                "status": {
                    "last_success_at": "2026-11-05T11:00:00",  # naive
                    "consecutive_failures": 0,
                    "in_flight": False,
                },
                "runs": [],
            }
        }
    }

    (state,) = build_job_states([definition], snapshot)

    assert state.last_success_at == datetime(2026, 11, 5, 11, 0, tzinfo=TOKYO)
    now = datetime(2026, 11, 5, 12, 0, tzinfo=JST)
    assert evaluate_status(definition, state.last_success_at, now) is Status.SUCCESS


def test_stored_naive_last_success_merges_with_aware_observation(tmp_path):
    from watchdog.ledger import JobState
    from watchdog.state import load_state, merge_observations

    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "jobs": {
                    "job-a": {
                        "last_success_at": "2026-11-05T11:00:00",  # naive
                        "consecutive_failures": 1,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    store = load_state(path)
    observed = JobState(
        definition=_definition(),
        last_success_at=datetime(2026, 11, 5, 12, 0, tzinfo=JST),
        consecutive_failures=0,
        evidence_available=True,
    )

    merged = merge_observations(store, [observed])

    assert merged.jobs["job-a"].last_success_at == observed.last_success_at
