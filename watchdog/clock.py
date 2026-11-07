"""Current-time resolution shared by the CLI subcommands.

The default timezone is fixed to Asia/Tokyo; the process environment
(including the TZ variable) is deliberately not consulted. A ``--now``
override is parsed with :func:`datetime.fromisoformat` exactly as
given: no timezone is attached and no conversion is applied, so a
naive value stays naive. What each caller then does with a naive
value is unchanged by this sharing (``check`` fails on the
aware/naive comparison, ``heartbeat`` stores the value as-is);
unifying that asymmetry would be a spec change, not a refactor.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE_NAME = "Asia/Tokyo"
DEFAULT_TIMEZONE = ZoneInfo(DEFAULT_TIMEZONE_NAME)


def resolve_now(now_arg: str | None) -> datetime:
    """Resolve the effective "now" for one CLI invocation.

    A missing or empty override means the current time in the default
    timezone; any other value is parsed as an ISO datetime string.
    """
    if now_arg:
        return datetime.fromisoformat(now_arg)
    return datetime.now(DEFAULT_TIMEZONE)
