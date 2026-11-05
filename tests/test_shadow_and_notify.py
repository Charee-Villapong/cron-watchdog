"""シャドーモードと正常時通知（必須要件5、完了の定義3項目目）.

- シャドー期間中は検出しても通知しない。
- 正常な週は「異常なし」以外の通知が本人の負担にならない。
"""

from __future__ import annotations

from datetime import timedelta

from conftest import make_definition


def _rows(sample_definition_rows, now, *, overdue: bool):
    from watchdog.definitions import load_definitions
    from watchdog.ledger import JobState, build_ledger_row

    definitions = load_definitions(sample_definition_rows)
    rows = []
    for i, definition in enumerate(definitions):
        if overdue and i == 0:
            last_success = now - timedelta(days=3)  # 1件だけ止める
        else:
            last_success = now - timedelta(hours=1)
        rows.append(
            build_ledger_row(
                JobState(definition=definition, last_success_at=last_success),
                now,
            )
        )
    return rows


def _assert_notification_suppressed(payload):
    """None（生成されない）か、抑止が明示されていること。"""
    if payload is None:
        return
    assert payload.should_notify is False
    assert payload.suppressed_reason is not None
    assert "shadow" in payload.suppressed_reason.lower()


def test_shadow_mode_suppresses_notification_even_with_detections(
    sample_definition_rows, now
):
    from watchdog.notify import build_notification

    rows = _rows(sample_definition_rows, now, overdue=True)

    payload = build_notification(rows, shadow_mode=True)

    _assert_notification_suppressed(payload)


def test_non_shadow_mode_notifies_about_overdue_detection(
    sample_definition_rows, now
):
    from watchdog.notify import build_notification

    rows = _rows(sample_definition_rows, now, overdue=True)

    payload = build_notification(rows, shadow_mode=False)

    assert payload is not None
    assert payload.should_notify is True
    assert "daily-fortune" in payload.text


def test_normal_week_notification_is_only_no_anomaly(
    sample_definition_rows, now
):
    """異常なしの週: 通知が生成されるなら本文は「異常なし」相当のみ。"""
    from watchdog.notify import build_notification

    rows = _rows(sample_definition_rows, now, overdue=False)

    payload = build_notification(rows, shadow_mode=False)

    if payload is None:
        return  # 正常時に何も生成しない実装も「負担にならない」を満たす
    assert "異常なし" in payload.text
    assert "期限超過" not in payload.text
    for name in ("daily-fortune", "weekly-cleanup", "threads-collection"):
        assert name not in payload.text


def test_shadow_mode_with_no_detections_also_sends_nothing(
    sample_definition_rows, now
):
    from watchdog.notify import build_notification

    rows = _rows(sample_definition_rows, now, overdue=False)

    payload = build_notification(rows, shadow_mode=True)

    _assert_notification_suppressed(payload)


def test_non_shadow_payload_records_detections(
    sample_definition_rows, now
):
    """報告用に、検出内容そのものはペイロードに保持される。"""
    from watchdog.notify import build_notification

    rows = _rows(sample_definition_rows, now, overdue=True)

    payload = build_notification(rows, shadow_mode=False)

    assert payload is not None
    assert [row.name for row in payload.detections] == ["daily-fortune"]
