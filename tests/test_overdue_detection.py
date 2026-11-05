"""期限超過の試験シナリオ（完了の定義2項目目の直接の検証）.

「わざと1件の定例を止めた試験で、期限超過として検知・報告されること」
を、過去日時の最終成功時刻を持つエントリで検証する。
"""

from __future__ import annotations

from datetime import timedelta

from conftest import make_definition


def _state(definition, last_success_at, **kwargs):
    from watchdog.ledger import JobState

    return JobState(
        definition=definition, last_success_at=last_success_at, **kwargs
    )


def test_stopped_job_with_old_last_success_is_detected_as_overdue(
    daily_definition_row, now
):
    """止めた定例: 最終成功が3日前 -> 期限超過として検出リストに入る。"""
    from watchdog.ledger import detect_overdue
    from watchdog.status import Status

    definition = make_definition(daily_definition_row)
    stopped = _state(definition, now - timedelta(days=3))

    detected = detect_overdue([stopped], now)

    assert len(detected) == 1
    assert detected[0].name == "daily-fortune"
    assert detected[0].status == Status.FAILURE


def test_fresh_job_is_not_detected_as_overdue(daily_definition_row, now):
    from watchdog.ledger import detect_overdue

    definition = make_definition(daily_definition_row)
    fresh = _state(definition, now - timedelta(hours=1))

    assert detect_overdue([fresh], now) == []


def test_only_the_overdue_job_is_detected_among_many(
    sample_definition_rows, now
):
    from watchdog.definitions import load_definitions
    from watchdog.ledger import detect_overdue

    daily, weekly, threads = load_definitions(sample_definition_rows)
    states = [
        _state(daily, now - timedelta(days=3)),       # 期限超過 (1d+2h)
        _state(weekly, now - timedelta(days=2)),      # 期限内 (7d+1h)
        _state(threads, now - timedelta(hours=3)),    # 期限内 (2d+3h)
    ]

    detected = detect_overdue(states, now)

    assert [row.name for row in detected] == ["daily-fortune"]


def test_running_job_is_not_detected_as_overdue(daily_definition_row, now):
    from watchdog.ledger import detect_overdue

    definition = make_definition(daily_definition_row)
    running = _state(definition, now - timedelta(days=3), running=True)

    assert detect_overdue([running], now) == []


def test_unknown_job_is_not_detected_as_overdue(daily_definition_row, now):
    from watchdog.ledger import detect_overdue

    definition = make_definition(daily_definition_row)
    unknown = _state(
        definition, now - timedelta(days=3), evidence_available=False
    )

    assert detect_overdue([unknown], now) == []


def test_not_run_job_is_not_detected_as_overdue(daily_definition_row, now):
    """実行履歴が無い（未実行）ものは期限超過の検出には入れない。"""
    from watchdog.ledger import detect_overdue

    definition = make_definition(daily_definition_row)
    never_run = _state(definition, None)

    assert detect_overdue([never_run], now) == []
