"""Time-boxed scanner exceptions in ``.grype.yaml`` expire.

Grype has no expiry field. A rule group that is accepted for a limited time carries a marker
comment ``# expires: YYYY-MM-DD <slug>`` in ``.grype.yaml``; this test fails once that date has
passed, so the exception cannot outlive its review date unnoticed.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MARKER = re.compile(r"^# expires: (\d{4}-\d{2}-\d{2}) ([a-z0-9-]+)$", re.MULTILINE)


def _markers() -> list[tuple[date, str]]:
    text = (ROOT / ".grype.yaml").read_text(encoding="utf-8")
    return [(date.fromisoformat(day), slug) for day, slug in MARKER.findall(text)]


def test_no_time_boxed_grype_exception_has_expired() -> None:
    today = datetime.now(UTC).date()
    expired = [f"{slug} (expired {day.isoformat()})" for day, slug in _markers() if today > day]
    assert not expired, (
        "time-boxed .grype.yaml exceptions have expired; re-check the findings, then remove the "
        f"rules and the marker or renew them with the owner: {expired}"
    )


def test_openssl_alpine_rules_carry_an_expiry_marker() -> None:
    text = (ROOT / ".grype.yaml").read_text(encoding="utf-8")
    rules = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    has_openssl_rule = any("libcrypto3" in line or "libssl3" in line for line in rules)
    slugs = {slug for _, slug in _markers()}
    # The rules and their marker come and go together.
    assert has_openssl_rule == ("openssl-alpine" in slugs)
