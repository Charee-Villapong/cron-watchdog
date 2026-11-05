"""次回予定の算出: 周期から次回予定時刻が計算できる。"""

from __future__ import annotations

from datetime import timedelta

from conftest import make_definition


def test_next_due_daily_is_last_success_plus_one_day(
    daily_definition_row, now
):
    from watchdog.ledger import compute_next_due

    definition = make_definition(daily_definition_row)
    last_success = now - timedelta(hours=5)

    assert compute_next_due(definition, last_success) == last_success + timedelta(
        days=1
    )


def test_next_due_weekly_is_last_success_plus_seven_days(
    weekly_definition_row, now
):
    from watchdog.ledger import compute_next_due

    definition = make_definition(weekly_definition_row)

    assert compute_next_due(definition, now) == now + timedelta(days=7)


def test_next_due_subdaily_period(now):
    from watchdog.definitions import load_definitions
    from watchdog.ledger import compute_next_due

    (definition,) = load_definitions(
        [
            {
                "name": "frequent-check",
                "evidence_type": "log_success",
                "period": "6h",
                "tolerance_seconds": 600,
                "timezone": "Asia/Tokyo",
            }
        ]
    )

    assert compute_next_due(definition, now) == now + timedelta(hours=6)


def test_next_due_without_last_success_is_none(daily_definition_row):
    from watchdog.ledger import compute_next_due

    definition = make_definition(daily_definition_row)

    assert compute_next_due(definition, None) is None
