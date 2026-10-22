"""The responsibility matrix carries the fixed compliance statement and makes no claims."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

MATRIX = Path(__file__).resolve().parents[3] / "docs" / "compliance" / "responsibility-matrix.md"
PHRASE = "not FedRAMP authorized; the authorizing official decides"

FORBIDDEN_CLAIMS = (
    re.compile(r"\bis\s+FedRAMP\s+authorized\b", re.IGNORECASE),
    re.compile(r"\bhas\s+(?:an\s+)?ATO\b", re.IGNORECASE),
    re.compile(r"\bATO\s+(?:granted|achieved|obtained|received)\b", re.IGNORECASE),
    re.compile(r"\bparity\s+with\b", re.IGNORECASE),
    re.compile(r"\bcompliance\s+parity\b", re.IGNORECASE),
    re.compile(r"\bfully\s+compliant\b", re.IGNORECASE),
    re.compile(
        r"\bauthorized\s+for\s+(?:an?\s+|the\s+)?(?:agency|government|production)\b", re.IGNORECASE
    ),
)


@pytest.fixture(scope="module")
def text() -> str:
    return MATRIX.read_text(encoding="utf-8")


def test_matrix_exists_and_has_exact_phrase(text: str) -> None:
    assert PHRASE in text


def test_columns_present(text: str) -> None:
    header = next(line for line in text.splitlines() if line.startswith("| Control area"))
    cells = [cell.strip() for cell in header.strip("|").split("|")]
    assert cells[0] == "Control area"
    assert cells[1] == "Microsoft"
    assert cells[2] == "Customer"
    assert cells[3].startswith("NeuroSphere")


def test_control_areas_present(text: str) -> None:
    for area in (
        "Physical and infrastructure",
        "Platform service controls inherited via audit scope",
        "Identity and tenant configuration",
        "Network isolation and private endpoints",
        "Data classification and residency",
        "Key management",
        "Logging and monitoring",
        "Application controls of NeuroSphere itself",
        "SSP and ATO",
    ):
        assert f"| {area} |" in text, area


def test_neurosphere_controls_are_customer_assessed(text: str) -> None:
    assert "customer-assessed" in text


def test_required_statements(text: str) -> None:
    lowered = text.lower()
    assert "do not automatically authorize" in lowered
    assert "not interchangeable" in lowered
    assert "separate facts" in lowered
    assert "no certification or authorization deadline is promised" in lowered
    assert "docs/evidence/G02/register.yaml" in text


@pytest.mark.parametrize("pattern", FORBIDDEN_CLAIMS, ids=lambda p: p.pattern)
def test_no_authorization_or_parity_claims(text: str, pattern: re.Pattern[str]) -> None:
    assert not pattern.search(text)


def test_claim_patterns_catch_bad_text() -> None:
    bad = ("NeuroSphere is FedRAMP authorized", "ATO granted last week", "parity with Commercial")
    for sample in bad:
        assert any(p.search(sample) for p in FORBIDDEN_CLAIMS), sample
    assert not any(p.search("NeuroSphere is not FedRAMP authorized") for p in FORBIDDEN_CLAIMS)
