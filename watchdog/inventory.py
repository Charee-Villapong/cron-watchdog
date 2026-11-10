"""Cron job inventory and definition-table diff (detection only).

Job existence cannot be taken from the collector snapshot: the
snapshot only contains jobs that are already in the definition table
(the collector queries status/runs per definition), so it can never
reveal unregistered jobs.  The filesystem projection of the cron
registry (``~/workspace/goals/*/crons/**`` and ``~/workspace/cron.d/**``)
enumerates every job instead; each projection file carries frontmatter
with ``id`` / ``enabled`` / ``schedule.kind``, which this module reads.
``_archive`` subtrees hold stale copies of removed jobs and are
ignored.

Only enabled, recurring (non-runonce) jobs count as existing: a
disabled job never runs, and runonce jobs are out of scope for the
definition table by design.  The diff never adds or removes definition
rows; it only classifies.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

RUNONCE_KIND = "runonce"
ARCHIVE_DIRNAME = "_archive"
_FRONTMATTER_HEAD_BYTES = 8192


@dataclass(frozen=True)
class CronJob:
    name: str
    kind: str | None
    enabled: bool


@dataclass(frozen=True)
class DefinitionDiff:
    matched: list[str]
    unregistered: list[str]
    missing: list[str]

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "matched": list(self.matched),
            "unregistered": list(self.unregistered),
            "missing": list(self.missing),
        }


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    """Parse the small YAML subset used by cron projection files.

    Returns flat fields (nested keys joined with ``.``), or None when
    the text has no complete frontmatter block.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, str] = {}
    section: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):
            key, sep, value = line.partition(":")
            if not sep:
                section = None
                continue
            section = key.strip()
            if value.strip():
                fields[section] = _unquote(value)
        elif section is not None:
            key, sep, value = line.strip().partition(":")
            if sep and value.strip():
                fields[f"{section}.{key}"] = _unquote(value)
    return None


def parse_cron_file(path: str | Path) -> CronJob | None:
    """Read one projection file; None when it is not a cron definition."""
    try:
        with Path(path).open("rb") as fh:
            head = fh.read(_FRONTMATTER_HEAD_BYTES)
    except OSError:
        return None
    fields = _parse_frontmatter(head.decode("utf-8", errors="replace"))
    if not fields:
        return None
    name = fields.get("id")
    kind = fields.get("schedule.kind")
    if not name or not kind:
        return None
    enabled = str(fields.get("enabled", "true")).strip().lower() != "false"
    return CronJob(name=name, kind=kind, enabled=enabled)


def load_inventory(roots: Iterable[str | Path]) -> list[CronJob]:
    """Enumerate cron jobs from projection trees, deduped by job id."""
    jobs: dict[str, CronJob] = {}
    for root in roots:
        base = Path(root)
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            if ARCHIVE_DIRNAME in path.parts:
                continue
            job = parse_cron_file(path)
            if job is not None and job.name not in jobs:
                jobs[job.name] = job
    return [jobs[name] for name in sorted(jobs)]


def recurring_names(jobs: Iterable[CronJob]) -> list[str]:
    """Names of jobs that exist as active recurring jobs."""
    return sorted(
        {job.name for job in jobs if job.enabled and job.kind != RUNONCE_KIND}
    )


def classify_diff(existing: Iterable[str], defined: Iterable[str]) -> DefinitionDiff:
    """Classify job names into matched / unregistered / missing."""
    existing_set = set(existing)
    defined_set = set(defined)
    return DefinitionDiff(
        matched=sorted(existing_set & defined_set),
        unregistered=sorted(existing_set - defined_set),
        missing=sorted(defined_set - existing_set),
    )
