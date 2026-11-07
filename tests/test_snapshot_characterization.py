"""snapshot.py の現状固定テスト（特性テスト）: C-046.

リファクタリング候補 C-046（追加モジュール3つが丸ごと無テスト）の
うち `watchdog.snapshot` を対象とする。テスト契約（tests/interfaces.md）
には無い追加モジュールのため、仕様の置き場は docs/design.md §10.4
（スナップショット JSON の形式）と §4.4／§5.4 の経路特記、および
ブラックボックス実行で観測した現行の入出力である。

固定する現行挙動の要点:
- 定義にあってスナップショットに無い対象は「証跡なし」
  （evidence_available=False、最終成功なし）になる。
- collect_errors にキーが存在する対象は、targets に実データが
  あっても証跡なし扱いが優先する（値が空文字／None でも同じ）。
- 最終成功は status.last_success_at が正で、runs への
  フォールバックは status 側が無い場合にだけ起きる。
- 実行中判定は2系統: status.in_flight と「started_at があって
  finished_at が無い run」の存在。last_status 文字列は使われない。
- consecutive_failures は int（bool を除く）のときだけ採用され、
  それ以外は 0 に倒れる。
- result_summary は一切読まれない（sanitized_snapshot_errors は
  error_text のみを、マスキングして取り出す）。

データはすべて架空。実データディレクトリは使わない。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

JST = timezone(timedelta(hours=9))

ROWS = [
    {
        "name": "job-a",
        "evidence_type": "log_success",
        "period": "1d",
        "tolerance_seconds": 7200,
        "timezone": "Asia/Tokyo",
    },
    {
        "name": "job-b",
        "evidence_type": "log_success",
        "period": "1d",
        "tolerance_seconds": 7200,
        "timezone": "Asia/Tokyo",
    },
]


def _definitions():
    from watchdog.definitions import load_definitions

    return load_definitions(ROWS)


def _states_by_name(snapshot):
    from watchdog.snapshot import build_job_states

    return {s.definition.name: s for s in build_job_states(_definitions(), snapshot)}


def _target(status=None, runs=None):
    entry = {}
    if status is not None:
        entry["status"] = status
    if runs is not None:
        entry["runs"] = runs
    return entry


def _status(**overrides):
    status = {
        "consecutive_failures": 0,
        "enabled": True,
        "in_flight": False,
        "last_success_at": "2026-11-05T11:00:00+09:00",
    }
    status.update(overrides)
    return status


# --- 証跡の有無 -----------------------------------------------------------


def test_missing_target_is_evidence_unavailable():
    states = _states_by_name({"targets": {}})

    for state in states.values():
        assert state.evidence_available is False
        assert state.last_success_at is None
        assert state.consecutive_failures == 0
        assert state.running is False


def test_collect_error_takes_precedence_over_present_target():
    snapshot = {
        "targets": {"job-a": _target(status=_status(consecutive_failures=3))},
        "collect_errors": {"job-a": "SOURCE_MISSING"},
    }

    state = _states_by_name(snapshot)["job-a"]

    assert state.evidence_available is False
    assert state.last_success_at is None
    assert state.consecutive_failures == 0


@pytest.mark.parametrize("error_value", ["", None])
def test_collect_error_key_presence_alone_marks_unavailable(error_value):
    snapshot = {"targets": {}, "collect_errors": {"job-a": error_value}}

    state = _states_by_name(snapshot)["job-a"]

    assert state.evidence_available is False


def test_present_but_empty_target_is_evidence_available():
    state = _states_by_name({"targets": {"job-a": {}}})["job-a"]

    assert state.evidence_available is True
    assert state.last_success_at is None
    assert state.consecutive_failures == 0


def test_unknown_targets_in_snapshot_are_ignored():
    snapshot = {
        "targets": {
            "unknown-job": _target(status=_status()),
            "job-a": _target(status=_status()),
        }
    }

    states = _states_by_name(snapshot)

    assert list(states) == ["job-a", "job-b"]


# --- 最終成功の決定 -------------------------------------------------------


def test_status_last_success_and_failures_are_adopted():
    snapshot = {
        "targets": {"job-a": _target(status=_status(consecutive_failures=2))}
    }

    state = _states_by_name(snapshot)["job-a"]

    assert state.last_success_at == datetime(2026, 11, 5, 11, 0, tzinfo=JST)
    assert state.consecutive_failures == 2
    assert state.evidence_available is True


def test_fallback_scans_succeeded_runs_for_latest_finish():
    """status に最終成功が無い場合、成功 run の finished_at 最大値を使う。

    後続の失敗 run は数えず、成功 run 同士では最も新しいものを取る。
    """
    runs = [
        {"status": "succeeded", "finished_at": "2026-11-03T10:00:00+09:00"},
        {"status": "failed", "finished_at": "2026-11-04T10:00:00+09:00"},
        {"status": "succeeded", "finished_at": "2026-11-04T09:00:00+09:00"},
    ]
    snapshot = {
        "targets": {
            "job-a": _target(status=_status(last_success_at=None), runs=runs)
        }
    }

    state = _states_by_name(snapshot)["job-a"]

    assert state.last_success_at == datetime(2026, 11, 4, 9, 0, tzinfo=JST)


def test_status_last_success_wins_over_later_succeeded_run():
    """status 側に値があれば runs は見ない（最大値マージではない）。"""
    runs = [{"status": "succeeded", "finished_at": "2026-11-04T10:00:00+09:00"}]
    snapshot = {
        "targets": {
            "job-a": _target(
                status=_status(last_success_at="2026-11-03T10:00:00+09:00"),
                runs=runs,
            )
        }
    }

    state = _states_by_name(snapshot)["job-a"]

    assert state.last_success_at == datetime(2026, 11, 3, 10, 0, tzinfo=JST)


def test_succeeded_run_without_finished_at_gives_no_fallback():
    runs = [{"status": "succeeded", "started_at": "2026-11-04T10:00:00+09:00"}]
    snapshot = {
        "targets": {
            "job-a": _target(status=_status(last_success_at=None), runs=runs)
        }
    }

    state = _states_by_name(snapshot)["job-a"]

    assert state.last_success_at is None


def test_invalid_status_datetime_raises_snapshot_error():
    from watchdog.snapshot import SnapshotError

    snapshot = {
        "targets": {"job-a": _target(status=_status(last_success_at="not-a-date"))}
    }

    with pytest.raises(SnapshotError):
        _states_by_name(snapshot)


def test_non_string_status_datetime_raises_snapshot_error():
    from watchdog.snapshot import SnapshotError

    snapshot = {"targets": {"job-a": _target(status=_status(last_success_at=12345))}}

    with pytest.raises(SnapshotError):
        _states_by_name(snapshot)


def test_date_only_datetime_is_accepted_as_midnight_naive():
    snapshot = {
        "targets": {"job-a": _target(status=_status(last_success_at="2026-11-05"))}
    }

    state = _states_by_name(snapshot)["job-a"]

    assert state.last_success_at == datetime(2026, 11, 5, 0, 0)
    assert state.last_success_at.tzinfo is None


# --- 連続失敗回数の型ガード -------------------------------------------------


@pytest.mark.parametrize("raw", ["3", 2.7, None, True])
def test_non_int_consecutive_failures_falls_back_to_zero(raw):
    snapshot = {
        "targets": {"job-a": _target(status=_status(consecutive_failures=raw))}
    }

    state = _states_by_name(snapshot)["job-a"]

    assert state.consecutive_failures == 0


def test_negative_int_consecutive_failures_is_kept_verbatim():
    snapshot = {
        "targets": {"job-a": _target(status=_status(consecutive_failures=-1))}
    }

    state = _states_by_name(snapshot)["job-a"]

    assert state.consecutive_failures == -1


# --- 実行中判定の2系統 -------------------------------------------------------


def test_in_flight_flag_marks_running():
    snapshot = {"targets": {"job-a": _target(status=_status(in_flight=True))}}

    assert _states_by_name(snapshot)["job-a"].running is True


def test_unfinished_run_marks_running_even_if_not_in_flight():
    runs = [
        {
            "status": "failed",
            "started_at": "2026-11-05T10:00:00+09:00",
            "finished_at": None,
        }
    ]
    snapshot = {
        "targets": {"job-a": _target(status=_status(in_flight=False), runs=runs)}
    }

    assert _states_by_name(snapshot)["job-a"].running is True


def test_finished_run_does_not_mark_running():
    runs = [
        {
            "status": "succeeded",
            "started_at": "2026-11-05T09:00:00+09:00",
            "finished_at": "2026-11-05T10:00:00+09:00",
        }
    ]
    snapshot = {"targets": {"job-a": _target(status=_status(), runs=runs)}}

    assert _states_by_name(snapshot)["job-a"].running is False


def test_last_status_running_string_alone_does_not_mark_running():
    snapshot = {
        "targets": {"job-a": _target(status=_status(last_status="running"))}
    }

    assert _states_by_name(snapshot)["job-a"].running is False


# --- load_snapshot -----------------------------------------------------------


def test_load_snapshot_roundtrip(tmp_path):
    import json

    from watchdog.snapshot import load_snapshot

    payload = {"collected_at": "2026-11-05T12:00:00+09:00", "targets": {}}
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert load_snapshot(path) == payload


def test_load_snapshot_missing_file_raises_snapshot_error(tmp_path):
    from watchdog.snapshot import SnapshotError, load_snapshot

    with pytest.raises(SnapshotError):
        load_snapshot(tmp_path / "no-such-snapshot.json")


def test_load_snapshot_invalid_json_raises_snapshot_error(tmp_path):
    from watchdog.snapshot import SnapshotError, load_snapshot

    path = tmp_path / "snapshot.json"
    path.write_text("{oops", encoding="utf-8")

    with pytest.raises(SnapshotError):
        load_snapshot(path)


@pytest.mark.parametrize("payload", ["[1, 2]", '"hi"', "42"])
def test_load_snapshot_non_object_raises_snapshot_error(tmp_path, payload):
    from watchdog.snapshot import SnapshotError, load_snapshot

    path = tmp_path / "snapshot.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(SnapshotError):
        load_snapshot(path)


# --- sanitized_snapshot_errors ----------------------------------------------


def test_sanitized_errors_masks_error_text():
    from watchdog.snapshot import sanitized_snapshot_errors

    snapshot = {
        "targets": {
            "job-a": {
                "runs": [
                    {
                        "status": "failed",
                        "error_text": "failed for user123@example.invalid "
                        "with Bearer FAKEtoken1234567890abcdef",
                    }
                ]
            }
        }
    }

    result = sanitized_snapshot_errors(snapshot)

    assert result == {"job-a": "failed for [masked-email] with Bearer [masked]"}


def test_sanitized_errors_takes_first_run_with_error_text():
    from watchdog.snapshot import sanitized_snapshot_errors

    snapshot = {
        "targets": {
            "job-a": {
                "runs": [
                    {"status": "failed", "error_text": None},
                    {"status": "failed", "error_text": "first error"},
                    {"status": "failed", "error_text": "second error"},
                ]
            },
            "job-b": {"runs": [{"status": "succeeded", "error_text": None}]},
        }
    }

    assert sanitized_snapshot_errors(snapshot) == {"job-a": "first error"}


def test_sanitized_errors_includes_targets_outside_definitions():
    from watchdog.snapshot import sanitized_snapshot_errors

    snapshot = {
        "targets": {
            "unknown-x": {"runs": [{"status": "failed", "error_text": "boom"}]}
        }
    }

    assert sanitized_snapshot_errors(snapshot) == {"unknown-x": "boom"}


def test_sanitized_errors_caps_long_text_at_200():
    from watchdog.snapshot import sanitized_snapshot_errors

    snapshot = {
        "targets": {
            "job-a": {"runs": [{"status": "failed", "error_text": "word " * 100}]}
        }
    }

    result = sanitized_snapshot_errors(snapshot)

    assert len(result["job-a"]) == 200


def test_sanitized_errors_empty_snapshot_returns_empty_dict():
    from watchdog.snapshot import sanitized_snapshot_errors

    assert sanitized_snapshot_errors({"targets": {}}) == {}
