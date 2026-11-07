"""definitions のファイル版読込の現状固定テスト（特性テスト）: C-047.

リファクタリング候補 C-047 のうち `load_definitions_file`
（ファイル版読込の3形態分岐）を対象とする。行形式の検証自体は
test_definitions.py で固定済みのため、ここではファイル形式の分岐と
読み込みエラー時の例外だけを、実測した現行挙動で固定する。

3形態:
1. `{"definitions": [...]}` 形式（fixtures／サンプルの正形式）
2. `[...]` 形式（裸のリスト）
3. それ以外の dict は DefinitionError（'definitions' リストが無い）

すべて tmp_path 配下の架空ファイルで実行する。
"""

from __future__ import annotations

import json

import pytest

ROW = {
    "name": "job-a",
    "evidence_type": "log_success",
    "period": "1d",
    "tolerance_seconds": 7200,
    "timezone": "Asia/Tokyo",
}


def _write(tmp_path, payload) -> "object":
    path = tmp_path / "definitions.json"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_wrapped_definitions_object_form(tmp_path):
    from watchdog.definitions import load_definitions_file

    definitions = load_definitions_file(_write(tmp_path, {"definitions": [ROW]}))

    assert [d.name for d in definitions] == ["job-a"]
    assert definitions[0].period == "1d"
    assert definitions[0].tolerance_seconds == 7200


def test_bare_list_form(tmp_path):
    from watchdog.definitions import load_definitions_file

    definitions = load_definitions_file(_write(tmp_path, [ROW]))

    assert [d.name for d in definitions] == ["job-a"]


@pytest.mark.parametrize("payload", [{"definitions": []}, []])
def test_empty_forms_return_empty_list(tmp_path, payload):
    from watchdog.definitions import load_definitions_file

    assert load_definitions_file(_write(tmp_path, payload)) == []


def test_wrapped_form_ignores_extra_top_level_keys(tmp_path):
    from watchdog.definitions import load_definitions_file

    payload = {"definitions": [ROW], "version": 1}

    definitions = load_definitions_file(_write(tmp_path, payload))

    assert [d.name for d in definitions] == ["job-a"]


@pytest.mark.parametrize(
    "payload",
    [
        ROW,  # 単一定義の dict そのものは受け付けない
        {"jobs": [ROW]},  # 別キー配下のリストは拾わない
    ],
)
def test_dict_without_definitions_key_raises_definition_error(tmp_path, payload):
    from watchdog.definitions import DefinitionError, load_definitions_file

    with pytest.raises(DefinitionError):
        load_definitions_file(_write(tmp_path, payload))


def test_missing_file_raises_file_not_found(tmp_path):
    from watchdog.definitions import load_definitions_file

    with pytest.raises(FileNotFoundError):
        load_definitions_file(tmp_path / "no-such-definitions.json")


def test_invalid_json_raises_value_error(tmp_path):
    from watchdog.definitions import load_definitions_file

    with pytest.raises(ValueError):  # json.JSONDecodeError は ValueError の子
        load_definitions_file(_write(tmp_path, "{oops"))


def test_invalid_row_in_file_raises_definition_error(tmp_path):
    from watchdog.definitions import DefinitionError, load_definitions_file

    payload = {"definitions": [{"name": "broken-only-name"}]}

    with pytest.raises(DefinitionError):
        load_definitions_file(_write(tmp_path, payload))
