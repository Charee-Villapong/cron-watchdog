"""CLI `check` の現状固定テスト（特性テスト）: 期限超過の抽出まわり.

リファクタリング候補 C-041（期限超過（FAILURE）抽出処理の三重重複の
共通化）の前提として、無テストだった CLI 側の現行挙動を固定する。
あわせて候補1の所見（`_cmd_check` の現状固定）として、終了コードの
3値（0=正常 / 2=一部が判定不能 / 1=実行自体の失敗）・状態保存・
ハートビート／outbox 追記内容を、既存 fixtures のシナリオで固定する。

テスト係が実装モジュール本体を読まず、CLI をブラックボックスとして
実行した観測結果（標準出力・終了コード・生成ファイル）だけから書いた。
``watchdog`` はテストプロセスでは import せず、サブプロセスで叩く。
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "fixtures"
NOW = "2026-11-05T12:00:00+09:00"

SELFTEST_ROWS = [
    {
        "name": "watchdog-selftest-overdue",
        "period": "1d",
        "last_success_at": "2026-11-02T00:05:00+09:00",
        "consecutive_failures": 0,
        "next_due_at": "2026-11-03T00:05:00+09:00",
        "status": "失敗",
    },
    {
        "name": "watchdog-selftest-fresh",
        "period": "1d",
        "last_success_at": "2026-11-05T11:00:00+09:00",
        "consecutive_failures": 0,
        "next_due_at": "2026-11-06T11:00:00+09:00",
        "status": "成功",
    },
]


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "watchdog", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def run_check(tmp_path: Path, **kwargs) -> tuple[subprocess.CompletedProcess, dict]:
    """`check` を tmp_path 配下のパスで実行し、(結果, パス辞書) を返す。"""
    paths = {
        "definitions": kwargs.get("definitions", FIXTURES_DIR / "definitions.json"),
        "snapshot": kwargs.get("snapshot", FIXTURES_DIR / "snapshot.json"),
        "state": tmp_path / "state.json",
        "data_dir": tmp_path / "data",
    }
    args = [
        "check",
        "--definitions",
        str(paths["definitions"]),
        "--snapshot",
        str(paths["snapshot"]),
        "--state",
        str(paths["state"]),
        "--data-dir",
        str(paths["data_dir"]),
    ]
    if kwargs.get("now", NOW) is not None:
        args += ["--now", kwargs.get("now", NOW)]
    args += list(kwargs.get("extra_args", ()))
    return run_cli(*args), paths


def write_json(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def definition_row(name: str, **overrides):
    row = {
        "name": name,
        "evidence_type": "log_success",
        "period": "1d",
        "tolerance_seconds": 7200,
        "timezone": "Asia/Tokyo",
    }
    row.update(overrides)
    return row


def snapshot_with(targets: dict, collect_errors: dict | None = None):
    return {
        "collected_at": NOW,
        "collector": "characterization-test",
        "collect_errors": collect_errors or {},
        "targets": targets,
    }


def target_entry(last_success_at, **status_overrides):
    status = {
        "consecutive_failures": 0,
        "enabled": True,
        "in_flight": False,
        "last_run_at": last_success_at,
        "last_status": "succeeded" if last_success_at else None,
        "last_success_at": last_success_at,
        "next_run_at": None,
        "resolved_timezone": "Asia/Tokyo",
    }
    status.update(status_overrides)
    return {"status": status, "runs": []}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def heartbeat_records(paths: dict) -> list:
    return read_jsonl(paths["data_dir"] / "watchdog-heartbeat.jsonl")


def outbox_records(paths: dict) -> list:
    return read_jsonl(paths["data_dir"] / "outbox" / "notifications.jsonl")


# --- fixtures シナリオ（期限超過1件＋正常1件） -------------------------


def test_check_selftest_fixture_stdout_rows(tmp_path):
    """README の自己試験シナリオ: 期限超過だけが「失敗」で出力される。"""
    result, _ = run_check(tmp_path)

    assert result.returncode == 0
    assert json.loads(result.stdout) == SELFTEST_ROWS


def test_check_selftest_state_store_contents(tmp_path):
    """状態ストアには両対象の最終成功時刻がそのまま保存される。"""
    _, paths = run_check(tmp_path)

    assert read_json(paths["state"]) == {
        "jobs": {
            "watchdog-selftest-fresh": {
                "last_success_at": "2026-11-05T11:00:00+09:00",
                "consecutive_failures": 0,
            },
            "watchdog-selftest-overdue": {
                "last_success_at": "2026-11-02T00:05:00+09:00",
                "consecutive_failures": 0,
            },
        }
    }


def test_check_selftest_heartbeat_record(tmp_path):
    """ハートビート（JSONL）: anomalies は期限超過の対象名だけ。"""
    _, paths = run_check(tmp_path)

    (record,) = heartbeat_records(paths)
    assert record["mode"] == "check"
    assert record["result"] == "ok"
    assert record["targets_checked"] == 2
    assert record["anomalies"] == ["watchdog-selftest-overdue"]
    assert record["started_at"] == NOW
    assert record["finished_at"] == NOW
    assert record["snapshot"] == str(FIXTURES_DIR / "snapshot.json")
    uuid.UUID(record["run_id"])  # 値は固定しない（形式だけ確認）


def test_check_selftest_last_run_and_outbox_shadow(tmp_path):
    """last-run と outbox: シャドー既定では抑止理由つきの下書きになる。"""
    _, paths = run_check(tmp_path)

    last_run = (paths["data_dir"] / "last-run.txt").read_text(encoding="utf-8")
    assert last_run == NOW + "\n"

    (entry,) = outbox_records(paths)
    assert entry == {
        "at": NOW,
        "would_notify": False,
        "suppressed_reason": "shadow mode: notifications suppressed",
        "text": "期限超過を検出しました（シャドー中につき未送信）: "
        "watchdog-selftest-overdue",
        "detections": ["watchdog-selftest-overdue"],
    }


def test_check_selftest_stderr_summary(tmp_path):
    result, paths = run_check(tmp_path)

    assert "checked=2" in result.stderr
    assert "overdue=['watchdog-selftest-overdue']" in result.stderr
    assert "unknown=[]" in result.stderr
    assert "notify_enabled=False" in result.stderr


# --- 終了コード3値 -------------------------------------------------------


def test_check_exit_code_zero_when_no_anomalies(tmp_path):
    """全件正常なら終了コード0、ハートビート result=ok、異常なし文面。"""
    definitions = write_json(
        tmp_path / "definitions.json",
        {"definitions": [definition_row("job-a")]},
    )
    snapshot = write_json(
        tmp_path / "snapshot.json",
        snapshot_with(
            {
                "job-a": target_entry(
                    "2026-11-05T11:00:00+09:00",
                    next_run_at="2026-11-06T11:00:00+09:00",
                )
            }
        ),
    )

    result, paths = run_check(
        tmp_path, definitions=definitions, snapshot=snapshot
    )

    assert result.returncode == 0
    (row,) = json.loads(result.stdout)
    assert row["status"] == "成功"
    (record,) = heartbeat_records(paths)
    assert record["result"] == "ok"
    assert record["anomalies"] == []
    (entry,) = outbox_records(paths)
    assert entry["detections"] == []
    assert entry["text"] == "異常なし（シャドー中につき未送信）"


def test_check_exit_code_two_when_unknown_present(tmp_path):
    """判定不能が混ざると終了コード2、ハートビート result=partial。

    判定不能の対象は anomalies / detections には入らない（現行挙動）。
    """
    definitions = write_json(
        tmp_path / "definitions.json",
        {"definitions": [definition_row("job-a"), definition_row("job-b")]},
    )
    snapshot = write_json(
        tmp_path / "snapshot.json",
        snapshot_with(
            {
                "job-a": target_entry(
                    "2026-11-05T11:00:00+09:00",
                    next_run_at="2026-11-06T11:00:00+09:00",
                )
            },
            collect_errors={"job-b": "SOURCE_MISSING"},
        ),
    )

    result, paths = run_check(
        tmp_path, definitions=definitions, snapshot=snapshot
    )

    assert result.returncode == 2
    rows = {row["name"]: row for row in json.loads(result.stdout)}
    assert rows["job-a"]["status"] == "成功"
    assert rows["job-b"]["status"] == "判定不能"
    assert rows["job-b"]["last_success_at"] is None
    assert rows["job-b"]["next_due_at"] is None
    (record,) = heartbeat_records(paths)
    assert record["result"] == "partial"
    assert record["anomalies"] == []
    (entry,) = outbox_records(paths)
    assert entry["detections"] == []


def test_check_exit_code_two_when_overdue_and_unknown(tmp_path):
    """期限超過と判定不能が同時でも終了コード2（失敗の1ではない）。"""
    definitions = write_json(
        tmp_path / "definitions.json",
        {
            "definitions": [
                definition_row("job-old", tolerance_seconds=1800),
                definition_row("job-b"),
            ]
        },
    )
    snapshot = write_json(
        tmp_path / "snapshot.json",
        snapshot_with(
            {
                "job-old": target_entry(
                    "2026-11-02T00:05:00+09:00",
                    next_run_at="2026-11-03T00:05:00+09:00",
                )
            },
            collect_errors={"job-b": "SOURCE_MISSING"},
        ),
    )

    result, paths = run_check(
        tmp_path, definitions=definitions, snapshot=snapshot
    )

    assert result.returncode == 2
    rows = {row["name"]: row["status"] for row in json.loads(result.stdout)}
    assert rows == {"job-old": "失敗", "job-b": "判定不能"}
    (record,) = heartbeat_records(paths)
    assert record["result"] == "partial"
    assert record["anomalies"] == ["job-old"]
    (entry,) = outbox_records(paths)
    assert entry["detections"] == ["job-old"]


def test_check_exit_code_one_when_definitions_missing(tmp_path):
    """定義表が読めない場合は終了コード1で、ファイルは何も作られない。"""
    result, paths = run_check(
        tmp_path, definitions=tmp_path / "no-such-definitions.json"
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "[watchdog] error:" in result.stderr
    assert not paths["state"].exists()
    assert not paths["data_dir"].exists()


def test_check_exit_code_one_when_snapshot_missing(tmp_path):
    """スナップショットが読めない場合も終了コード1で副作用なし。"""
    result, paths = run_check(
        tmp_path, snapshot=tmp_path / "no-such-snapshot.json"
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "cannot read snapshot" in result.stderr
    assert not paths["state"].exists()
    assert not paths["data_dir"].exists()


# --- 期限超過抽出の境界 ---------------------------------------------------


def test_check_running_and_not_run_are_not_anomalies(tmp_path):
    """実行中・未実行は期限超過として抽出されず、終了コードも0のまま。"""
    definitions = write_json(
        tmp_path / "definitions.json",
        {
            "definitions": [
                definition_row("job-running"),
                definition_row("job-never"),
            ]
        },
    )
    snapshot = write_json(
        tmp_path / "snapshot.json",
        snapshot_with(
            {
                "job-running": target_entry(
                    "2026-11-02T00:05:00+09:00",
                    in_flight=True,
                    next_run_at="2026-11-03T00:05:00+09:00",
                ),
                "job-never": target_entry(None),
            }
        ),
    )

    result, paths = run_check(
        tmp_path, definitions=definitions, snapshot=snapshot
    )

    assert result.returncode == 0
    rows = {row["name"]: row["status"] for row in json.loads(result.stdout)}
    assert rows == {"job-running": "実行中", "job-never": "未実行"}
    (record,) = heartbeat_records(paths)
    assert record["anomalies"] == []
    (entry,) = outbox_records(paths)
    assert entry["detections"] == []


def test_check_nonshadow_outbox_records_overdue_detection(tmp_path):
    """通知有効時は outbox の would_notify が立ち、文面が通常形になる。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "notify-flag.json").write_text(
        json.dumps({"notify": True, "mode": "weekly_plus_anomaly"}),
        encoding="utf-8",
    )

    result, paths = run_check(tmp_path)

    assert result.returncode == 0
    assert "notify_enabled=True" in result.stderr
    (entry,) = outbox_records(paths)
    assert entry == {
        "at": NOW,
        "would_notify": True,
        "suppressed_reason": None,
        "text": "期限超過を検出しました:\n- watchdog-selftest-overdue (周期 1d)",
        "detections": ["watchdog-selftest-overdue"],
    }
    (record,) = heartbeat_records(paths)
    assert record["anomalies"] == ["watchdog-selftest-overdue"]


