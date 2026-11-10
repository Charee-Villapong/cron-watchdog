"""CLI `check` の差分検知の統合テスト。

`--cron-roots` で与えた cron 定義の投影ツリーと定義表を突き合わせた
結果（一致／未登録／消滅）が、チェックの記録であるハートビート
JSONL に残ることを固定する。差分は検知のみで、通知の判定
（shadow の抑制を含む）には影響しないこともあわせて固定する。

``watchdog`` はサブプロセスで実行し、生成ファイルだけから検証する。
すべて架空データ・tmp_path 配下で実行し、実データには触れない。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "fixtures"
NOW = "2026-11-05T12:00:00+09:00"


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "watchdog", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def write_cron_file(root, *parts, job_id, kind, enabled=True):
    path = root.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"id: {job_id}\n"
        f"enabled: {'true' if enabled else 'false'}\n"
        "schedule:\n"
        f"  kind: {kind}\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )
    return path


def run_check_with_roots(tmp_path: Path, cron_root: Path):
    data_dir = tmp_path / "data"
    result = run_cli(
        "check",
        "--definitions",
        str(FIXTURES_DIR / "definitions.json"),
        "--snapshot",
        str(FIXTURES_DIR / "snapshot.json"),
        "--state",
        str(tmp_path / "state.json"),
        "--data-dir",
        str(data_dir),
        "--now",
        NOW,
        "--cron-roots",
        str(cron_root),
    )
    records = [
        json.loads(line)
        for line in (data_dir / "watchdog-heartbeat.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    outbox = [
        json.loads(line)
        for line in (data_dir / "outbox" / "notifications.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    return result, records[-1], outbox[-1]


def test_check_records_definition_diff_in_heartbeat(tmp_path):
    cron_root = tmp_path / "crons"
    write_cron_file(
        cron_root,
        "daily",
        "watchdog-selftest-fresh__daily@07:00:00.md",
        job_id="watchdog-selftest-fresh",
        kind="daily",
    )
    write_cron_file(
        cron_root,
        "weekly",
        "extra-job__weekly@Mon-09:00:00.md",
        job_id="extra-job",
        kind="weekly",
    )
    write_cron_file(
        cron_root,
        "runonce",
        "job-once__runonce@2026-11-06T12:00:00.md",
        job_id="job-once",
        kind="runonce",
    )

    result, record, _outbox = run_check_with_roots(tmp_path, cron_root)

    assert result.returncode == 0
    assert record["definition_diff"] == {
        "matched": ["watchdog-selftest-fresh"],
        "unregistered": ["extra-job"],
        "missing": ["watchdog-selftest-overdue"],
    }
    assert "unregistered=['extra-job']" in result.stderr
    assert "missing=['watchdog-selftest-overdue']" in result.stderr


def test_check_diff_does_not_trigger_notification_in_shadow(tmp_path):
    cron_root = tmp_path / "crons"
    write_cron_file(
        cron_root,
        "weekly",
        "extra-job__weekly@Mon-09:00:00.md",
        job_id="extra-job",
        kind="weekly",
    )

    _result, _record, outbox = run_check_with_roots(tmp_path, cron_root)

    # 差分があっても shadow の間は通知しない（検知のみ）。
    assert outbox["would_notify"] is False
    assert outbox["detections"] == ["watchdog-selftest-overdue"]


def test_check_diff_is_null_when_no_cron_files_found(tmp_path):
    cron_root = tmp_path / "empty-roots"
    cron_root.mkdir()

    result, record, _outbox = run_check_with_roots(tmp_path, cron_root)

    # 実在一覧が1件も取れない場合は誤検知を避け、差分を記録しない。
    assert result.returncode == 0
    assert record["definition_diff"] is None
