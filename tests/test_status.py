"""状態判定: 成功 / 失敗（期限超過）/ 未実行 / 実行中 / 判定不能.

必須要件2: 状態は5つに分け、実行中と判定不能を失敗と混ぜない。
期限 = 最終成功 + 周期 + 許容遅延。
daily-fortune の定義: period=1d, tolerance=7200s (2h)
-> now=2026-11-05 12:00 JST のとき期限は最終成功 + 26h。
"""

from __future__ import annotations

from datetime import timedelta

from conftest import make_definition


def test_status_within_deadline_is_success(daily_definition_row, now):
    from watchdog.status import Status, evaluate_status

    definition = make_definition(daily_definition_row)
    last_success = now - timedelta(hours=25)  # 期限(26h)内

    assert evaluate_status(definition, last_success, now) == Status.SUCCESS


def test_status_exactly_at_deadline_is_success(daily_definition_row, now):
    from watchdog.status import Status, evaluate_status

    definition = make_definition(daily_definition_row)
    last_success = now - timedelta(hours=26)  # ちょうど期限

    assert evaluate_status(definition, last_success, now) == Status.SUCCESS


def test_status_past_deadline_is_failure_overdue(daily_definition_row, now):
    from watchdog.status import Status, evaluate_status

    definition = make_definition(daily_definition_row)
    last_success = now - timedelta(hours=26, seconds=1)  # 期限を1秒超過

    status = evaluate_status(definition, last_success, now)

    assert status == Status.FAILURE


def test_status_uses_tolerance_not_just_period(daily_definition_row, now):
    """周期は過ぎたが許容遅延内なら、まだ失敗にしない。"""
    from watchdog.status import Status, evaluate_status

    definition = make_definition(daily_definition_row)
    # 周期(24h)は超過、周期+許容(26h)は未超過
    last_success = now - timedelta(hours=25, minutes=30)

    assert evaluate_status(definition, last_success, now) == Status.SUCCESS


def test_status_no_history_is_not_run(daily_definition_row, now):
    from watchdog.status import Status, evaluate_status

    definition = make_definition(daily_definition_row)

    status = evaluate_status(definition, None, now)

    assert status == Status.NOT_RUN
    assert status != Status.FAILURE


def test_status_running_is_running_not_failure(daily_definition_row, now):
    """実行中の run がある場合は、最終成功が古くても失敗と混ぜない。"""
    from watchdog.status import Status, evaluate_status

    definition = make_definition(daily_definition_row)
    last_success = now - timedelta(days=10)  # 単独なら期限超過

    status = evaluate_status(definition, last_success, now, running=True)

    assert status == Status.RUNNING
    assert status != Status.FAILURE


def test_status_evidence_unavailable_is_unknown_not_failure(
    daily_definition_row, now
):
    """証跡が取得できない場合は判定不能とし、失敗と混ぜない。"""
    from watchdog.status import Status, evaluate_status

    definition = make_definition(daily_definition_row)
    last_success = now - timedelta(days=10)

    status = evaluate_status(
        definition, last_success, now, evidence_available=False
    )

    assert status == Status.UNKNOWN
    assert status != Status.FAILURE


def test_status_values_are_the_five_japanese_labels():
    from watchdog.status import Status

    assert {s.value for s in Status} == {
        "未実行",
        "実行中",
        "成功",
        "失敗",
        "判定不能",
    }
