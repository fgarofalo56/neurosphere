"""No-claim scan (PRP-56 item 3): the library, runbook, rendered bundles and frontend strings."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from neurosphere_core.compliance import DISCLAIMER, load_library, scan_for_claims
from neurosphere_core.compliance.loader import LIBRARY_DIR

from .helpers import REPO_ROOT


@pytest.mark.parametrize(
    "text",
    [
        "NeuroSphere is HIPAA compliant.",
        "The estate is non-compliant in two areas.",
        "NeuroSphere is FedRAMP authorized.",
        "The platform is authorized to operate.",
        "The workload is certified.",
        "NeuroSphere has an ATO from the agency.",
        "Coverage is 87% of controls.",
        "Authorization was granted on 2026-11-02.",
    ],
)
def test_planted_claims_fail(text: str) -> None:
    assert scan_for_claims(text), text


@pytest.mark.parametrize(
    "text",
    [
        DISCLAIMER,
        "This bundle does not determine compliance.",
        "NeuroSphere is not FedRAMP authorized; the authorizing official decides.",
        "Real ingestion uses authorized connectors only.",
        "NeuroSphere does not have an ATO and promises no date.",
        "Window 2026-10-17 to 2026-11-16 for evidence observed.",
    ],
)
def test_neutral_text_passes(text: str) -> None:
    assert scan_for_claims(text) == []


def test_library_files_contain_no_claim() -> None:
    for path in sorted(LIBRARY_DIR.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        assert scan_for_claims(text) == [], path.name
        # the parsed strings too (titles are what the page shows)
        doc = yaml.safe_load(text)
        for row in doc["controls"]:
            assert scan_for_claims(row["title"]) == [], row["control_id"]


def test_library_never_calls_a_framework_supported_or_covered() -> None:
    word = re.compile(r"\b(supported|covered|coverage)\b", re.IGNORECASE)
    for path in sorted(LIBRARY_DIR.glob("*.yaml")):
        assert not word.search(path.read_text(encoding="utf-8")), path.name


def test_every_control_has_source_and_retrieval_date() -> None:
    library = load_library()
    for fw in library.frameworks:
        for mapped in fw.controls:
            assert mapped.control.source_url.startswith("https://")
            assert mapped.control.source_retrieved
            assert mapped.control.framework_version


def test_runbook_has_the_disclaimer_and_no_claim() -> None:
    runbook = Path(REPO_ROOT / "docs/runbooks/compliance-evidence.md")
    if not runbook.exists():
        pytest.skip("runbook is written in item 8")
    text = " ".join(runbook.read_text(encoding="utf-8").split())
    assert DISCLAIMER in text
    assert scan_for_claims(runbook.read_text(encoding="utf-8")) == []
