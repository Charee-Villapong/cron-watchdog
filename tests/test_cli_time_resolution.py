"""CLI の時刻解決・タイムゾーンの現状固定テスト（特性テスト）.

リファクタリング候補 C-042（現在時刻の解決処理とタイムゾーン文字列の
重複直書きの共通化＋定数化）の前提として、`check` と `heartbeat` の
時刻まわりの現行挙動を固定する。

固定の方法（時刻注入の仕組み）:
- 両サブコマンドとも `--now` 引数で ISO 8601 文字列を注入できる。
  これを使い、表示・保存される時刻文字列をそのまま固定する。
- `--now` 省略時は実行時刻そのものは固定できないため、実行時刻に
  依存しない範囲だけを固定する: 既定オフセットが +09:00
  （Asia/Tokyo）であること、環境変数 TZ に影響されないこと、
  check の3つの記録（last-run／heartbeat JSONL／outbox）の時刻が
  互いに一致すること。

観測で判明した現行の非対称も、そのまま固定する（直さない）:
- `check` はオフセット無し（naive）の `--now` を付けると比較に失敗して
  終了コード1になるが、`heartbeat` は naive のまま保存して正常終了する。
- `Z` サフィックスは両者とも `+00:00` 表記へ正規化される。
- `--now` に与えたオフセットは変換されず、そのまま保存される
  （例: +00:00 のまま。Asia/Tokyo へは寄せられない）。

テスト係が実装モジュール本体を読まず、CLI をブラックボックスとして
実行した観測結果だけから書いた。``watchdog`` は import しない。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "fixtures"
TOKYO_NOW = "2026-11-05T12:00:00+09:00"
UTC_SAME_INSTANT = "2026-11-05T03:00:00+00:00"  # TOKYO_NOW と同一瞬間
TOKYO_OFFSET = timedelta(hours=9)


def run_cli(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "watchdog", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def run_check(tmp_path: Path, *extra: str, env: dict | None = None):
    data_dir = tmp_path / "data"
    args = [
        "check",
        "--definitions",
        str(FIXTURES_DIR / "definitions.json"),
        "--snapshot",
        str(FIXTURES_DIR / "snapshot.json"),
        "--state",
        str(tmp_path / "state.json"),
        "--data-dir",
        str(data_dir),
        *extra,
    ]
    return run_cli(*args, env=env), data_dir


def run_heartbeat(tmp_path: Path, *extra: str, env: dict | None = None):
    data_dir = tmp_path / "data"
    args = ["heartbeat", "--data-dir", str(data_dir), *extra]
    return run_cli(*args, env=env), data_dir


def recorded_times(data_dir: Path) -> dict:
    """check が残す3つの時刻記録を読み出す。"""
    heartbeat = json.loads(
        (data_dir / "watchdog-heartbeat.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    outbox = json.loads(
        (data_dir / "outbox" / "notifications.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    return {
        "last_run": (data_dir / "last-run.txt").read_text(encoding="utf-8").strip(),
        "heartbeat_started": heartbeat["started_at"],
        "heartbeat_finished": heartbeat["finished_at"],
        "outbox_at": outbox["at"],
    }


# --- check: --now 注入時の解決結果 ---------------------------------------


def test_check_now_tokyo_offset_is_used_verbatim_everywhere(tmp_path):
    result, data_dir = run_check(tmp_path, "--now", TOKYO_NOW)

    assert result.returncode == 0
    assert recorded_times(data_dir) == {
        "last_run": TOKYO_NOW,
        "heartbeat_started": TOKYO_NOW,
        "heartbeat_finished": TOKYO_NOW,
        "outbox_at": TOKYO_NOW,
    }


def test_check_now_utc_offset_is_preserved_not_converted(tmp_path):
    """同じ瞬間を UTC で与えても、記録は +00:00 のまま（東京へ寄せない）。

    判定結果（標準出力の台帳行）は同一瞬間なので東京指定時と一致する。
    """
    tokyo_result, _ = run_check(tmp_path / "tokyo", "--now", TOKYO_NOW)
    utc_result, utc_data = run_check(tmp_path / "utc", "--now", UTC_SAME_INSTANT)

    assert utc_result.returncode == 0
    assert utc_result.stdout == tokyo_result.stdout
    times = recorded_times(utc_data)
    assert set(times.values()) == {UTC_SAME_INSTANT}


def test_check_now_z_suffix_is_normalized_to_utc_offset(tmp_path):
    result, data_dir = run_check(tmp_path, "--now", "2026-11-05T03:00:00Z")

    assert result.returncode == 0
    assert recorded_times(data_dir)["last_run"] == UTC_SAME_INSTANT


def test_check_naive_now_fails_with_exit_one_and_no_side_effects(tmp_path):
    """オフセット無しの --now は比較エラーのため終了コード1、副作用なし。"""
    result, data_dir = run_check(tmp_path, "--now", "2026-11-05T12:00:00")

    assert result.returncode == 1
    assert result.stdout == ""
    assert "offset-naive" in result.stderr
    assert not (tmp_path / "state.json").exists()
    assert not data_dir.exists()


def test_check_invalid_now_fails_with_exit_one(tmp_path):
    result, data_dir = run_check(tmp_path, "--now", "not-a-date")

    assert result.returncode == 1
    assert result.stdout == ""
    assert "Invalid isoformat string: 'not-a-date'" in result.stderr
    assert not data_dir.exists()


# --- check: --now 省略時の既定（実行時刻に依存しない範囲） ----------------


def test_check_without_now_defaults_to_tokyo_offset(tmp_path):
    result, data_dir = run_check(tmp_path)

    assert result.returncode == 0
    times = recorded_times(data_dir)
    # 1回の実行で解決された単一の時刻が、3記録すべてに使われる
    assert len(set(times.values())) == 1
    parsed = datetime.fromisoformat(times["last_run"])
    assert parsed.utcoffset() == TOKYO_OFFSET
    assert times["last_run"].endswith("+09:00")


def test_check_without_now_ignores_tz_environment(tmp_path):
    """環境変数 TZ を変えても既定は +09:00 のまま（固定文字列の現行挙動）。"""
    for tz_name in ("UTC", "America/New_York"):
        env = dict(os.environ, TZ=tz_name)
        result, data_dir = run_check(
            tmp_path / tz_name.replace("/", "_"), env=env
        )

        assert result.returncode == 0
        last_run = recorded_times(data_dir)["last_run"]
        assert datetime.fromisoformat(last_run).utcoffset() == TOKYO_OFFSET
        assert last_run.endswith("+09:00")


# --- heartbeat: --now 注入時の解決結果 ------------------------------------


def test_heartbeat_now_tokyo_offset_written_verbatim(tmp_path):
    result, data_dir = run_heartbeat(tmp_path, "--now", TOKYO_NOW)

    assert result.returncode == 0
    last_run_path = data_dir / "last-run.txt"
    assert result.stdout == (
        f"heartbeat recorded: {last_run_path} {TOKYO_NOW}\n"
    )
    assert last_run_path.read_text(encoding="utf-8") == TOKYO_NOW + "\n"
    # heartbeat サブコマンドが作るのは last-run.txt だけ（JSONL は作らない）
    files = [p for p in data_dir.rglob("*") if p.is_file()]
    assert files == [last_run_path]


def test_heartbeat_now_z_suffix_is_normalized_to_utc_offset(tmp_path):
    result, data_dir = run_heartbeat(tmp_path, "--now", "2026-11-05T12:00:00Z")

    assert result.returncode == 0
    last_run = (data_dir / "last-run.txt").read_text(encoding="utf-8")
    assert last_run == "2026-11-05T12:00:00+00:00\n"


def test_heartbeat_naive_now_is_stored_without_offset(tmp_path):
    """check と違い、heartbeat は naive な --now をそのまま保存する。"""
    result, data_dir = run_heartbeat(tmp_path, "--now", "2026-11-05T12:00:00")

    assert result.returncode == 0
    last_run = (data_dir / "last-run.txt").read_text(encoding="utf-8")
    assert last_run == "2026-11-05T12:00:00\n"
    assert "2026-11-05T12:00:00" in result.stdout


def test_heartbeat_date_only_now_becomes_midnight_without_offset(tmp_path):
    result, data_dir = run_heartbeat(tmp_path, "--now", "2026-11-05")

    assert result.returncode == 0
    last_run = (data_dir / "last-run.txt").read_text(encoding="utf-8")
    assert last_run == "2026-11-05T00:00:00\n"


def test_heartbeat_invalid_now_fails_with_exit_one(tmp_path):
    result, data_dir = run_heartbeat(tmp_path, "--now", "not-a-date")

    assert result.returncode == 1
    assert result.stdout == ""
    assert "Invalid isoformat string: 'not-a-date'" in result.stderr
    assert not data_dir.exists()


def test_heartbeat_overwrites_last_run_on_repeat(tmp_path):
    later = "2026-11-05T13:00:00+09:00"
    run_heartbeat(tmp_path, "--now", TOKYO_NOW)

    result, data_dir = run_heartbeat(tmp_path, "--now", later)

    assert result.returncode == 0
    last_run = (data_dir / "last-run.txt").read_text(encoding="utf-8")
    assert last_run == later + "\n"


# --- heartbeat: --now 省略時の既定 ----------------------------------------


def test_heartbeat_without_now_defaults_to_tokyo_offset(tmp_path):
    result, data_dir = run_heartbeat(tmp_path)

    assert result.returncode == 0
    last_run = (data_dir / "last-run.txt").read_text(encoding="utf-8").strip()
    assert datetime.fromisoformat(last_run).utcoffset() == TOKYO_OFFSET
    assert last_run.endswith("+09:00")
    assert result.stdout.endswith(last_run + "\n")


def test_heartbeat_without_now_ignores_tz_environment(tmp_path):
    env = dict(os.environ, TZ="UTC")

    result, data_dir = run_heartbeat(tmp_path, env=env)

    assert result.returncode == 0
    last_run = (data_dir / "last-run.txt").read_text(encoding="utf-8").strip()
    assert datetime.fromisoformat(last_run).utcoffset() == TOKYO_OFFSET
