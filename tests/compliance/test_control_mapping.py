"""PRP-23 item 2: the NIST 800-53 control mapping is well formed and makes no overclaim.

The mapping lives in ``docs/compliance/ssp/control-mapping.yaml``. These tests fail on a bad
status, a missing PRP, a missing evidence path, a planned/customer entry with no owner, and on any
affirmative claim of compliance, authorization, an ATO, a percentage or a certification date.

The claim detector is a handful of pure functions so the same rule is exercised both by planted
fixture strings and by the real mapping and documents.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SSP_DIR = ROOT / "docs" / "compliance" / "ssp"
MAPPING_PATH = SSP_DIR / "control-mapping.yaml"
POAM_PATH = ROOT / "docs" / "compliance" / "poam.md"
MATRIX_REL = "docs/compliance/responsibility-matrix.md"

STATEMENT = "not FedRAMP authorized; the authorizing official decides"
VOCABULARY = (
    "designed",
    "implemented_tested",
    "inherited",
    "customer",
    "planned",
    "not_applicable",
)
EVIDENCE_REQUIRED = {"designed", "implemented_tested", "inherited"}
OWNER_REQUIRED = {"planned", "customer"}
REQUIRED_FAMILIES = {
    "AC", "AU", "CA", "CM", "CP", "IA", "IR", "PL", "RA", "SA", "SC", "SI", "SR",
}  # fmt: skip
SCOPE_INPUTS = (
    "Data classification",
    "Payload opt-in",
    "Retention periods",
    "Legal hold process",
    "Authorizing official",
    "Agency baseline",
)
POAM_COLUMNS = (
    "Weakness",
    "Control",
    "Milestone",
    "Owner",
    "Scheduled completion",
    "Status",
)

# ---------------------------------------------------------------------------
# Claim detector (pure functions)
# ---------------------------------------------------------------------------

_NEGATION = re.compile(r"\b(not|no|never|cannot|nor|neither)\b", re.IGNORECASE)
_AUTHORIZED = re.compile(r"\bauthori[sz]ed\b", re.IGNORECASE)
_AUTHORIZED_OK_NEXT = re.compile(
    r"\s+(custodians?|users?|connectors?|principals?|callers?|personnel|operators?|roles?)\b",
    re.IGNORECASE,
)
_COMPLIANT = re.compile(r"\bcompliant\b", re.IGNORECASE)
_PERCENT = re.compile(r"\b\d{1,3}(?:\.\d+)?\s?%")
_ATO_CLAIM = re.compile(
    r"\b(?:has|have|holds?|received|granted|achieved|obtained)\b[^.;\n]{0,20}\bATO\b"
    r"|\bATO\s+(?:granted|achieved|issued|received)\b",
    re.IGNORECASE,
)
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_DATE_TOPIC = re.compile(r"\b(?:certif\w*|authori[sz]\w*|ATO)\b", re.IGNORECASE)


def _clause_prefix(text: str, start: int, width: int = 25) -> str:
    """Text before ``start`` limited to the same clause and at most ``width`` characters."""
    prefix = text[max(0, start - width) : start]
    return re.split(r"[.;:\n]", prefix)[-1]


def _negated(text: str, start: int) -> bool:
    return _NEGATION.search(_clause_prefix(text, start)) is not None


def find_claims(text: str) -> list[str]:
    """Return a description of each affirmative overclaim found in ``text``.

    Rules:
    - "compliant" is never allowed (the status vocabulary has no such value).
    - "authorized" is allowed only when negated in the same clause ("not FedRAMP authorized"),
      or when it qualifies a named actor class: custodians, users, connectors, principals,
      callers, personnel, operators, roles. "authorizing official" is a different word and passes.
    - An ATO claim ("has an ATO", "ATO granted") is allowed only when negated.
    - A percentage is never allowed (no compliance score).
    - A date on a sentence about certification, authorization or an ATO is never allowed.
    """
    found: list[str] = []
    for m in _COMPLIANT.finditer(text):
        found.append(f"compliant: {m.group(0)!r}")
    for m in _AUTHORIZED.finditer(text):
        if _negated(text, m.start()):
            continue
        if _AUTHORIZED_OK_NEXT.match(text, m.end()):
            continue
        found.append(f"authorized: {_snippet(text, m.start())!r}")
    for m in _ATO_CLAIM.finditer(text):
        if not _negated(text, m.start()):
            found.append(f"ato: {m.group(0)!r}")
    for m in _PERCENT.finditer(text):
        found.append(f"percentage: {m.group(0)!r}")
    for sentence in re.split(r"(?<=[.;])\s+|\n", text):
        if _DATE.search(sentence) and _DATE_TOPIC.search(sentence):
            found.append(f"dated claim: {sentence.strip()[:60]!r}")
    return found


def _snippet(text: str, start: int) -> str:
    return text[max(0, start - 20) : start + 25].replace("\n", " ")


def iter_strings(node: Any) -> Iterator[str]:
    """Yield every string in a nested YAML structure."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from iter_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from iter_strings(value)


