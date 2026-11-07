"""notify.read_notify_flag の現状固定テスト（特性テスト）: C-047.

リファクタリング候補 C-047 のうち、通知フラグ読み取りを対象とする。
これは「通知しない側へ倒れる fail-safe」の要であり、設計の正は
README「シャドー運用と通知の有効化」: フラグが無い場合もシャドー
として扱い、通知を有効化できるのは `notify: true` の明示だけである。

実測した現行挙動: True を返すのは JSON の真の boolean true の
ときだけ。数値の 1 や文字列 "true" は有効化にならない。壊れた
JSON・空ファイルも例外ではなく False（シャドー）に倒れる。

すべて tmp_path 配下の架空ファイルで実行する。
"""

from __future__ import annotations

import json

import pytest


def _write(tmp_path, payload):
    path = tmp_path / "notify-flag.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_missing_flag_file_means_no_notify(tmp_path):
    from watchdog.notify import read_notify_flag

    assert read_notify_flag(tmp_path / "no-such-flag.json") is False


def test_notify_true_enables_notifications(tmp_path):
    from watchdog.notify import read_notify_flag

    path = _write(tmp_path, {"notify": True, "mode": "weekly_plus_anomaly"})

    assert read_notify_flag(path) is True


def test_notify_false_means_no_notify(tmp_path):
    from watchdog.notify import read_notify_flag

    path = _write(tmp_path, {"notify": False, "mode": "shadow"})

    assert read_notify_flag(path) is False


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"mode": "shadow"},
        {"notify": None},
        {"notify": 0},
    ],
)
def test_missing_or_null_notify_means_no_notify(tmp_path, payload):
    from watchdog.notify import read_notify_flag

    assert read_notify_flag(_write(tmp_path, payload)) is False


@pytest.mark.parametrize("value", [1, "true", "yes"])
def test_non_boolean_truthy_values_do_not_enable(tmp_path, value):
    """有効化は boolean true のみ。1 や "true" では通知側に倒れない。"""
    from watchdog.notify import read_notify_flag

    assert read_notify_flag(_write(tmp_path, {"notify": value})) is False


@pytest.mark.parametrize("content", ["", "{oops", "not json"])
def test_unreadable_flag_content_means_no_notify(tmp_path, content):
    from watchdog.notify import read_notify_flag

    assert read_notify_flag(_write(tmp_path, content)) is False
