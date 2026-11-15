"""PRP-44 item 5: the worker roles resolve review policy from the store, else the defaults."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import pytest
from neurosphere_contracts.admin.v1.review_policy_document import ReviewPolicyDocument
from neurosphere_core.admin.platform import DEFAULTS_ETAG, ReviewPolicyAdmin
from neurosphere_core.hitl import ReviewPolicyRegistry
from neurosphere_workers.admin_platform import POLICY_STORE_UNAVAILABLE, load_review_policies
from neurosphere_workers.admin_platform import policy as module

from .support import ACTOR, CUSTOMER, repo, runtime_config


def _settings(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "self_approval_forbidden": True,
        "approver_permission": "action.approve",
        "assignment_timeout_seconds": 14400,
        "sla_seconds": 1800,
        "escalation_step_seconds": 7200,
        "max_escalations": 1,
        "expiry_seconds": 86400,
    }
    base.update(over)
    return base


def _document() -> ReviewPolicyDocument:
    return ReviewPolicyDocument.model_validate(
        {
            "schema_version": "1.0.0",
            "policy_version": "x",
            "kind_defaults": [{"review_kind": "maker_checker", "policy": _settings()}],
            "action_overrides": [],
        }
    )


def _use(monkeypatch: pytest.MonkeyPatch, repository: Any) -> None:
    class _Fake:
        @staticmethod
        def from_client(*_: object, **__: object) -> Any:
            return repository

    monkeypatch.setattr(module, "CosmosAdminConfigRepository", _Fake)


async def test_stored_policy_wins_over_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = repo()
    await ReviewPolicyAdmin(repository).replace(
        CUSTOMER, _document(), if_match=DEFAULTS_ETAG, updated_by=ACTOR
    )
    _use(monkeypatch, repository)
    registry = await load_review_policies(runtime_config(), object())
    policy = registry.resolve("maker_checker")
    assert policy.sla == timedelta(minutes=30) and policy.max_escalations == 1
    assert policy.policy_version == "admin-v1"


async def test_no_stored_policy_equals_the_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, repo())
    registry = await load_review_policies(runtime_config(), object())
    plain = ReviewPolicyRegistry()
    for kind in ("maker_checker", "relationship", "evaluation_dispute", "recommendation"):
        assert registry.resolve(kind) == plain.resolve(kind)
    assert registry.loaded


async def test_a_read_failure_keeps_the_defaults_with_one_reason_coded_line(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    repository = repo()
    repository.fail_with(RuntimeError("boom"))
    _use(monkeypatch, repository)
    with caplog.at_level(logging.INFO, logger="neurosphere_workers.admin_platform"):
        registry = await load_review_policies(runtime_config(), object())
    assert registry.resolve("maker_checker") == ReviewPolicyRegistry().resolve("maker_checker")
    lines = [r for r in caplog.records if getattr(r, "reason", None) == POLICY_STORE_UNAVAILABLE]
    assert len(lines) == 1 and "boom" not in caplog.text


async def test_the_loaded_registry_cannot_be_loaded_again(monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, repo())
    registry = await load_review_policies(runtime_config(), object())
    with pytest.raises(RuntimeError):
        registry.load(None)
