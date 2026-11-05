"""連続失敗回数: 失敗が続く場合に正しく数え、成功でリセットされる。"""

from __future__ import annotations

from datetime import timedelta


def _runs(now, results):
    """results: 古い順の成否リスト。RunRecord の並びを作る。"""
    from watchdog.ledger import RunRecord

    base = now - timedelta(days=len(results))
    return [
        RunRecord(finished_at=base + timedelta(days=i), succeeded=ok)
        for i, ok in enumerate(results)
    ]


def test_count_all_failures(now):
    from watchdog.ledger import count_consecutive_failures

    assert count_consecutive_failures(_runs(now, [False, False, False])) == 3


def test_count_resets_on_latest_success(now):
    from watchdog.ledger import count_consecutive_failures

    assert count_consecutive_failures(_runs(now, [False, False, True])) == 0


def test_count_only_failures_after_last_success(now):
    from watchdog.ledger import count_consecutive_failures

    runs = _runs(now, [False, True, False, False])

    assert count_consecutive_failures(runs) == 2


def test_count_empty_history_is_zero(now):
    from watchdog.ledger import count_consecutive_failures

    assert count_consecutive_failures([]) == 0


def test_count_single_failure_is_one(now):
    from watchdog.ledger import count_consecutive_failures

    assert count_consecutive_failures(_runs(now, [False])) == 1


def test_count_single_success_is_zero(now):
    from watchdog.ledger import count_consecutive_failures

    assert count_consecutive_failures(_runs(now, [True])) == 0


def test_count_early_failures_do_not_leak_past_success(now):
    from watchdog.ledger import count_consecutive_failures

    runs = _runs(now, [False, False, False, True, False])

    assert count_consecutive_failures(runs) == 1
