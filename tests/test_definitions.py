"""定義表の読み込み: 正常系 / 必須項目欠落 / 無効な周期表現.

対応する完了の定義: 「主要な定期実行が台帳に登録され…」
必須要件1: 成功の定義は設定側の定義表として持ち、本体は読むだけ。
"""

from __future__ import annotations

from datetime import timedelta

import pytest


def test_load_valid_definitions_returns_all(sample_definition_rows):
    from watchdog.definitions import load_definitions

    definitions = load_definitions(sample_definition_rows)

    assert len(definitions) == 3
    assert [d.name for d in definitions] == [
        "daily-fortune",
        "weekly-cleanup",
        "threads-collection",
    ]


def test_load_definition_preserves_fields(daily_definition_row):
    from watchdog.definitions import load_definitions

    (definition,) = load_definitions([daily_definition_row])

    assert definition.name == "daily-fortune"
    assert definition.evidence_type == "log_success"
    assert definition.period == "1d"
    assert definition.tolerance_seconds == 7200
    assert definition.timezone == "Asia/Tokyo"


def test_definition_period_timedelta_matches_period(daily_definition_row):
    from watchdog.definitions import load_definitions

    (definition,) = load_definitions([daily_definition_row])

    assert definition.period_timedelta == timedelta(days=1)


@pytest.mark.parametrize(
    "missing_field",
    ["name", "evidence_type", "period", "tolerance_seconds", "timezone"],
)
def test_load_definitions_missing_required_field_raises_explicit_error(
    daily_definition_row, missing_field
):
    from watchdog.definitions import DefinitionError, load_definitions

    row = {k: v for k, v in daily_definition_row.items() if k != missing_field}

    with pytest.raises(DefinitionError):
        load_definitions([row])


@pytest.mark.parametrize(
    "field", ["name", "evidence_type", "period", "timezone"]
)
def test_load_definitions_empty_required_field_raises_explicit_error(
    daily_definition_row, field
):
    from watchdog.definitions import DefinitionError, load_definitions

    row = dict(daily_definition_row, **{field: ""})

    with pytest.raises(DefinitionError):
        load_definitions([row])


def test_load_definitions_error_is_not_silent_for_one_bad_row_among_good(
    sample_definition_rows,
):
    from watchdog.definitions import DefinitionError, load_definitions

    rows = [sample_definition_rows[0], {"name": "broken-only-name"}]

    with pytest.raises(DefinitionError):
        load_definitions(rows)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1d", timedelta(days=1)),
        ("7d", timedelta(days=7)),
        ("1w", timedelta(days=7)),
        ("24h", timedelta(hours=24)),
        ("6h", timedelta(hours=6)),
        ("30m", timedelta(minutes=30)),
    ],
)
def test_parse_period_valid_expressions(expression, expected):
    from watchdog.definitions import parse_period

    assert parse_period(expression) == expected


def test_invalid_period_is_error_or_unknown(
    daily_definition_row, now
):
    """無効な周期表現は、黙って正常扱いせず、エラーか判定不能にする。"""
    from watchdog.definitions import DefinitionError, load_definitions

    row = dict(daily_definition_row, period="every-now-and-then")

    try:
        (definition,) = load_definitions([row])
    except DefinitionError:
        return  # エラーとして扱う実装は合格

    # エラーにならない実装は、判定が「判定不能」でなければならない
    from watchdog.status import Status, evaluate_status

    status = evaluate_status(definition, last_success_at=now, now=now)
    assert status == Status.UNKNOWN
    assert status != Status.SUCCESS
    assert status != Status.FAILURE


def test_parse_period_invalid_expression_raises(daily_definition_row):
    from watchdog.definitions import DefinitionError, parse_period

    with pytest.raises(DefinitionError):
        parse_period("not-a-period")
