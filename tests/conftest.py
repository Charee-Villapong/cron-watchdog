"""Shared fixtures for watchdog tests.

No import of ``watchdog`` at module level: collection must succeed
even while the implementation does not exist yet. Each test imports
``watchdog`` inside its own body.

All data is fictional. Datetimes are timezone-aware and injected
via the ``now`` argument everywhere; no test reads the wall clock
for the behaviour under test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

JST = timezone(timedelta(hours=9), name="Asia/Tokyo")


@pytest.fixture()
def tz_jst():
    return JST


@pytest.fixture()
def now():
    """Fixed 'now' used by every judgement test: 2026-11-05 12:00 JST."""
    return datetime(2026, 11, 5, 12, 0, 0, tzinfo=JST)


@pytest.fixture()
def daily_definition_row():
    """One valid definition row (fictional job)."""
    return {
        "name": "daily-fortune",
        "evidence_type": "log_success",
        "period": "1d",
        "tolerance_seconds": 7200,  # 2 hours
        "timezone": "Asia/Tokyo",
    }


@pytest.fixture()
def weekly_definition_row():
    return {
        "name": "weekly-cleanup",
        "evidence_type": "log_success",
        "period": "7d",
        "tolerance_seconds": 3600,  # 1 hour
        "timezone": "Asia/Tokyo",
    }


@pytest.fixture()
def sample_definition_rows(daily_definition_row, weekly_definition_row):
    return [
        daily_definition_row,
        weekly_definition_row,
        {
            "name": "threads-collection",
            "evidence_type": "sheet_updated",
            "period": "2d",
            "tolerance_seconds": 10800,
            "timezone": "Asia/Tokyo",
        },
    ]


def make_definition(row):
    """Helper (not a fixture): build a Definition via the public API."""
    from watchdog.definitions import load_definitions

    return load_definitions([row])[0]
