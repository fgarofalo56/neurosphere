"""PRP-44 item 1: review policy conversion, safety rules, diff and loadable registry."""

from __future__ import annotations

from datetime import timedelta

import pytest
from neurosphere_contracts.admin.v1.review_policy_document import ReviewPolicyDocument
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.platform import (
    DEFAULTS_ETAG,
    LoadableReviewPolicyRegistry,
    PolicyAlreadyLoadedError,
    ReviewPolicyAdmin,
    defaults_document,
    policies_from_document,
)
from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.errors import InvalidSchemaError, StaleVersionError
from neurosphere_core.hitl import ReviewPolicyRegistry
from neurosphere_core.hitl.policy import default_policies
from pydantic import ValidationError

from .platform_helpers import ACTOR, CUSTOMER, policy_body, policy_settings


def _doc(**kwargs: object) -> ReviewPolicyDocument:
    return ReviewPolicyDocument.model_validate(policy_body(**kwargs))  # type: ignore[arg-type]


def test_document_converts_to_registry_inputs() -> None:
    stored = policies_from_document(_doc())
    policy = stored.kind_defaults["maker_checker"]
    assert policy.sla == timedelta(hours=1) and policy.max_escalations == 3
    assert policy.approver_permission is Permission.ACTION_APPROVE
    assert stored.kind_defaults["relationship"].approver_permission is Permission.CATALOG_CURATE


def test_defaults_document_round_trips_to_default_policies() -> None:
    stored = policies_from_document(defaults_document())
    expected = default_policies()
    assert {
        k: p.model_dump(exclude={"policy_version"}) for k, p in stored.kind_defaults.items()
    } == {k: p.model_dump(exclude={"policy_version"}) for k, p in expected.items()}


@pytest.mark.parametrize(
    "settings",
    [
        policy_settings(self_approval_forbidden=False),
        policy_settings(approver_permission="catalog.curate"),
    ],
)
def test_maker_checker_can_never_be_loosened(settings: dict[str, object]) -> None:
    with pytest.raises(InvalidSchemaError) as caught:
        policies_from_document(_doc(maker_checker=settings))
    assert caught.value.reason == "maker_checker_loosened"


def test_maker_checker_override_cannot_loosen_either() -> None:
    override = {
        "review_kind": "maker_checker",
        "action_kind": "swap_model",
        "policy": policy_settings(self_approval_forbidden=False),
    }
    with pytest.raises(InvalidSchemaError):
        policies_from_document(_doc(action_overrides=[override]))


def test_sla_under_a_minute_is_refused_and_contract_bounds_hold() -> None:
    with pytest.raises(InvalidSchemaError) as caught:
        policies_from_document(_doc(maker_checker=policy_settings(sla_seconds=59)))
    assert caught.value.reason == "sla_too_short"
    for bad in (
        policy_settings(expiry_seconds=7776001),
        policy_settings(max_escalations=11),
        policy_settings(sla_seconds=0),
        policy_settings(approver_permission="not.a.permission"),
    ):
        with pytest.raises(ValidationError):
            _doc(maker_checker=bad)


async def test_get_defaults_then_put_requires_the_matching_etag_and_returns_a_diff() -> None:
    admin = ReviewPolicyAdmin(InMemoryAdminConfigRepository(cloud="commercial"))
    read = await admin.get(CUSTOMER)
    assert read.source == "defaults" and read.etag == DEFAULTS_ETAG
    with pytest.raises(StaleVersionError):
        await admin.replace(CUSTOMER, _doc(), if_match='"nope"', updated_by=ACTOR)
    write = await admin.replace(CUSTOMER, _doc(), if_match=read.etag, updated_by=ACTOR)
    assert write.after.policy_version == "admin-v1"
    assert any(
        c.path == "kind_defaults/maker_checker/sla_seconds" and (c.before, c.after) == (86400, 3600)
        for c in write.changes
    )
    again = await admin.get(CUSTOMER)
    assert again.source == "stored" and again.version == 1
    second = await admin.replace(
        CUSTOMER, _doc(), if_match=write.stored.etag.root, updated_by=ACTOR
    )
    assert second.after.policy_version == "admin-v2" and second.changes == ()
    with pytest.raises(StaleVersionError):
        await admin.replace(CUSTOMER, _doc(), if_match=write.stored.etag.root, updated_by=ACTOR)


async def test_registry_without_stored_policy_equals_the_defaults() -> None:
    registry = LoadableReviewPolicyRegistry()
    assert not await registry.load_from(InMemoryAdminConfigRepository(), CUSTOMER)
    plain = ReviewPolicyRegistry()
    for kind in default_policies():
        assert registry.resolve(kind) == plain.resolve(kind)


async def test_registry_applies_the_stored_policy_once() -> None:
    repo = InMemoryAdminConfigRepository(cloud="commercial")
    admin = ReviewPolicyAdmin(repo)
    await admin.replace(CUSTOMER, _doc(), if_match=DEFAULTS_ETAG, updated_by=ACTOR)
    registry = LoadableReviewPolicyRegistry()
    assert await registry.load_from(repo, CUSTOMER)
    assert registry.resolve("maker_checker").sla == timedelta(hours=1)
    assert registry.resolve("maker_checker").policy_version == "admin-v1"
    with pytest.raises(PolicyAlreadyLoadedError):
        await registry.load_from(repo, CUSTOMER)


async def test_a_failed_read_leaves_the_registry_unloaded_with_defaults() -> None:
    repo = InMemoryAdminConfigRepository()
    repo.fail_with(RuntimeError("down"))
    registry = LoadableReviewPolicyRegistry()
    with pytest.raises(RuntimeError):
        await registry.load_from(repo, CUSTOMER)
    assert not registry.loaded
    assert registry.resolve("maker_checker") == ReviewPolicyRegistry().resolve("maker_checker")