def test_check_appends_heartbeat_and_outbox_on_repeat(tmp_path):
    """再実行ではハートビート／outbox が追記され、last-run は最新になる。"""
    later = "2026-11-05T13:00:00+09:00"

    first, paths = run_check(tmp_path)
    second, _ = run_check(tmp_path, now=later)

    assert first.returncode == second.returncode == 0
    records = heartbeat_records(paths)
    assert [r["started_at"] for r in records] == [NOW, later]
    assert records[0]["run_id"] != records[1]["run_id"]
    assert all(r["anomalies"] == ["watchdog-selftest-overdue"] for r in records)
    entries = outbox_records(paths)
    assert [e["at"] for e in entries] == [NOW, later]
    last_run = (paths["data_dir"] / "last-run.txt").read_text(encoding="utf-8")
    assert last_run == later + "\n"


def test_check_state_does_not_regress_on_older_snapshot(tmp_path):
    """古いスナップショットを後から流しても状態の最終成功は後退しない。

    2回目の標準出力行も、保存済みの新しい最終成功で判定される。
    """
    _, paths = run_check(tmp_path)
    older_snapshot = read_json(FIXTURES_DIR / "snapshot.json")
    fresh = older_snapshot["targets"]["watchdog-selftest-fresh"]
    fresh["status"]["last_success_at"] = "2026-11-01T11:00:00+09:00"
    fresh["status"]["last_run_at"] = "2026-11-01T11:00:00+09:00"
    snapshot = write_json(tmp_path / "older-snapshot.json", older_snapshot)

    result, _ = run_check(tmp_path, snapshot=snapshot)

    assert result.returncode == 0
    assert json.loads(result.stdout) == SELFTEST_ROWS
    state = read_json(paths["state"])
    assert (
        state["jobs"]["watchdog-selftest-fresh"]["last_success_at"]
        == "2026-11-05T11:00:00+09:00"
    )
