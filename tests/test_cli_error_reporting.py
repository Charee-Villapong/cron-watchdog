"""Regression test: the CLI error line must not leak exception details.

Verified failure (2026-11-18 review): ``main`` printed the raw
exception message to stderr. Messages can embed input values (here a
fake secret used as a period expression) and internal paths. The
error line now reports the exception type only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "fixtures"
FAKE_SECRET = "FAKESECRET9x"


def test_error_line_reports_type_only_and_hides_input(tmp_path):
    definitions = tmp_path / "definitions.json"
    definitions.write_text(
        json.dumps(
            {
                "definitions": [
                    {
                        "name": "job-a",
                        "evidence_type": "log_success",
                        "period": FAKE_SECRET,
                        "tolerance_seconds": 7200,
                        "timezone": "Asia/Tokyo",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "watchdog",
            "check",
            "--definitions",
            str(definitions),
            "--snapshot",
            str(FIXTURES_DIR / "snapshot.json"),
            "--state",
            str(tmp_path / "state.json"),
            "--data-dir",
            str(tmp_path / "data"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "[watchdog] error: DefinitionError" in result.stderr
    assert FAKE_SECRET not in result.stderr
    assert str(tmp_path) not in result.stderr