def missing_evidence(entry: dict[str, Any], root: Path) -> list[str]:
    """Evidence paths of ``entry`` that do not exist under ``root``."""
    return [p for p in entry.get("evidence") or [] if not (root / p).exists()]


def entry_problems(entry: dict[str, Any], root: Path, known_prps: set[str]) -> list[str]:
    """All structural problems of one control entry."""
    problems: list[str] = []
    cid = entry.get("id", "?")
    status = entry.get("status")
    if status not in VOCABULARY:
        problems.append(f"{cid}: status {status!r} not in vocabulary")
    prps = entry.get("prps") or []
    if not prps:
        problems.append(f"{cid}: no implementing PRP")
    problems += [f"{cid}: unknown PRP {p}" for p in prps if p not in known_prps]
    if status in EVIDENCE_REQUIRED:
        if not entry.get("evidence"):
            problems.append(f"{cid}: {status} entry has no evidence path")
        problems += [f"{cid}: evidence path missing: {p}" for p in missing_evidence(entry, root)]
    if status in OWNER_REQUIRED and not str(entry.get("owner") or "").strip():
        problems.append(f"{cid}: {status} entry names no owner")
    if status == "inherited":
        if MATRIX_REL not in (entry.get("evidence") or []):
            problems.append(f"{cid}: inherited entry does not cite the responsibility matrix")
        if "do not automatically authorize" not in " ".join(str(entry.get("narrative")).split()):
            problems.append(f"{cid}: inherited entry lacks the non-authorization caveat")
    return problems


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _known_prps() -> set[str]:
    ids: set[str] = set()
    for path in (ROOT / "PRPs").glob("*/PRP-*.md"):
        m = re.match(r"(PRP-\d+)-", path.name)
        if m:
            ids.add(m.group(1))
    return ids


@pytest.fixture(scope="module")
def mapping() -> dict[str, Any]:
    return yaml.safe_load(MAPPING_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def controls(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    return mapping["controls"]


@pytest.fixture(scope="module")
def known_prps() -> set[str]:
    return _known_prps()


def _owned_markdown() -> list[Path]:
    return sorted([*SSP_DIR.rglob("*.md"), POAM_PATH])


# ---------------------------------------------------------------------------
# Detector tests (planted fixtures)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "NeuroSphere is FedRAMP authorized.",
        "The platform is authorized to operate.",
        "NeuroSphere is compliant with the Moderate baseline.",
        "The system is non-compliant in two areas.",
        "NeuroSphere has an ATO from the agency.",
        "ATO granted for the workload.",
        "Coverage is 87% of controls.",
        "Authorization was granted on 2026-11-02.",
        "Certification date: 2026-12-01.",
        "Only authorized.",
    ],
)
def test_planted_affirmative_claims_fail(text: str) -> None:
    assert find_claims(text), text


@pytest.mark.parametrize(
    "text",
    [
        STATEMENT,
        "NeuroSphere is not FedRAMP authorized; the authorizing official decides.",
        "NeuroSphere does not have an ATO and promises no date.",
        "Real ingestion uses authorized connectors only.",
        "Held data may be exported to authorized custodians.",
        "Only authorized users and principals reach the API.",
        "A listing in an audit scope is not an authorization of this workload.",
        "Inherited controls do not automatically authorize this application.",
        "The authorizing official owns the decision.",
        "Retrieved 2026-10-08 from the audit-scope listing.",
    ],
)
def test_non_claim_forms_pass(text: str) -> None:
    assert find_claims(text) == [], text


def test_statement_sentence_is_exactly_the_mandated_text() -> None:
    assert STATEMENT == "not FedRAMP authorized; the authorizing official decides"
    assert find_claims(STATEMENT) == []


def test_negation_does_not_leak_across_sentences() -> None:
    assert find_claims("This is not a drill. The system is authorized.")


def test_entry_problems_detects_planted_defects(tmp_path: Path) -> None:
    (tmp_path / "real.md").write_text("x", encoding="utf-8")
    known = {"PRP-06"}
    good = {"id": "AC-3", "status": "designed", "prps": ["PRP-06"], "evidence": ["real.md"]}
    assert entry_problems(good, tmp_path, known) == []

    bad_status = {**good, "status": "compliant"}
    assert any("not in vocabulary" in p for p in entry_problems(bad_status, tmp_path, known))

    missing = {**good, "status": "implemented_tested", "evidence": ["nope.md"]}
    assert any("evidence path missing" in p for p in entry_problems(missing, tmp_path, known))

    no_ev = {**good, "evidence": []}
    assert any("no evidence path" in p for p in entry_problems(no_ev, tmp_path, known))

    no_prp = {**good, "prps": []}
    assert any("no implementing PRP" in p for p in entry_problems(no_prp, tmp_path, known))

    ghost = {**good, "prps": ["PRP-999"]}
    assert any("unknown PRP" in p for p in entry_problems(ghost, tmp_path, known))

    planned = {"id": "SI-12", "status": "planned", "prps": ["PRP-06"], "evidence": []}
    assert any("names no owner" in p for p in entry_problems(planned, tmp_path, known))
    assert entry_problems({**planned, "owner": "PRP-23 item 1"}, tmp_path, known) == []

    inherited = {**good, "status": "inherited", "narrative": "Platform provides it."}
    problems = entry_problems(inherited, tmp_path, known)
    assert any("responsibility matrix" in p for p in problems)
    assert any("non-authorization caveat" in p for p in problems)


