"""CLI の出力形式まわりの現状固定テスト（特性テスト）: C-046.

既存の test_cli_check_characterization.py が JSON 標準出力・終了コード・
状態保存・ハートビート／outbox を固定済みのため、本ファイルはその
未検証範囲だけを固定する（候補 C-046 の cli.py 残部、および候補5
「台帳行のシリアライズ定義の重複」の前提）:

- `--format csv` の標準出力文字列（ヘッダー順・None の空文字化を含む）
- `--out` ファイルへの書き出し（JSON 形式では標準出力と同一。
  CSV 形式でもファイル側は JSON になる、という現行の非対称を含む）
- `shadow-status` サブコマンドの出力（フラグ無し／false／true／
  壊れたフラグのいずれも終了コード0、壊れた場合はシャドー扱い）
- サブコマンド無し・不明なサブコマンドは argparse の終了コード2

CLI はブラックボックスとしてサブプロセス実行する。すべての書き込み先は
tmp_path 配下であり、実データディレクトリには触れない。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "fixtures"
NOW = "2026-11-05T12:00:00+09:00"

EXPECTED_CSV = (
    "name,period,last_success_at,consecutive_failures,next_due_at,status\n"
    "watchdog-selftest-overdue,1d,2026-11-02T00:05:00+09:00,0,"
    "2026-11-03T00:05:00+09:00,失敗\n"
    "watchdog-selftest-fresh,1d,2026-11-05T11:00:00+09:00,0,"
    "2026-11-06T11:00:00+09:00,成功\n"
)


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "watchdog", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def run_check(tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
    return run_cli(
        "check",
        "--definitions",
        str(FIXTURES_DIR / "definitions.json"),
        "--snapshot",
        str(FIXTURES_DIR / "snapshot.json"),
        "--state",
        str(tmp_path / "state.json"),
        "--data-dir",
        str(tmp_path / "data"),
        "--now",
        NOW,
        *extra,
    )


# --- CSV 形式 -----------------------------------------------------------------


def test_check_csv_stdout_exact_text(tmp_path):
    result = run_check(tmp_path, "--format", "csv")

    assert result.returncode == 0
    assert result.stdout == EXPECTED_CSV


def test_check_csv_none_fields_become_empty_strings(tmp_path):
    """最終成功・次回予定が無い行は、CSV では空文字になる（JSON では null）。"""
    definitions = tmp_path / "definitions.json"
    definitions.write_text(
        json.dumps(
            {
                "definitions": [
                    {
                        "name": "job-never",
                        "evidence_type": "log_success",
                        "period": "1d",
                        "tolerance_seconds": 7200,
                        "timezone": "Asia/Tokyo",
                    },
                    {
                        "name": "job-unknown",
                        "evidence_type": "log_success",
                        "period": "1d",
                        "tolerance_seconds": 7200,
                        "timezone": "Asia/Tokyo",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "collected_at": NOW,
                "collector": "characterization-test",
                "collect_errors": {"job-unknown": "SOURCE_MISSING"},
                "targets": {
                    "job-never": {
                        "status": {
                            "consecutive_failures": 0,
                            "enabled": True,
                            "in_flight": False,
                            "last_run_at": None,
                            "last_status": None,
                            "last_success_at": None,
                            "next_run_at": None,
                            "resolved_timezone": "Asia/Tokyo",
                        },
                        "runs": [],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "check",
        "--definitions",
        str(definitions),
        "--snapshot",
        str(snapshot),
        "--state",
        str(tmp_path / "state.json"),
        "--data-dir",
        str(tmp_path / "data"),
        "--format",
        "csv",
        "--now",
        NOW,
    )

    assert result.returncode == 2  # 判定不能を含むため partial
    assert result.stdout == (
        "name,period,last_success_at,consecutive_failures,next_due_at,status\n"
        "job-never,1d,,0,,未実行\n"
        "job-unknown,1d,,0,,判定不能\n"
    )


# --- --out ファイル -------------------------------------------------------------


def test_check_out_file_matches_stdout_in_json_format(tmp_path):
    out = tmp_path / "ledger.json"

    result = run_check(tmp_path, "--out", str(out))

    assert result.returncode == 0
    assert out.read_text(encoding="utf-8") == result.stdout
    assert json.loads(out.read_text(encoding="utf-8"))[0]["name"] == (
        "watchdog-selftest-overdue"
    )


def test_check_out_file_is_json_even_when_format_csv(tmp_path):
    """現行の非対称: --format csv でも --out ファイルの中身は JSON 形式。"""
    out = tmp_path / "ledger.out"
    csv_run_dir = tmp_path / "csv-run"
    csv_run_dir.mkdir()
    json_run_dir = tmp_path / "json-run"
    json_run_dir.mkdir()

    result = run_check(csv_run_dir, "--format", "csv", "--out", str(out))
    json_result = run_check(json_run_dir)

    assert result.returncode == 0
    assert result.stdout == EXPECTED_CSV
    file_text = out.read_text(encoding="utf-8")
    assert file_text == json_result.stdout
    assert json.loads(file_text)[0]["name"] == "watchdog-selftest-overdue"


# --- shadow-status --------------------------------------------------------------


def _shadow_status(tmp_path: Path, flag_content: str | None):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    if flag_content is not None:
        (data_dir / "notify-flag.json").write_text(
            flag_content, encoding="utf-8"
        )
    result = run_cli("shadow-status", "--data-dir", str(data_dir))
    return result, data_dir


def test_shadow_status_without_flag_file_reports_shadow(tmp_path):
    result, data_dir = _shadow_status(tmp_path, None)

    assert result.returncode == 0
    assert result.stdout == (
        f"notify-flag: {data_dir / 'notify-flag.json'}\n"
        "mode: shadow (notifications suppressed)\n"
    )


def test_shadow_status_with_notify_false_reports_shadow(tmp_path):
    result, _ = _shadow_status(
        tmp_path, json.dumps({"notify": False, "mode": "shadow"})
    )

    assert result.returncode == 0
    assert "mode: shadow (notifications suppressed)\n" in result.stdout


def test_shadow_status_with_notify_true_reports_enabled(tmp_path):
    result, data_dir = _shadow_status(
        tmp_path, json.dumps({"notify": True, "mode": "weekly_plus_anomaly"})
    )

    assert result.returncode == 0
    assert result.stdout == (
        f"notify-flag: {data_dir / 'notify-flag.json'}\n"
        "mode: notify enabled\n"
    )


def test_shadow_status_with_corrupt_flag_reports_shadow(tmp_path):
    result, _ = _shadow_status(tmp_path, "{oops")

    assert result.returncode == 0
    assert "mode: shadow (notifications suppressed)\n" in result.stdout


# --- 引数エラー -------------------------------------------------------------------


def test_no_subcommand_exits_with_code_two():
    result = run_cli()

    assert result.returncode == 2
    assert result.stdout == ""


def test_unknown_subcommand_exits_with_code_two():
    result = run_cli("bogus")

    assert result.returncode == 2
    assert result.stdout == ""


def test_check_without_required_args_exits_with_code_two():
    result = run_cli("check")

    assert result.returncode == 2
    assert result.stdout == ""
