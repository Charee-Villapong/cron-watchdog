"""見守り自身の死活記録（必須要件3）.

実行のたびに、見守り対象とは別のローカルファイルへ最終実行時刻が
書かれ、読み戻せること。
"""

from __future__ import annotations

from datetime import timedelta


def test_heartbeat_is_written_and_read_back(tmp_path, now):
    from watchdog.heartbeat import read_heartbeat, record_heartbeat

    path = tmp_path / "watchdog-self-heartbeat.txt"

    record_heartbeat(path, now)

    assert path.exists()
    assert read_heartbeat(path) == now


def test_heartbeat_is_overwritten_with_latest_run(tmp_path, now):
    from watchdog.heartbeat import read_heartbeat, record_heartbeat

    path = tmp_path / "watchdog-self-heartbeat.txt"
    later = now + timedelta(hours=1)

    record_heartbeat(path, now)
    record_heartbeat(path, later)

    assert read_heartbeat(path) == later


def test_heartbeat_does_not_touch_the_ledger_file(tmp_path, now):
    """死活記録は対象台帳とは別ファイルであり、台帳を書き換えない。"""
    from watchdog.heartbeat import record_heartbeat

    ledger_path = tmp_path / "ledger.csv"
    ledger_original = "name,last_success_at\nfictional-job,2026-11-01\n"
    ledger_path.write_text(ledger_original, encoding="utf-8")
    heartbeat_path = tmp_path / "watchdog-self-heartbeat.txt"

    record_heartbeat(heartbeat_path, now)

    assert heartbeat_path != ledger_path
    assert ledger_path.read_text(encoding="utf-8") == ledger_original


def test_read_heartbeat_missing_file_returns_none(tmp_path):
    from watchdog.heartbeat import read_heartbeat

    assert read_heartbeat(tmp_path / "no-such-file.txt") is None


def test_heartbeat_read_back_is_timezone_aware(tmp_path, now):
    from watchdog.heartbeat import read_heartbeat, record_heartbeat

    path = tmp_path / "watchdog-self-heartbeat.txt"
    record_heartbeat(path, now)

    result = read_heartbeat(path)

    assert result is not None
    assert result.tzinfo is not None
    assert result.utcoffset() == now.utcoffset()