# ---------------------------------------------------------------------------
# The real mapping
# ---------------------------------------------------------------------------


def test_status_vocabulary_is_fixed(mapping: dict[str, Any]) -> None:
    assert tuple(mapping["status_vocabulary"]) == VOCABULARY
    assert set(mapping["status_meaning"]) == set(VOCABULARY)


def test_every_entry_is_well_formed(controls: list[dict[str, Any]], known_prps: set[str]) -> None:
    assert controls, "mapping has no controls"
    problems = [p for e in controls for p in entry_problems(e, ROOT, known_prps)]
    assert problems == []


def test_control_ids_unique_and_in_declared_families(
    mapping: dict[str, Any], controls: list[dict[str, Any]]
) -> None:
    ids = [e["id"] for e in controls]
    assert len(ids) == len(set(ids))
    for cid in ids:
        assert re.fullmatch(r"[A-Z]{2}-\d+", cid), cid
        assert cid.split("-")[0] in mapping["families"], cid


def test_required_families_present(controls: list[dict[str, Any]]) -> None:
    present = {e["id"].split("-")[0] for e in controls}
    assert REQUIRED_FAMILIES <= present, sorted(REQUIRED_FAMILIES - present)


def test_baseline_is_not_selected_here(mapping: dict[str, Any]) -> None:
    baseline = str(mapping["baseline"]).lower()
    assert "customer input" in baseline
    assert "open" in baseline


def test_statement_field_and_no_claims_in_mapping(mapping: dict[str, Any]) -> None:
    assert mapping["statement"] == STATEMENT
    offenders = [(s[:60], f) for s in iter_strings(mapping) if (f := find_claims(s))]
    assert offenders == []


def test_inheritance_reference_points_at_matrix(mapping: dict[str, Any]) -> None:
    assert mapping["inheritance_reference"] == MATRIX_REL
    assert (ROOT / MATRIX_REL).is_file()
    assert "do not automatically authorize" in " ".join(mapping["inheritance_caveat"].split())


def test_no_entry_uses_vocabulary_outside_the_six(controls: list[dict[str, Any]]) -> None:
    counts = {s: sum(1 for e in controls if e["status"] == s) for s in VOCABULARY}
    assert sum(counts.values()) == len(controls)


def test_family_narrative_files_cover_every_control(
    mapping: dict[str, Any], controls: list[dict[str, Any]]
) -> None:
    for fam in {e["id"].split("-")[0] for e in controls}:
        assert fam in mapping["families"]
        path = SSP_DIR / "families" / f"{fam.lower()}.md"
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8")
        for entry in controls:
            if entry["id"].startswith(fam + "-"):
                assert f"## {entry['id']} " in text, f"{entry['id']} missing from {path.name}"


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def test_owned_documents_exist() -> None:
    assert (SSP_DIR / "scope.md").is_file()
    assert POAM_PATH.is_file()
    assert len(_owned_markdown()) >= 3


def test_every_owned_markdown_has_statement_and_no_claims() -> None:
    for path in _owned_markdown():
        text = path.read_text(encoding="utf-8")
        assert STATEMENT in text, f"{path.relative_to(ROOT)} lacks the statement"
        assert find_claims(text) == [], path.relative_to(ROOT)


def test_every_owned_markdown_has_fixed_header_block() -> None:
    for path in _owned_markdown():
        head = "\n".join(path.read_text(encoding="utf-8").splitlines()[:8])
        for label in ("- Scope:", "- Status vocabulary:", "- Statement:"):
            assert label in head, f"{path.relative_to(ROOT)} header lacks {label}"


def test_scope_lists_customer_inputs_as_open() -> None:
    text = (SSP_DIR / "scope.md").read_text(encoding="utf-8")
    rows = {line.split("|")[1].strip(): line for line in text.splitlines() if line.startswith("| ")}
    for name in SCOPE_INPUTS:
        match = [line for key, line in rows.items() if key.startswith(name)]
        assert match, f"scope.md lacks input {name}"
        assert "| OPEN |" in match[0], f"{name} is not OPEN"


def test_scope_keeps_fedramp_and_dod_in_a_separate_section() -> None:
    text = (SSP_DIR / "scope.md").read_text(encoding="utf-8")
    assert "## FedRAMP and DoD scope (tracked separately)" in text
    assert "not interchangeable" in text
    assert "not an authorization of this workload" in text


def test_poam_template_columns_and_no_prefilled_dates() -> None:
    text = POAM_PATH.read_text(encoding="utf-8")
    header = "| " + " | ".join(POAM_COLUMNS) + " |"
    assert header in text
    assert _DATE.search(text) is None, "POA&M must not carry pre-filled dates"
