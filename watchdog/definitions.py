"""Definition table loading (test-contract module ``watchdog.definitions``).

Definitions live in configuration (JSON at runtime, dict rows in tests).
The watchdog body only reads them; judgement thresholds are never
hard-coded in the judgement logic.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping


class DefinitionError(ValueError):
    """Explicit error for missing/invalid definition-table entries."""


_PERIOD_RE = re.compile(r"^(\d+)\s*([dwhm])$")
_UNIT_DELTAS = {
    "m": lambda n: timedelta(minutes=n),
    "h": lambda n: timedelta(hours=n),
    "d": lambda n: timedelta(days=n),
    "w": lambda n: timedelta(weeks=n),
}

REQUIRED_FIELDS = ("name", "evidence_type", "period", "tolerance_seconds", "timezone")
_TEXT_FIELDS = ("name", "evidence_type", "period", "timezone")


def parse_period(value: str) -> timedelta:
    """Parse ``"1d"`` / ``"7d"`` / ``"1w"`` / ``"24h"`` / ``"6h"`` / ``"30m"``.

    Raises:
        DefinitionError: if the expression cannot be interpreted.
    """
    if not isinstance(value, str):
        raise DefinitionError(f"period must be a string, got {type(value).__name__}")
    match = _PERIOD_RE.match(value.strip())
    if match is None:
        raise DefinitionError(f"unparsable period expression: {value!r}")
    amount = int(match.group(1))
    if amount <= 0:
        raise DefinitionError(f"period must be positive: {value!r}")
    return _UNIT_DELTAS[match.group(2)](amount)


@dataclass(frozen=True)
class Definition:
    name: str
    evidence_type: str
    period: str
    tolerance_seconds: int
    timezone: str

    @property
    def period_timedelta(self) -> timedelta:
        return parse_period(self.period)


def _validate_row(row: Mapping[str, Any], index: int) -> Definition:
    for field in REQUIRED_FIELDS:
        if field not in row or row[field] is None:
            raise DefinitionError(f"definition #{index}: missing field {field!r}")
        value = row[field]
        if isinstance(value, str) and value.strip() == "":
            raise DefinitionError(f"definition #{index}: empty field {field!r}")
    for field in _TEXT_FIELDS:
        if not isinstance(row[field], str):
            raise DefinitionError(f"definition #{index}: field {field!r} must be text")
    tolerance = row["tolerance_seconds"]
    if isinstance(tolerance, bool) or not isinstance(tolerance, int):
        raise DefinitionError(
            f"definition #{index}: 'tolerance_seconds' must be an int"
        )
    if tolerance < 0:
        raise DefinitionError(f"definition #{index}: 'tolerance_seconds' must be >= 0")
    period = row["period"].strip()
    parse_period(period)  # raises DefinitionError for invalid expressions
    return Definition(
        name=row["name"].strip(),
        evidence_type=row["evidence_type"].strip(),
        period=period,
        tolerance_seconds=tolerance,
        timezone=row["timezone"].strip(),
    )


def load_definitions(rows: Iterable[Mapping[str, Any]]) -> list[Definition]:
    """Load definition rows; any invalid row fails the whole load."""
    return [_validate_row(row, i) for i, row in enumerate(rows)]


def load_definitions_file(path: str | Path) -> list[Definition]:
    """Load definitions from a JSON file.

    Accepted shapes: a bare list of rows, or an object with a
    ``"definitions"`` (or ``"targets"``) list.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        rows = data.get("definitions", data.get("targets"))
        if rows is None:
            raise DefinitionError("definitions file: no 'definitions' list found")
    else:
        rows = data
    return load_definitions(rows)
