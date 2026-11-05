"""エラー情報のマスキング（必須要件4）.

一次切り分けの情報は、エラー種別・発生時刻・該当ログの有無に絞り、
認証情報・個人情報を含みうる文字列は除去／切り捨てる。
ログ原文をそのまま転載しない。

テストデータはすべて架空（example.invalid ドメイン、FAKE を含む
トークン風文字列）であり、実在の個人情報は含まない。
"""

from __future__ import annotations

FAKE_EMAIL = "user123@example.invalid"
FAKE_BEARER = "Bearer FAKEtoken1234567890abcdef"
FAKE_API_KEY = "sk-FAKE1234567890abcdef1234567890"


def test_mask_removes_email_like_string():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive(f"failed for {FAKE_EMAIL} at step 3")

    assert FAKE_EMAIL not in result
    assert "example.invalid" not in result


def test_mask_removes_bearer_token_like_string():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive(f"auth error: {FAKE_BEARER}")

    assert "FAKEtoken1234567890abcdef" not in result


def test_mask_removes_api_key_like_string():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive(f"key={FAKE_API_KEY} rejected")

    assert FAKE_API_KEY not in result


def test_mask_removes_token_assignment():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive("token=FAKEsecretvalue123456 password=hunter2fake")

    assert "FAKEsecretvalue123456" not in result
    assert "hunter2fake" not in result


def test_mask_truncates_long_string():
    from watchdog.masking import mask_sensitive

    long_text = "x" * 5000

    result = mask_sensitive(long_text)

    assert len(result) <= 200
    assert result != long_text


def test_mask_respects_explicit_max_length():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive("y" * 500, max_length=50)

    assert len(result) <= 50


def test_mask_keeps_ordinary_short_text_readable():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive("connection timed out")

    assert "connection timed out" in result


def test_sanitize_error_preserves_type_time_and_log_flag(now):
    from watchdog.masking import sanitize_error

    sanitized = sanitize_error(
        f"Traceback ... failed for {FAKE_EMAIL} with {FAKE_BEARER}",
        error_type="TimeoutError",
        occurred_at=now,
        has_log=True,
    )

    assert sanitized.error_type == "TimeoutError"
    assert sanitized.occurred_at == now
    assert sanitized.has_log is True


def test_sanitize_error_message_is_masked_and_not_verbatim(now):
    from watchdog.masking import sanitize_error

    raw = f"Traceback ... failed for {FAKE_EMAIL} with {FAKE_BEARER} " + (
        "z" * 1000
    )

    sanitized = sanitize_error(
        raw, error_type="RuntimeError", occurred_at=now, has_log=False
    )

    assert sanitized.message != raw
    assert FAKE_EMAIL not in sanitized.message
    assert "FAKEtoken1234567890abcdef" not in sanitized.message
    assert len(sanitized.message) <= 200
    assert sanitized.has_log is False
