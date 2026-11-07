"""heartbeat の JSONL 版記録／読戻の現状固定テスト（特性テスト）: C-047.

リファクタリング候補 C-047 のうち `append_heartbeat_record` /
`read_heartbeat_records` を対象とする。単一ファイル版
（record_heartbeat / read_heartbeat）は test_heartbeat.py で
固定済みのため、ここでは CLI が使う JSONL 追記形式だけを固定する。
候補 C-047 の所見どおり、読戻側は現行の呼び出し元が CLI の
書き込み経路に限られるが、往復の形は安全網として固定しておく。

すべて tmp_path 配下で実行し、実データには触れない。
"""

from __future__ import annotations

import json

import pytest


def test_append_creates_file_with_one_json_line_per_record(tmp_path):
    from watchdog.heartbeat import append_heartbeat_record

    path = tmp_path / "watchdog-heartbeat.jsonl"

    append_heartbeat_record(path, {"mode": "check", "result": "ok"})
    append_heartbeat_record(path, {"mode": "check", "result": "partial"})

    assert path.read_text(encoding="utf-8") == (
        '{"mode": "check", "result": "ok"}\n'
        '{"mode": "check", "result": "partial"}\n'
    )


def test_append_creates_parent_directories(tmp_path):
    from watchdog.heartbeat import append_heartbeat_record

    path = tmp_path / "sub" / "dir" / "watchdog-heartbeat.jsonl"

    append_heartbeat_record(path, {"mode": "check"})

    assert path.exists()


def test_read_records_roundtrip_preserves_order_and_content(tmp_path):
    from watchdog.heartbeat import append_heartbeat_record, read_heartbeat_records

    path = tmp_path / "watchdog-heartbeat.jsonl"
    records = [
        {"mode": "check", "result": "ok", "targets_checked": 2},
        {"mode": "check", "result": "partial", "anomalies": ["job-a"]},
    ]
    for record in records:
        append_heartbeat_record(path, record)

    assert read_heartbeat_records(path) == records


def test_read_records_missing_file_returns_empty_list(tmp_path):
    from watchdog.heartbeat import read_heartbeat_records

    assert read_heartbeat_records(tmp_path / "no-such.jsonl") == []


def test_read_records_empty_file_returns_empty_list(tmp_path):
    from watchdog.heartbeat import read_heartbeat_records

    path = tmp_path / "watchdog-heartbeat.jsonl"
    path.write_text("", encoding="utf-8")

    assert read_heartbeat_records(path) == []


def test_read_records_skips_blank_lines(tmp_path):
    from watchdog.heartbeat import read_heartbeat_records

    path = tmp_path / "watchdog-heartbeat.jsonl"
    path.write_text('{"a": 1}\n\n{"b": 2}\n', encoding="utf-8")

    assert read_heartbeat_records(path) == [{"a": 1}, {"b": 2}]


def test_read_records_invalid_line_raises_value_error(tmp_path):
    from watchdog.heartbeat import read_heartbeat_records

    path = tmp_path / "watchdog-heartbeat.jsonl"
    path.write_text('{"a": 1}\nnot-json\n', encoding="utf-8")

    with pytest.raises(ValueError):  # json.JSONDecodeError は ValueError の子
        read_heartbeat_records(path)


def test_appended_lines_are_individually_valid_json(tmp_path):
    from watchdog.heartbeat import append_heartbeat_record

    path = tmp_path / "watchdog-heartbeat.jsonl"
    append_heartbeat_record(path, {"started_at": "2026-11-05T12:00:00+09:00"})

    (line,) = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(line) == {"started_at": "2026-11-05T12:00:00+09:00"}
