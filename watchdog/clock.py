"""Current-time resolution shared by the CLI subcommands.

The default timezone is fixed to Asia/Tokyo; the process environment
(including the TZ variable) is deliberately not consulted. A ``--now``
override is parsed with :func:`datetime.fromisoformat`; an aware
value is kept exactly as given (no conversion), while a naive value
is interpreted as Asia/Tokyo wall time and made aware. Every parse
boundary routes through :func:`as_default_timezone`, so naive and
aware datetimes never mix in comparisons (which used to raise
``TypeError`` and fail the whole ``check`` run).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE_NAME = "Asia/Tokyo"
DEFAULT_TIMEZONE = ZoneInfo(DEFAULT_TIMEZONE_NAME)


def as_default_timezone(value: datetime) -> datetime:
    """Return *value* as an aware datetime.

    Aware values pass through unchanged; naive values are read as
    Asia/Tokyo wall time and get the default timezone attached.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=DEFAULT_TIMEZONE)
    return value


def resolve_now(now_arg: str | None) -> datetime:
    """Resolve the effective "now" for one CLI invocation.

    A missing or empty override means the current time in the default
    timezone; any other value is parsed as an ISO datetime string and
    normalized by :func:`as_default_timezone`.
    """
    if now_arg:
        return as_default_timezone(datetime.fromisoformat(now_arg))
    return datetime.now(DEFAULT_TIMEZONE)
