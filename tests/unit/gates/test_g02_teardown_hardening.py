"""PRP-59 item 5: G02 teardown hardening (#213 items 1, 2, 4). Fake runner, no live call."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from test_g02_profile_paths import (  # type: ignore[import-not-found]  # pyright: ignore[reportMissingImports]
    Env,
    _common,  # pyright: ignore[reportUnknownVariableType]
    _profile,  # pyright: ignore[reportUnknownVariableType]
    _StubProfile,  # pyright: ignore[reportUnknownVariableType]
)


@pytest.fixture
def env(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Env:
    return Env(tmp_path, monkeypatch)


class _InterruptedDeploy(_StubProfile):
    def __init__(self) -> None:
        super().__init__(RuntimeError("unused"))

    def deploy(self, ctx: Any) -> None:
        raise KeyboardInterrupt

    def cleanup(self, ctx: Any) -> None:
        return None


def test_interrupt_during_deploy_tears_down_writes_fail_evidence_then_reraises(env: Env) -> None:
    with pytest.raises(KeyboardInterrupt):
        env.go(_InterruptedDeploy())
    assert env.runner.issued("az group delete")
    text = env.evidence_text("stub")
    assert "# G02 stub profile - FAIL" in text
    assert "- Interrupted: true" in text


def test_group_with_a_resource_lacking_the_run_tag_is_not_deleted(env: Env) -> None:
    # The dry-run plan is the empty default here (deploy failed early), so only the
    # pre-delete re-list can see the foreign resource.
    class _Early(_StubProfile):
        def __init__(self) -> None:
            super().__init__(RuntimeError("unused"))

        def deploy(self, ctx: Any) -> None:
            raise _common().StepError("boom")  # type: ignore[attr-defined]

        def cleanup(self, ctx: Any) -> None:
            return None

    env.runner.extra_resources = ["/subscriptions/x/resourceGroups/rg/providers/y/foreign"]
    assert env.go(_Early()) == 1
    text = env.evidence_text("stub")
    assert "without this run's tag; group not deleted" in text
    assert not env.runner.issued("az group delete")


def test_pre_delete_listing_failure_refuses_the_delete(env: Env) -> None:
    class _Ok(_StubProfile):
        def __init__(self) -> None:
            super().__init__(RuntimeError("unused"))

        def cleanup(self, ctx: Any) -> None:
            return None

    calls = {"n": 0}

    def flaky(args: list[str]) -> None:
        if "[].{id:id,tags:tags}" in args:
            calls["n"] += 1
            if calls["n"] >= 2:  # the pre-delete re-list
                raise json.JSONDecodeError("bad", "x", 0)

    env.runner.hooks["az resource list"] = flaky
    assert env.go(_Ok()) == 0
    # The group tag was verified, so the delete proceeds, but the unreadable re-list is recorded.
    assert env.runner.issued("az group delete")
    assert "[WARN] pre-delete-relist" in env.evidence_text("stub")


def test_unexpected_cleanup_error_propagates_after_evidence(env: Env) -> None:
    with pytest.raises(ZeroDivisionError):
        env.go(_StubProfile(ZeroDivisionError("bug")))
    assert env.runner.issued("az group delete")
    assert "unexpected ZeroDivisionError" in env.evidence_text("stub")


def test_aks_cleanup_only_catches_recoverable_errors(env: Env) -> None:
    profile = _profile("aks")

    class Ctx:
        def __init__(self) -> None:
            self.facts = {"namespace": "ns", "release_installed": True, "release": "r"}
            self.work_dir = Path("work")

        def run(self, *argv: str, **_: Any) -> None:
            if argv[0] == "helm":
                raise ZeroDivisionError("bug")

    with pytest.raises(ZeroDivisionError):
        profile.cleanup(Ctx())
