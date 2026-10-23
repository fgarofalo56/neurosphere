"""Guards the caveats in docs/ops/dr-runbook.md. Unmarked: runs in CI, no emulators."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNBOOK = REPO_ROOT / "docs" / "ops" / "dr-runbook.md"
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence" / "G07" / "dr"


def _text() -> str:
    return RUNBOOK.read_text(encoding="utf-8")


def _flat() -> str:
    """Lower-cased text with whitespace collapsed, so wrapped sentences still match."""
    return re.sub(r"\s+", " ", _text()).lower()


REQUIRED = {
    "metadata geo-dr copies neither event payloads nor entra rbac": (
        "metadata geo-dr copies neither event payloads nor entra rbac"
    ),
    "metadata geo-dr insufficient for event-data recovery point": "insufficient for an event-data",
    "geo-replication premium and dedicated only": "premium and dedicated tiers only",
    "government unverified": "government support is unverified",
    "geo-replication needs a live test": "requires a live test",
    "foundry no automatic dr": "foundry provides no automatic application disaster recovery",
    "model endpoint does not fail over": "does not fail over with the platform",
    "restore is not failover": "a restore drill proves a restore, not a failover",
    "provisional target": "provisional target",
    "environment label": "compose, not representative of production",
    "replay from archive": "replay from the redacted archive",
    "checkpoint check": "checkpoint store",
    "key retention check": "encryption keys",
    "dns check": "dns",
    "private endpoints both sides": "private endpoints",
}


@pytest.mark.parametrize("needle", list(REQUIRED.values()), ids=list(REQUIRED))
def test_required_caveat_present(needle: str) -> None:
    assert needle in _flat()


def test_private_endpoints_on_both_sides() -> None:
    assert "configured on both sides" in _flat()


def test_cites_external_references_with_retrieval_dates() -> None:
    text = _text()
    for url, date in (
        ("https://learn.microsoft.com/azure/event-hubs/geo-replication", "2026-07-11"),
        ("https://learn.microsoft.com/azure/event-hubs/event-hubs-geo-dr", "2026-10-06"),
        (
            "https://learn.microsoft.com/azure/foundry/how-to/high-availability-resiliency",
            "2026-10-06",
        ),
    ):
        assert url in text
        assert re.search(re.escape(url) + r"[\s(]*retrieved " + date, text)


_TARGET_NUMBER = re.compile(
    r"(?<![\w.])(4\s?h(?:ours?)?|15\s?min(?:utes?)?)(?![\w])", re.IGNORECASE
)


def test_rto_rpo_numbers_always_beside_provisional_target() -> None:
    """Any line quoting 4 h or 15 min must say 'provisional target' on that same line."""
    offenders = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(_text().splitlines(), start=1)
        if _TARGET_NUMBER.search(line) and "provisional target" not in line.lower()
    ]
    assert not offenders, offenders


def test_targets_are_not_presented_as_commitments() -> None:
    flat = _flat()
    for banned in ("guarantee", "sla", "fedramp", "authorization to operate", "99.9"):
        assert re.search(rf"\b{re.escape(banned)}\b", flat) is None, banned
    assert re.search(r"\bato\b", flat) is None


def test_measured_values_are_published_with_label() -> None:
    text = _text()
    assert "Measured restore time per store" in text
    assert "Recovery point gap" in text
    assert "Sum of per-store restore times" in text


def test_runbook_matches_committed_evidence() -> None:
    """The run date and git SHA quoted in the runbook come from the committed evidence file."""
    import json

    files = sorted(EVIDENCE_DIR.glob("restore-drill-compose-*.json"))
    assert files, "no committed drill evidence"
    evidence = json.loads(files[-1].read_text(encoding="utf-8"))
    assert evidence["environment_label"] == "compose, not representative of production"
    assert evidence["measured"]["all_match"] is True
    assert evidence["git_sha"] in _text()
    assert evidence["date"] in _text()
    for store in evidence["measured"]["stores"]:
        assert store["match"] is True
