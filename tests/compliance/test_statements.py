"""The statement checker: required sentence plus affirmative-claim rules."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest

GOOD = "Status: aid. NeuroSphere is not FedRAMP authorized; the authorizing official decides.\n"


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, body in files.items():
        p = tmp_path / "docs" / "compliance" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp_path


def test_missing_sentence_fails_and_names_file(
    checker: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _tree(tmp_path, {"a.md": GOOD, "plans/b.md": "# Plan\nNo disclaimer.\n"})
    assert checker.main(["--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "docs/compliance/plans/b.md" in out
    assert "docs/compliance/a.md" not in out


def test_sentence_present_passes(checker: ModuleType, tmp_path: Path) -> None:
    root = _tree(tmp_path, {"a.md": GOOD, "plans/b.md": "# P\n" + GOOD})
    assert checker.main(["--root", str(root)]) == 0


def test_hard_wrapped_sentence_passes(checker: ModuleType, tmp_path: Path) -> None:
    body = "NeuroSphere is not FedRAMP\nauthorized; the authorizing\nofficial decides.\n"
    assert checker.main(["--root", str(_tree(tmp_path, {"a.md": body}))]) == 0


def test_wrong_case_sentence_fails(checker: ModuleType, tmp_path: Path) -> None:
    body = "Not FedRAMP authorized; the authorizing official decides.\n"
    assert checker.main(["--root", str(_tree(tmp_path, {"a.md": body}))]) == 1


@pytest.mark.parametrize(
    "claim",
    [
        "NeuroSphere is FedRAMP authorized.",
        "The platform is FedRAMP High authorized for Government.",
        "NeuroSphere is DoD IL5 certified.",
        "NeuroSphere has been granted an ATO.",
        "The system received its ATO last year.",
        "NeuroSphere has compliance parity with Commercial.",
        "Certification date: 2027-03-01.",
        "Authorization expected in Q3.",
        "Compliance is at 87% of controls.",
        "Controls implemented: 92%.",
    ],
)
def test_affirmative_claims_fail(
    checker: ModuleType, tmp_path: Path, claim: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _tree(tmp_path, {"a.md": GOOD + "\n" + claim + "\n"})
    assert checker.main(["--root", str(root)]) == 1
    assert "a.md:" in capsys.readouterr().out


@pytest.mark.parametrize(
    "ok",
    [
        "NeuroSphere is not FedRAMP authorized.",
        "This document does not claim an ATO.",
        "NeuroSphere cannot grant an agency ATO.",
        "The authorizing official decides whether an ATO is granted.",
        "Only authorized custodians may export held data.",
        "Access is limited to authorized users and authorized connectors.",
        "A listing in an audit scope is not an authorization of this workload.",
        "No certification or authorization deadline is promised.",
        "Parity between clouds is not claimed.",
        "Fabric in GCC High has a FedRAMP High assessment in progress.",
    ],
)
def test_negated_and_neutral_forms_pass(checker: ModuleType, tmp_path: Path, ok: str) -> None:
    root = _tree(tmp_path, {"a.md": GOOD + "\n" + ok + "\n"})
    assert checker.main(["--root", str(root)]) == 0


def test_real_docs_compliance_passes(checker: ModuleType, repo_root: Path) -> None:
    assert (repo_root / "docs" / "compliance" / "responsibility-matrix.md").is_file()
    assert checker.check(repo_root) == []
