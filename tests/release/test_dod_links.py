"""Checks that the release DoD checklist only cites evidence and never claims compliance."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKLIST = REPO_ROOT / "docs" / "release" / "dod-checklist.md"
GATES_DOC = REPO_ROOT / "docs" / "RESEARCH-AND-GATES.md"
MASTER_INDEX = REPO_ROOT / "PRPs" / "PRP-MASTER-neurosphere.md"
MASTER_ANCHOR = "definition-of-programme-done"

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
CODE_RE = re.compile(r"`([^`]+)`")
OPEN_RE = re.compile(r"OPEN \(G\d\d\)")
GATE_RE = re.compile(r"\bG\d\d\b")
CLAIM_PHRASES = (
    "fedramp authorized",
    "fedramp-authorized",
    "fedramp high authorized",
    "fedramp compliant",
    "ato granted",
    "ato obtained",
    "ato achieved",
    "authorized to operate",
    "compliance parity achieved",
    "achieves compliance parity",
    "full compliance parity",
    "has an ato",
)


def _resolve(target: str, base: Path) -> Path:
    """Resolve a link target relative to the checklist, then the repo root."""
    path = urlsplit(target).path
    candidate = (base.parent / path).resolve()
    if candidate.is_relative_to(REPO_ROOT.resolve()):
        return candidate
    return (REPO_ROOT / path).resolve()


def _under_evidence(path: Path) -> bool:
    evidence = (REPO_ROOT / "docs" / "evidence").resolve().parts
    return path.parts[: len(evidence)] == evidence and len(path.parts) > len(evidence)


def _is_master(target: str, base: Path) -> bool:
    parts = urlsplit(target)
    return (
        not parts.scheme
        and not parts.netloc
        and parts.fragment == MASTER_ANCHOR
        and _resolve(target, base) == MASTER_INDEX.resolve()
    )


def _links(text: str) -> list[str]:
    return LINK_RE.findall(text)


def _evidence_codespans(text: str) -> list[str]:
    return [c for c in CODE_RE.findall(text) if "docs/evidence/" in c]


def check_line_references(text: str, base: Path) -> list[str]:
    errors = []
    for line in text.splitlines():
        if not line.startswith("- [ ]"):
            continue
        has_link = any(
            not urlsplit(t).scheme and _under_evidence(_resolve(t, base)) for t in _links(line)
        )
        if not (has_link or _evidence_codespans(line) or OPEN_RE.search(line)):
            errors.append(f"no evidence reference or OPEN (Gxx): {line}")
    return errors


def check_link_targets(text: str, base: Path) -> list[str]:
    errors = []
    for target in _links(text):
        if _is_master(target, base):
            continue
        parts = urlsplit(target)
        if parts.scheme or parts.netloc:
            errors.append(f"external link not allowed: {target}")
        elif not _under_evidence(_resolve(target, base)):
            errors.append(f"link outside docs/evidence: {target}")
    return errors


def check_links_exist(text: str, base: Path) -> list[str]:
    errors = []
    for target in _links(text):
        parts = urlsplit(target)
        if parts.scheme or parts.netloc or _is_master(target, base):
            continue
        resolved = _resolve(target, base)
        if _under_evidence(resolved) and not resolved.exists():
            errors.append(f"evidence path missing: {target}")
    return errors


def check_codespan_patterns(text: str) -> list[str]:
    return [
        f"code-span evidence path lacks <version>: {c}"
        for c in _evidence_codespans(text)
        if "<version>" not in c or not c.startswith("docs/evidence/")
    ]


def check_gate_ids(text: str, gates_text: str) -> list[str]:
    known = set(GATE_RE.findall(gates_text))
    return [f"unknown gate id: {g}" for g in sorted(set(GATE_RE.findall(text)) - known)]


def check_no_claims(text: str) -> list[str]:
    lowered = re.sub(r"\s+", " ", text.lower())
    return [f"compliance claim phrase: {p}" for p in CLAIM_PHRASES if p in lowered]


def _text() -> str:
    return CHECKLIST.read_text(encoding="utf-8")


def test_every_line_has_evidence_or_open() -> None:
    assert check_line_references(_text(), CHECKLIST) == []


def test_links_stay_in_evidence_or_master_index() -> None:
    assert check_link_targets(_text(), CHECKLIST) == []


def test_linked_evidence_exists() -> None:
    assert check_links_exist(_text(), CHECKLIST) == []


def test_codespan_patterns_are_per_release() -> None:
    assert check_codespan_patterns(_text()) == []


def test_gate_ids_exist_in_register() -> None:
    gates = GATES_DOC.read_text(encoding="utf-8")
    assert check_gate_ids(_text(), gates) == []


def test_no_compliance_claims() -> None:
    assert check_no_claims(_text()) == []


def test_checklist_is_not_trivial() -> None:
    text = _text()
    assert len([ln for ln in text.splitlines() if ln.startswith("- [ ]")]) >= 15
    assert "does not represent FedRAMP authorization" in text
    assert any(_is_master(t, CHECKLIST) for t in _links(text))


def test_negative_outside_link_fails(tmp_path: Path) -> None:
    f = tmp_path / "c.md"
    f.write_text("- [ ] x [bad](../../README.md)\n- [ ] y [web](https://example.com/a)\n")
    text = f.read_text()
    assert len(check_link_targets(text, f)) == 2
    assert check_line_references(text, f)


def test_negative_missing_reference_fails(tmp_path: Path) -> None:
    f = tmp_path / "c.md"
    f.write_text("- [ ] nothing here\n- [ ] ok OPEN (G02)\n")
    errors = check_line_references(f.read_text(), f)
    assert errors == ["no evidence reference or OPEN (Gxx): - [ ] nothing here"]


def test_negative_bad_codespan_and_gate_fail(tmp_path: Path) -> None:
    f = tmp_path / "c.md"
    f.write_text("- [ ] a `docs/evidence/release/v1/x.txt`\n- [ ] b OPEN (G99)\n")
    text = f.read_text()
    assert check_codespan_patterns(text)
    assert check_gate_ids(text, "G01 G02") == ["unknown gate id: G99"]


def test_negative_claim_phrase_fails(tmp_path: Path) -> None:
    f = tmp_path / "c.md"
    f.write_text("This release is FedRAMP Authorized and has compliance parity achieved.\n")
    assert len(check_no_claims(f.read_text())) == 2
    assert check_no_claims("this does not represent FedRAMP authorization or an ATO") == []
