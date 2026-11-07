"""抜粋上限120の仕様テスト: C-048 (CW-10).

仕様（本人の決定 2026-11-07、docs/design.md §7.1 の B-7 と
docs/design-notes.md「マスキング上限」）:

- ``mask_sensitive`` の既定上限200は契約であり、変えない。
- 台帳・通知向け抜粋の上限120は定数
  ``watchdog.masking.EXCERPT_MAX_LENGTH`` として併存し、
  利用側は用途に応じて ``max_length`` に渡す。
- 抜粋の利用側である ``watchdog.snapshot.sanitized_snapshot_errors``
  は、現状この120をどこからも渡されていない。

変更前後の差（本ファイルが固定する変更後の仕様）:

- 変更前: ``sanitized_snapshot_errors`` が返す抜粋は既定の
  200文字で切り取られる（現行実装。既存の
  ``test_sanitized_errors_caps_long_text_at_200`` が固定）。
- 変更後: 同じ抜粋は120文字で切り取られる。120文字以下なら
  従来どおり全文が返る。マスキングの置換パターン自体は不変。

そのため、120文字超の入力を扱うテストは現行実装では落ちる
（レッド）のが期待結果であり、120文字以下の入力とマスキング
置換のテストは変更前後を通じて通る。

検証は公開API ``sanitized_snapshot_errors`` の振る舞いだけを
通じて行う。内部実装や定数を直接参照しない（仕様値「120」
そのものの assert は行う）。データはすべて架空。
"""

from __future__ import annotations

FAKE_EMAIL = "user123@example.invalid"
FAKE_BEARER = "Bearer FAKEtoken1234567890abcdef"


def _snapshot_with_error(error_text, target="job-a"):
    return {
        "targets": {target: {"runs": [{"status": "failed", "error_text": error_text}]}}
    }


def test_sanitized_errors_truncates_long_excerpt_to_120_chars():
    from watchdog.snapshot import sanitized_snapshot_errors

    error_text = "word " * 100  # マスク後も500文字で、120を大きく超える

    result = sanitized_snapshot_errors(_snapshot_with_error(error_text))

    assert len(result["job-a"]) == 120
    assert result["job-a"] == error_text[:120]


def test_sanitized_errors_truncates_masked_long_excerpt_to_120_chars():
    from watchdog.snapshot import sanitized_snapshot_errors

    error_text = f"failed for {FAKE_EMAIL} " + "word " * 100

    result = sanitized_snapshot_errors(_snapshot_with_error(error_text))

    assert len(result["job-a"]) == 120
    assert result["job-a"].startswith("failed for [masked-email] ")
    assert FAKE_EMAIL not in result["job-a"]


def test_sanitized_errors_keeps_short_excerpt_verbatim():
    from watchdog.snapshot import sanitized_snapshot_errors

    snapshot = _snapshot_with_error("first error")

    assert sanitized_snapshot_errors(snapshot) == {"job-a": "first error"}


def test_sanitized_errors_keeps_excerpt_at_exactly_120_chars():
    from watchdog.snapshot import sanitized_snapshot_errors

    error_text = "word " * 24  # ちょうど120文字

    result = sanitized_snapshot_errors(_snapshot_with_error(error_text))

    assert len(result["job-a"]) == 120
    assert result["job-a"] == error_text


def test_sanitized_errors_masks_email_and_bearer_within_excerpt():
    from watchdog.snapshot import sanitized_snapshot_errors

    snapshot = _snapshot_with_error(f"failed for {FAKE_EMAIL} with {FAKE_BEARER}")

    result = sanitized_snapshot_errors(snapshot)

    assert result == {"job-a": "failed for [masked-email] with Bearer [masked]"}
    assert FAKE_EMAIL not in result["job-a"]
    assert "FAKEtoken1234567890abcdef" not in result["job-a"]
    assert len(result["job-a"]) <= 120
