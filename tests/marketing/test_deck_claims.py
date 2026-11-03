"""Claims lint for the walking deck, plus tests of the shared lint rules (PRP-26 item 1)."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DECK_DIR = REPO / "marketing" / "deck"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rules = _load("claims_rules", Path(__file__).with_name("claims_rules.py"))
builder = _load("deck_build_pptx", DECK_DIR / "build_pptx.py")

DECK_TEXT = (DECK_DIR / "deck.md").read_text(encoding="utf-8")
FRONT, _BODY = rules.parse_front_matter(DECK_TEXT)
SLIDES = builder.parse_deck(DECK_TEXT)
CHECKLIST = (DECK_DIR / "claims-checklist.md").read_text(encoding="utf-8")


def _checklist_rows() -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in CHECKLIST.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and re.fullmatch(r"C\d+", cells[0]):
            rows[cells[0]] = cells
    return rows


# ---- the deck itself -------------------------------------------------------------------


def test_deck_has_no_claims_violations() -> None:
    violations = rules.find_violations(DECK_TEXT)
    assert violations == [], "\n".join(f"line {v.line} [{v.rule}] {v.sentence}" for v in violations)


def test_deck_front_matter_is_draft_with_claims() -> None:
    assert FRONT["status"] in {"draft", "reviewed"}
    assert isinstance(FRONT["claims"], list) and FRONT["claims"]


def test_slide_count_and_notes() -> None:
    assert 10 <= len(SLIDES) <= 14
    for slide in SLIDES:
        assert slide.title
        assert slide.bullets
        assert len(slide.notes) > 40, slide.title
        assert slide.claims, f"slide '{slide.title}' cites no claim"


def test_every_slide_claim_is_declared_and_every_declared_claim_is_used() -> None:
    declared = {c["id"] for c in FRONT["claims"]}
    used = {cid for s in SLIDES for cid in s.claims}
    assert used <= declared, used - declared
    assert declared <= used, declared - used


def test_every_claim_source_exists() -> None:
    for claim in FRONT["claims"]:
        assert (REPO / claim["source"]).is_file(), f"{claim['id']}: {claim['source']}"


def test_checklist_matches_front_matter() -> None:
    rows = _checklist_rows()
    assert set(rows) == {c["id"] for c in FRONT["claims"]}
    for claim in FRONT["claims"]:
        cells = rows[claim["id"]]
        assert claim["source"] in cells[3]
        assert (REPO / claim["source"]).is_file()
        slide_numbers = {str(i) for i, s in enumerate(SLIDES, 1) if claim["id"] in s.claims}
        assert set(re.findall(r"\d+", cells[2])) == slide_numbers


def test_unreviewed_claims_block_reviewed_status() -> None:
    unreviewed = [cid for cid, cells in _checklist_rows().items() if "UNREVIEWED" in cells[4]]
    if FRONT["status"] == "reviewed":
        assert not unreviewed, f"reviewed deck with unreviewed claims: {unreviewed}"
    else:
        assert FRONT["status"] == "draft"


def test_no_microsoft_marks_or_partnership_implication() -> None:
    lowered = DECK_TEXT.lower()
    for phrase in ("partner", "endorse", "microsoft logo", "badge", "powered by microsoft"):
        assert phrase not in lowered, phrase


def test_checklist_has_no_em_dash() -> None:
    assert "—" not in CHECKLIST


# ---- the shared lint rules: pass and fail examples -------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "NeuroSphere is not FedRAMP authorized and cannot grant an agency ATO.",
        "We do not claim FedRAMP authorization, an ATO, parity or savings figures.",
        "No savings claim is made.",
        "The Viewer role is read-only.",
        "Target: dashboard p95 <=2s on bounded aggregates.",
        "Measured 99.9% availability, see docs/evidence/G05/README.md.",
        "Government support is gated by the capability matrix.",
        "A station is not a ratio of anything.",
        "The analyst runs saved reports.",
        "Duration estimate: 11 s",
        "Estimated runtime 132 s (about 2.2 min).",
        "Estimated total runtime 132 s.",
        "We do not claim FedRAMP authorization.",
        "no ATO claim is made",
        "It is not slow, and we cannot say it is the best.",
        "It is not FedRAMP High and has no IL5 status.",
    ],
)
def test_rules_pass_examples(text: str) -> None:
    assert rules.find_violations(text) == []


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("NeuroSphere is FedRAMP authorized.", "authorized"),
        ("The platform has an ATO.", "ato"),
        ("The platform is FedRAMP compliant.", "fedramp-status"),
        ("It offers full parity with Commercial.", "parity"),
        ("A unique approach.", "unique"),
        ("The first and only tool.", "first"),
        ("The best catalog.", "best"),
        ("Performance is guaranteed.", "guaranteed"),
        ("A compliant platform.", "compliant"),
        ("It saves 30 percent of spend.", "savings"),
        ("Complete coverage of every agent.", "completeness"),
        ("Teams are saving money.", "savings"),
        ("Teams saved 30 percent last quarter.", "savings"),
        ("Dashboards load in 2 s, estimate: 40%.", "unlabelled-number"),
        ("Cost fell 40% in the estimate.", "unlabelled-number"),
        ("Dashboards load in 2 s.", "unlabelled-number"),
        ("Dashboards load in 2s.", "unlabelled-number"),
        ("Availability is 99.9%.", "unlabelled-number"),
        ("Fast and good — really.", "em-dash"),
        ("Not only fast but the best.", "best"),
        ("It is not slow and is the only option.", "only"),
        ("Not slow, the first choice.", "first"),
        ("NeuroSphere supports FedRAMP High.", "fedramp-level"),
        ("Designed for FedRAMP Moderate workloads.", "fedramp-level"),
        ("Ready for IL4/IL5 data.", "fedramp-level"),
        ("It is not FedRAMP authorized but covers FedRAMP Low.", "fedramp-level"),
        ("Teams save money.", "savings"),
        ("It will save 30 percent.", "savings"),
        ("Reduces cost by 30 percent.", "unlabelled-number"),
        ("Cuts latency 40 percent.", "unlabelled-number"),
        ("Cuts spend by 12 per cent.", "unlabelled-number"),
        ("Cuts latency to 2 s, our estimate.", "unlabelled-number"),
        ("Scene estimate says 40%.", "unlabelled-number"),
    ],
)
def test_rules_fail_examples(text: str, rule: str) -> None:
    assert rule in {v.rule for v in rules.find_violations(text)}


def test_negation_must_come_before_the_phrase() -> None:
    assert rules.find_violations("Authorized, which we do not dispute.") != []


def test_negation_does_not_leak_across_sentences() -> None:
    text = "There is no savings figure. The platform is unique."
    assert [v.rule for v in rules.find_violations(text)] == ["unique"]


def test_violation_reports_line_number() -> None:
    violations = rules.find_violations("fine line\nThe best one.\n")
    assert [(v.rule, v.line) for v in violations] == [("best", 2)]


def test_parse_front_matter() -> None:
    meta, body = rules.parse_front_matter("---\nstatus: draft\nclaims: [a]\n---\n# Hi\n")
    assert meta == {"status": "draft", "claims": ["a"]}
    assert body.startswith("# Hi")
    with pytest.raises(ValueError, match="front matter"):
        rules.parse_front_matter("# no front matter")
    with pytest.raises(ValueError, match="unterminated"):
        rules.parse_front_matter("---\nstatus: draft\n")
