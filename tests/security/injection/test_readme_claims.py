"""The README's stub notes stay true (PRP-48 item 6, #70)."""

from __future__ import annotations

from pathlib import Path

from .schema import Escalate, FollowInstruction, load_corpus
from .stubs import _holds  # pyright: ignore[reportPrivateUsage]

README = Path(__file__).with_name("README.md").read_text(encoding="utf-8")


def test_follow_instruction_abstain_count_matches_the_readme() -> None:
    cases = load_corpus()
    follow = [c for c in cases if isinstance(c.attempt, FollowInstruction)]
    assert all(c.expected == "abstain" for c in follow)
    assert f"{len(follow)} of the {len(cases)} cases" in " ".join(README.split())


def test_no_escalate_case_targets_a_held_permission() -> None:
    """The stub's comply-on-held branch is documented as never hit by the corpus."""
    for case in load_corpus():
        attempt = case.attempt
        if isinstance(attempt, Escalate):
            assert case.expected == "deny", case.id
            assert not _holds(case.scope, attempt.permission, attempt.target_domain_id), case.id


def test_readme_names_the_consumer_suites() -> None:
    root = Path(__file__).resolve().parents[3]
    for suite in (
        "services/api/tests/copilot_api/test_orchestrator_injection.py",
        "tests/security/mcp/test_injection_via_tool_output.py",
    ):
        assert suite in README
        assert (root / suite).is_file(), suite
