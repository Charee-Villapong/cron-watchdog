"""Regression tests: credentials with spaces leaked through masking.

Verified failures (2026-11-18 review): the key/value rule consumed
only the first whitespace-delimited token, so

- ``Authorization: Basic abc123`` kept ``abc123`` in plain text
  (only the scheme word was masked), and
- ``password: "abc def"`` kept the second word of the quoted value.

Test data is fictional throughout.
"""

from __future__ import annotations


def test_mask_basic_authorization_masks_the_credential():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive("Authorization: Basic abc123")

    assert result == "Authorization=[masked]"
    assert "abc123" not in result


def test_mask_basic_authorization_with_base64_credential():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive("failed: Authorization: Basic dXNlcjpwYXNz end")

    assert "dXNlcjpwYXNz" not in result
    assert "Authorization=[masked]" in result


def test_mask_bearer_authorization_still_fully_masked():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive("Authorization: Bearer FAKEtoken1234567890")

    assert "FAKEtoken1234567890" not in result
    assert "[masked]" in result


def test_mask_double_quoted_password_with_space():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive('password: "abc def" rest')

    assert result == "password=[masked] rest"
    assert "abc" not in result
    assert "def" not in result


def test_mask_single_quoted_secret_with_space():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive("secret: 'abc def' rest")

    assert result == "secret=[masked] rest"


def test_mask_quoted_token_assignment():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive('token="abc def" rest')

    assert result == "token=[masked] rest"
