"""masking の未検証だった置換規則の現状固定テスト（特性テスト）: C-047.

リファクタリング候補 C-047 のうち masking.py の置換規則の未検証分を
対象とする。規則の正は docs/design.md §7.2 の表。メール／Bearer／
APIキー風／token= 形式と切り捨ては test_masking.py で固定済みの
ため、ここでは残りの種別だけを実測した現行挙動で固定する:

- UUID 形式・長い英数字列 -> [masked-id]
- 電話番号形式 -> [masked-number]
- URL のクエリ文字列の除去（スキーム＋ホスト＋パスは残る）
- ホームディレクトリ配下の絶対パス -> ~/...（ユーザー名を出さない）
- 秘密系キーワードの「キー: 値」形式（= 形式は既存テスト側）
- 制御文字・改行の1行化
- 切り捨てはちょうど上限文字数で、末尾への "…" 付加はない
  （§7.2 の記述と実装が食い違う点。現行挙動をそのまま固定する）

テストデータはすべて架空。
"""

from __future__ import annotations

FAKE_UUID = "123e4567-e89b-12d3-a456-426614174000"


def test_mask_replaces_uuid_with_masked_id():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive(f"failed id {FAKE_UUID} done")

    assert result == "failed id [masked-id] done"


def test_mask_replaces_long_alphanumeric_token_with_masked_id():
    from watchdog.masking import mask_sensitive

    token = "abcdefghijklmnopqrstuvwx"  # 24文字の英数文字列

    result = mask_sensitive(f"tok {token} done")

    assert token not in result
    assert "[masked-id]" in result


def test_mask_replaces_long_hex_string_with_masked_id():
    from watchdog.masking import mask_sensitive

    digest = "abcdef0123456789" * 2  # 32文字の16進文字列

    result = mask_sensitive(f"hash {digest} done")

    assert result == "hash [masked-id] done"


def test_mask_keeps_short_alphanumeric_word():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive("tok abcdefghij done")

    assert "abcdefghij" in result


def test_mask_replaces_mobile_phone_number():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive("call 090-1234-5678 now")

    assert result == "call [masked-number] now"


def test_mask_replaces_landline_phone_number():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive("call 03-1234-5678 now")

    assert result == "call [masked-number] now"


def test_mask_strips_url_query_string():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive(
        "see https://example.com/path/page?token=abc123&x=1 end"
    )

    assert result == "see https://example.com/path/page end"


def test_mask_keeps_url_without_query_unchanged():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive("see https://example.com/path/page end")

    assert result == "see https://example.com/path/page end"


def test_mask_shortens_posix_home_path_without_username():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive("open /home/someuser/secret/file.txt failed")

    assert result == "open ~/secret/file.txt failed"
    assert "someuser" not in result


def test_mask_shortens_macos_home_path_without_username():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive("open /Users/someuser/secret/file.txt failed")

    assert result == "open ~/secret/file.txt failed"
    assert "someuser" not in result


def test_mask_replaces_secret_value_in_colon_form():
    from watchdog.masking import mask_sensitive

    result = mask_sensitive("password: hunter2fake rest")

    assert "hunter2fake" not in result
    assert result == "password=[masked] rest"


def test_mask_replaces_cookie_and_session_values():
    from watchdog.masking import mask_sensitive

    cookie_result = mask_sensitive("cookie: sessionvalue123 rest")
    session_result = mask_sensitive("session=abcdef123456 rest")

    assert "sessionvalue123" not in cookie_result
    assert "[masked]" in cookie_result
    assert session_result == "session=[masked] rest"


def test_mask_flattens_newlines_and_control_characters():
    from watchdog.masking import mask_sensitive

    assert mask_sensitive("line1\nline2\r\nline3") == "line1 line2 line3"
    assert mask_sensitive("a\tb\x00c") == "a b c"


def test_mask_truncates_spaced_text_exactly_without_ellipsis():
    from watchdog.masking import mask_sensitive

    text = "word " * 100  # 500文字（長い英数字列の規則には掛からない形）

    result = mask_sensitive(text)

    assert result == text[:200]
    assert len(result) == 200


def test_excerpt_max_length_constant_is_120_and_caps_output():
    from watchdog.masking import EXCERPT_MAX_LENGTH, mask_sensitive

    assert EXCERPT_MAX_LENGTH == 120

    result = mask_sensitive("word " * 100, max_length=EXCERPT_MAX_LENGTH)

    assert len(result) == 120
