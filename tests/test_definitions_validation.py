"""Regression tests: definitions root type and timezone validation.

Verified failures (2026-11-18 review):
- a JSON root that is neither an object nor a list (number, boolean,
  string) made ``load_definitions_file`` raise ``TypeError`` instead
  of ``DefinitionError``; non-object rows did the same;
- an unknown timezone name such as ``"Mars/Olympus"`` passed
  validation untouched.
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


def _write(tmp_path, payload):
    path = tmp_path / "definitions.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize("payload", [42, True, "hello", 1.5, None])
def test_non_container_root_raises_definition_error(tmp_path, payload):
    from watchdog.definitions import DefinitionError, load_definitions_file

    with pytest.raises(DefinitionError):
        load_definitions_file(_write(tmp_path, payload))


@pytest.mark.parametrize("payload", [[1, 2], ["x"], {"definitions": [42]}])
def test_non_object_rows_raise_definition_error(tmp_path, payload):
    from watchdog.definitions import DefinitionError, load_definitions_file

    with pytest.raises(DefinitionError):
        load_definitions_file(_write(tmp_path, payload))


def test_definitions_value_must_be_a_list(tmp_path):
    from watchdog.definitions import DefinitionError, load_definitions_file

    with pytest.raises(DefinitionError):
        load_definitions_file(_write(tmp_path, {"definitions": "not-a-list"}))


def test_unknown_timezone_raises_definition_error():
    from watchdog.definitions import DefinitionError, load_definitions

    with pytest.raises(DefinitionError):
        load_definitions([{**ROW, "timezone": "Mars/Olympus"}])


def test_unknown_timezone_in_file_raises_definition_error(tmp_path):
    from watchdog.definitions import DefinitionError, load_definitions_file

    payload = {"definitions": [{**ROW, "timezone": "Nowhere/Special"}]}

    with pytest.raises(DefinitionError):
        load_definitions_file(_write(tmp_path, payload))


@pytest.mark.parametrize("timezone", ["Asia/Tokyo", "UTC", "America/New_York"])
def test_known_timezones_are_accepted(timezone):
    from watchdog.definitions import load_definitions

    (definition,) = load_definitions([{**ROW, "timezone": timezone}])

    assert definition.timezone == timezone
