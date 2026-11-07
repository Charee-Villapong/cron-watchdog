"""state.py の現状固定テスト（特性テスト）: C-046.

リファクタリング候補 C-046（追加モジュール3つが丸ごと無テスト）の
うち `watchdog.state` を対象とする。設計上の正は docs/design.md §5.4:
状態ストアへの累積マージは「最終成功は単調増加（過去に戻らない）」が
中核保証である。以下はブラックボックス実行で観測した現行挙動の固定。

固定する現行挙動の要点:
- 最終成功は max（観測値と保存値の新しい方）。古い観測では後退しない。
- 一方、連続失敗回数は単調ではなく、最新の観測値で常に置き換わる
  （最終成功が後退しない観測でも置き換わる）。
- apply_store は保存側の新しい最終成功を判定用 JobState へ反映するが、
  連続失敗回数は観測側の値をそのまま使う（保存値は適用しない）。
- ストアが無い（ファイルが無い）場合は空のストアとして扱う。

すべて tmp_path 配下で実行し、実データには触れない。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

JST = timezone(timedelta(hours=9))
T_OLD = datetime(2026, 11, 4, 11, 0, tzinfo=JST)
T_STORED = datetime(2026, 11, 5, 11, 0, tzinfo=JST)
T_NEW = datetime(2026, 11, 5, 12, 0, tzinfo=JST)


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


def _job_state(last_success_at, consecutive_failures=0, **kwargs):
    from watchdog.ledger import JobState

    return JobState(
        definition=_definition(),
        last_success_at=last_success_at,
        consecutive_failures=consecutive_failures,
        **kwargs,
    )


def _store(last_success_at=T_STORED, consecutive_failures=1, name="job-a"):
    from watchdog.state import StateStore, StoredJob

    return StateStore(
        jobs={name: StoredJob(last_success_at, consecutive_failures)}
    )


# --- load / save -------------------------------------------------------------


def test_load_missing_file_returns_empty_store(tmp_path):
    from watchdog.state import load_state

    store = load_state(tmp_path / "no-such-state.json")

    assert store.jobs == {}


def test_save_and_load_roundtrip(tmp_path):
    from watchdog.state import StateStore, StoredJob, load_state, save_state

    store = StateStore(
        jobs={
            "job-a": StoredJob(T_STORED, 2),
            "job-b": StoredJob(None, 0),
        }
    )
    path = tmp_path / "state.json"

    save_state(path, store)

    assert load_state(path) == store


def test_save_writes_exact_json_layout(tmp_path):
    from watchdog.state import save_state

    path = tmp_path / "state.json"

    save_state(path, _store(consecutive_failures=2))

    assert path.read_text(encoding="utf-8") == (
        "{\n"
        '  "jobs": {\n'
        '    "job-a": {\n'
        '      "last_success_at": "2026-11-05T11:00:00+09:00",\n'
        '      "consecutive_failures": 2\n'
        "    }\n"
        "  }\n"
        "}"
    )
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "jobs": {
            "job-a": {
                "last_success_at": "2026-11-05T11:00:00+09:00",
                "consecutive_failures": 2,
            }
        }
    }


def test_save_creates_parent_directories(tmp_path):
    from watchdog.state import load_state, save_state

    path = tmp_path / "sub" / "dir" / "state.json"

    save_state(path, _store())

    assert load_state(path).jobs["job-a"].last_success_at == T_STORED


def test_load_ignores_unknown_extra_keys(tmp_path):
    from watchdog.state import load_state

    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "jobs": {
                    "job-a": {
                        "last_success_at": "2026-11-05T11:00:00+09:00",
                        "consecutive_failures": 1,
                        "extra": 9,
                    }
                },
                "other": 1,
            }
        ),
        encoding="utf-8",
    )

    store = load_state(path)

    assert store.jobs["job-a"].last_success_at == T_STORED
    assert store.jobs["job-a"].consecutive_failures == 1


@pytest.mark.parametrize(
    "content",
    [
        "",
        "{oops",
        json.dumps(
            {"jobs": {"job-a": {"last_success_at": "not-a-date",
                                 "consecutive_failures": 0}}}
        ),
    ],
)
def test_load_corrupt_state_raises_value_error(tmp_path, content):
    from watchdog.state import load_state

    path = tmp_path / "state.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError):
        load_state(path)


# --- merge_observations: 単調マージ -------------------------------------------


def test_merge_newer_observation_advances_last_success():
    from watchdog.state import merge_observations

    merged = merge_observations(_store(), [_job_state(T_NEW, 0)])

    assert merged.jobs["job-a"].last_success_at == T_NEW
    assert merged.jobs["job-a"].consecutive_failures == 0


def test_merge_older_observation_does_not_regress_last_success():
    """中核保証: 古い観測を流しても最終成功は後退しない。"""
    from watchdog.state import merge_observations

    merged = merge_observations(_store(), [_job_state(T_OLD, 5)])

    assert merged.jobs["job-a"].last_success_at == T_STORED


def test_merge_replaces_consecutive_failures_even_when_older():
    """連続失敗回数は単調ではなく、最新の観測値で常に置き換わる。"""
    from watchdog.state import merge_observations

    merged = merge_observations(_store(), [_job_state(T_OLD, 5)])

    assert merged.jobs["job-a"].consecutive_failures == 5


def test_merge_none_observation_keeps_stored_last_success():
    from watchdog.state import merge_observations

    merged = merge_observations(_store(), [_job_state(None, 7)])

    assert merged.jobs["job-a"].last_success_at == T_STORED
    assert merged.jobs["job-a"].consecutive_failures == 7


def test_merge_adds_previously_unseen_job():
    from watchdog.state import StateStore, merge_observations

    merged = merge_observations(
        StateStore(), [_job_state(T_NEW, 2)]
    )

    assert merged.jobs["job-a"].last_success_at == T_NEW
    assert merged.jobs["job-a"].consecutive_failures == 2


def test_merge_records_none_last_success_for_new_job():
    from watchdog.state import StateStore, merge_observations

    merged = merge_observations(StateStore(), [_job_state(None, 4)])

    assert merged.jobs["job-a"].last_success_at is None
    assert merged.jobs["job-a"].consecutive_failures == 4


# --- apply_store: 判定への反映 -------------------------------------------------


def test_apply_store_upgrades_last_success_from_newer_store():
    from watchdog.state import apply_store

    (state,) = apply_store(_store(consecutive_failures=9), [_job_state(T_OLD, 1)])

    assert state.last_success_at == T_STORED


def test_apply_store_keeps_observed_failures_not_stored():
    from watchdog.state import apply_store

    (state,) = apply_store(_store(consecutive_failures=9), [_job_state(T_OLD, 1)])

    assert state.consecutive_failures == 1


def test_apply_store_keeps_observation_when_store_is_older():
    from watchdog.state import apply_store

    (state,) = apply_store(_store(last_success_at=T_OLD), [_job_state(T_NEW, 1)])

    assert state.last_success_at == T_NEW


def test_apply_store_without_entry_leaves_state_unchanged():
    from watchdog.state import StateStore, apply_store

    observed = _job_state(T_NEW, 3, running=True, evidence_available=False)

    (state,) = apply_store(StateStore(), [observed])

    assert state.last_success_at == T_NEW
    assert state.consecutive_failures == 3
    assert state.running is True
    assert state.evidence_available is False
