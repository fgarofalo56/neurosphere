"""PRP-44 item 1: domain registry rules."""

from __future__ import annotations

import pytest
from neurosphere_contracts.admin.v1.domain_definition import DomainDefinition
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.platform import DomainAdmin, DomainRegistry
from neurosphere_core.errors import InvalidSchemaError, StaleVersionError

from .platform_helpers import ACTOR, CONTROL, CUSTOMER, FINANCE, domain_body


def _admin() -> tuple[DomainAdmin, DomainRegistry, InMemoryAdminConfigRepository]:
    repo = InMemoryAdminConfigRepository(cloud="commercial")
    return DomainAdmin(repo, cloud="commercial"), DomainRegistry(repo), repo


def _model(**kwargs: object) -> DomainDefinition:
    return DomainDefinition.model_validate(domain_body(**kwargs))  # type: ignore[arg-type]


async def test_first_domain_registers_the_control_domain() -> None:
    admin, registry, _ = _admin()
    assert not await registry.has_any(CUSTOMER)
    write = await admin.create(CUSTOMER, _model(), updated_by=ACTOR)
    assert write.control_registered
    assert await registry.is_registered(CUSTOMER, FINANCE)
    assert await registry.is_registered(CUSTOMER, CONTROL)
    control = await admin.get(CUSTOMER, CONTROL)
    assert control is not None and control.body.is_control_domain is True  # type: ignore[union-attr]


async def test_duplicate_is_409_stale_version() -> None:
    admin, _, _ = _admin()
    await admin.create(CUSTOMER, _model(), updated_by=ACTOR)
    with pytest.raises(StaleVersionError):
        await admin.create(CUSTOMER, _model(), updated_by=ACTOR)


@pytest.mark.parametrize(
    ("domain_id", "reason"),
    [
        ("government:contoso:neurosphere:domain:x", "cross_cloud"),
        ("commercial:other:neurosphere:domain:x", "cross_customer"),
        ("commercial:contoso:neurosphere:domain:admin-config", "reserved_domain_name"),
        ("commercial:contoso:neurosphere:domain:gateway", "reserved_domain_name"),
        ("commercial:contoso:neurosphere:domain:authz-denials", "reserved_domain_name"),
        ("commercial:contoso:neurosphere:domain:read-audit", "reserved_domain_name"),
        ("commercial:contoso:neurosphere:domain:identity-admin", "reserved_domain_name"),
    ],
)
async def test_non_canonical_or_reserved_ids_are_refused(domain_id: str, reason: str) -> None:
    admin, _, _ = _admin()
    with pytest.raises(InvalidSchemaError) as caught:
        await admin.create(CUSTOMER, _model(domain_id=domain_id), updated_by=ACTOR)
    assert caught.value.reason == reason


async def test_control_flag_must_match_the_reserved_domain() -> None:
    admin, _, _ = _admin()
    with pytest.raises(InvalidSchemaError):
        await admin.create(CUSTOMER, _model(is_control_domain=True), updated_by=ACTOR)
    with pytest.raises(InvalidSchemaError):
        await admin.create(CUSTOMER, _model(domain_id=CONTROL), updated_by=ACTOR)


async def test_control_domain_can_be_created_directly_but_never_retired() -> None:
    admin, _, _ = _admin()
    write = await admin.create(
        CUSTOMER, _model(domain_id=CONTROL, is_control_domain=True), updated_by=ACTOR
    )
    assert not write.control_registered
    with pytest.raises(StaleVersionError) as caught:
        await admin.retire(CUSTOMER, CONTROL, if_match=write.document.etag.root, updated_by=ACTOR)
    assert caught.value.reason == "control_domain_protected"


async def test_retired_domain_keeps_its_record_and_stops_being_registered() -> None:
    admin, registry, _ = _admin()
    write = await admin.create(CUSTOMER, _model(), updated_by=ACTOR)
    retired = await admin.retire(
        CUSTOMER, FINANCE, if_match=write.document.etag.root, updated_by=ACTOR
    )
    assert retired.status == "retired"
    assert not await registry.is_registered(CUSTOMER, FINANCE)
    assert await admin.get(CUSTOMER, FINANCE) is not None
    assert [d.id.root for d in await admin.list(CUSTOMER)] == [CONTROL]
    assert len(await admin.list(CUSTOMER, include_retired=True)) == 2


async def test_unregistered_enforces_only_once_the_registry_is_non_empty() -> None:
    admin, registry, _ = _admin()
    assert await registry.unregistered(CUSTOMER, [FINANCE]) == []
    await admin.create(CUSTOMER, _model(), updated_by=ACTOR)
    other = "commercial:contoso:neurosphere:domain:ops"
    assert await registry.unregistered(CUSTOMER, [FINANCE, other, other]) == [other]
