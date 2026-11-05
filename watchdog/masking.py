"""Error masking (fixed in code; cannot be loosened by configuration).

Only masked, truncated excerpts may leave the local machine. The raw
``result_summary`` of a cron run is never accepted as input here at
all: callers pass only ``error_text`` (see watchdog.snapshot).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

DEFAULT_MAX_LENGTH = 200
# Design-fixed excerpt cap for ledger/notification use (design.md §7).
EXCERPT_MAX_LENGTH = 120

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+\S+")
_KV_SECRET_RE = re.compile(
    r"(?i)\b(token|password|passwd|secret|api[-_]?key|apikey|authorization"
    r"|cookie|session)\s*[:=]\s*\S+"
)
_SK_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{12}\b"
)
_PHONE_RE = re.compile(r"\b0\d{1,4}-\d{1,4}-\d{4}\b")
_URL_QUERY_RE = re.compile(r"(https?://[^\s?#]+)(?:\?[^\s]*)?")
_HOME_PATH_RE = re.compile(r"(?:/home|/Users)/[^/\s:]+")
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9+/=_-]{20,}\b")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")


@dataclass(frozen=True)
class SanitizedError:
    error_type: str
    occurred_at: datetime
    has_log: bool
    message: str


def mask_sensitive(text: str, *, max_length: int = DEFAULT_MAX_LENGTH) -> str:
    result = _EMAIL_RE.sub("[masked-email]", text)
    result = _BEARER_RE.sub("Bearer [masked]", result)
    result = _KV_SECRET_RE.sub(lambda m: f"{m.group(1)}=[masked]", result)
    result = _SK_KEY_RE.sub("[masked]", result)
    result = _UUID_RE.sub("[masked-id]", result)
    result = _PHONE_RE.sub("[masked-number]", result)
    result = _URL_QUERY_RE.sub(r"\1", result)
    result = _HOME_PATH_RE.sub("~", result)
    result = _LONG_TOKEN_RE.sub("[masked-id]", result)
    result = _CONTROL_RE.sub(" ", result)
    if len(result) > max_length:
        result = result[:max_length]
    return result


def sanitize_error(
    raw_message: str,
    *,
    error_type: str,
    occurred_at: datetime,
    has_log: bool,
) -> SanitizedError:
    return SanitizedError(
        error_type=error_type,
        occurred_at=occurred_at,
        has_log=has_log,
        message=mask_sensitive(raw_message),
    )
