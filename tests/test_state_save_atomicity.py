"""Regression tests: save_state must not use a fixed temp file name.

Verified failure (2026-11-18 review): the temp file was always
``state.json.tmp``, so two watchdog runs saving the same state file
concurrently shared one temp path and could corrupt each other's
store. The save now goes through a unique ``mkstemp`` file.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
T_STORED = datetime(2026, 11, 5, 11, 0, tzinfo=JST)


def _store():
    from watchdog.state import StateStore, StoredJob

    return StateStore(jobs={"job-a": StoredJob(T_STORED, 2)})


def test_save_leaves_no_temp_file_behind(tmp_path):
    from watchdog.state import save_state

    path = tmp_path / "state.json"

    save_state(path, _store())

    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_save_does_not_touch_a_foreign_fixed_name_temp_file(tmp_path):
    """A pre-existing ``state.json.tmp`` (e.g. another run's) is left alone."""
    from watchdog.state import load_state, save_state

    path = tmp_path / "state.json"
    foreign = tmp_path / "state.json.tmp"
    foreign.write_text("someone else's temp", encoding="utf-8")

    save_state(path, _store())

    assert foreign.read_text(encoding="utf-8") == "someone else's temp"
    assert load_state(path).jobs["job-a"].last_success_at == T_STORED


def test_repeated_saves_keep_the_latest_content(tmp_path):
    from watchdog.state import StateStore, StoredJob, load_state, save_state

    path = tmp_path / "state.json"

    save_state(path, _store())
    save_state(path, StateStore(jobs={"job-a": StoredJob(T_STORED, 5)}))

    assert load_state(path).jobs["job-a"].consecutive_failures == 5
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]
