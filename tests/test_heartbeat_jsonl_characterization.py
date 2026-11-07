"""heartbeat の JSONL 版記録の現状固定テスト（特性テスト）: C-047 / C-048.

リファクタリング候補 C-047 のうち `append_heartbeat_record` を
対象とする。単一ファイル版（record_heartbeat / read_heartbeat）は
test_heartbeat.py で固定済みのため、ここでは CLI が使う JSONL
追記形式だけを固定する。

C-048（本人の決定）により `read_heartbeat_records` は削除される
ため、同関数を対象とするテスト／検証は本ファイルから取り除いた。
これは実装都合ではなく本人の決定（仕様）由来の変更である。
`append_heartbeat_record` のカバレッジは落とさず、書き込み結果は
ファイルを直接読んで JSON 行として検証する形に置き換えた。

すべて tmp_path 配下で実行し、実データには触れない。
"""

from __future__ import annotations

import json


def test_append_creates_file_with_one_json_line_per_record(tmp_path):
    from watchdog.heartbeat import append_heartbeat_record

    path = tmp_path / "watchdog-heartbeat.jsonl"

    append_heartbeat_record(path, {"mode": "check", "result": "ok"})
    append_heartbeat_record(path, {"mode": "check", "result": "partial"})

    assert path.read_text(encoding="utf-8") == (
        '{"mode": "check", "result": "ok"}\n' '{"mode": "check", "result": "partial"}\n'
    )


def test_append_creates_parent_directories(tmp_path):
    from watchdog.heartbeat import append_heartbeat_record

    path = tmp_path / "sub" / "dir" / "watchdog-heartbeat.jsonl"

    append_heartbeat_record(path, {"mode": "check"})

    assert path.exists()


def test_append_preserves_order_and_content_read_back_from_file(tmp_path):
    from watchdog.heartbeat import append_heartbeat_record

    path = tmp_path / "watchdog-heartbeat.jsonl"
    records = [
        {"mode": "check", "result": "ok", "targets_checked": 2},
        {"mode": "check", "result": "partial", "anomalies": ["job-a"]},
    ]
    for record in records:
        append_heartbeat_record(path, record)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == records


def test_appended_lines_are_individually_valid_json(tmp_path):
    from watchdog.heartbeat import append_heartbeat_record

    path = tmp_path / "watchdog-heartbeat.jsonl"
    append_heartbeat_record(path, {"started_at": "2026-11-05T12:00:00+09:00"})

    (line,) = path.read_text(encoding="utf-8").splitlines()
    assert json.loads(line) == {"started_at": "2026-11-05T12:00:00+09:00"}
