"""台帳行の生成（完了の定義1項目目）.

1エントリから「予定周期・最終成功時刻・連続失敗回数・次回予定・
状態」を含む行データが生成される。
台帳には主要な定期実行が登録され、最終成功時刻が保持される。
"""

from __future__ import annotations

from datetime import timedelta

from conftest import make_definition


def _row(daily_definition_row, now, **state_kwargs):
    from watchdog.ledger import JobState, build_ledger_row

    definition = make_definition(daily_definition_row)
    state = JobState(definition=definition, **state_kwargs)
    return build_ledger_row(state, now)


def test_ledger_row_contains_all_required_fields(daily_definition_row, now):
    last_success = now - timedelta(hours=3)

    row = _row(
        daily_definition_row,
        now,
        last_success_at=last_success,
        consecutive_failures=2,
    )

    assert row.name == "daily-fortune"
    assert row.period == "1d"  # 予定周期
    assert row.last_success_at == last_success  # 最終成功時刻
    assert row.consecutive_failures == 2  # 連続失敗回数
    assert row.next_due_at == last_success + timedelta(days=1)  # 次回予定
    assert row.status is not None  # 状態


def test_ledger_row_status_is_success_when_fresh(daily_definition_row, now):
    from watchdog.status import Status

    row = _row(
        daily_definition_row, now, last_success_at=now - timedelta(hours=1)
    )

    assert row.status == Status.SUCCESS


def test_ledger_row_status_is_failure_when_overdue(daily_definition_row, now):
    from watchdog.status import Status

    row = _row(
        daily_definition_row, now, last_success_at=now - timedelta(days=3)
    )

    assert row.status == Status.FAILURE


def test_ledger_row_for_never_run_job(daily_definition_row, now):
    from watchdog.status import Status

    row = _row(daily_definition_row, now, last_success_at=None)

    assert row.status == Status.NOT_RUN
    assert row.last_success_at is None
    assert row.next_due_at is None
    assert row.consecutive_failures == 0


def test_ledger_rows_cover_all_registered_definitions(
    sample_definition_rows, now
):
    """定義表の全エントリについて台帳行が生成される（登録漏れなし）。"""
    from watchdog.definitions import load_definitions
    from watchdog.ledger import JobState, build_ledger_row

    definitions = load_definitions(sample_definition_rows)

    rows = [
        build_ledger_row(
            JobState(
                definition=d, last_success_at=now - timedelta(minutes=30)
            ),
            now,
        )
        for d in definitions
    ]

    assert [row.name for row in rows] == [d.name for d in definitions]
    assert all(
        row.last_success_at == now - timedelta(minutes=30) for row in rows
    )
