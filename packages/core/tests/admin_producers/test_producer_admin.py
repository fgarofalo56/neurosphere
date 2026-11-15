"""PRP-41 item 1: producer administration over the in-memory admin_config store."""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_contracts.admin.v1.producer_record import ProducerRecord
from neurosphere_core.admin import InMemoryAdminConfigRepository
from neurosphere_core.admin.producers import (
    ProducerAdmin,
    ProducerResult,
    registration_from_record,
    secret_digest,
)
from neurosphere_core.errors import (
    ForbiddenError,
    InvalidSchemaError,
    NotFoundError,
    StaleVersionError,
)

CUSTOMER = "contoso"
ACTOR = "commercial:contoso:entra:person:p-" + "0c" * 32
SOURCES: Any = {"gw-1": "gateway", "bill-1": "billing"}


def make() -> tuple[ProducerAdmin, InMemoryAdminConfigRepository]:
    repo = InMemoryAdminConfigRepository(cloud="commercial")
    return ProducerAdmin(repo, cloud="commercial"), repo


async def create(admin: ProducerAdmin, pid: str = "poller-1") -> ProducerResult:
    return await admin.create(CUSTOMER, pid, cloud="commercial", sources=SOURCES, updated_by=ACTOR)


async def test_create_stores_digest_only_and_returns_secret_once() -> None:
    admin, repo = make()
    result = await create(admin)
    assert result.issued is not None
    secret = result.issued.secret
    stored = await repo.get(CUSTOMER, "producer", "poller-1")
    assert stored is not None
    body = stored.body
    assert isinstance(body, ProducerRecord)
    assert body.secret_sha256 == secret_digest(secret)
    assert secret not in stored.model_dump_json()
    assert body.status == "active"
    again = await admin.get(CUSTOMER, "poller-1")
    assert secret not in again.model_dump_json()


async def test_duplicate_id_raises() -> None:
    admin, _ = make()
    await create(admin)
    with pytest.raises(StaleVersionError):
        await create(admin)


async def test_cross_cloud_and_customer_refused_before_write() -> None:
    admin, repo = make()
    with pytest.raises(InvalidSchemaError) as cloud:
        await admin.create(CUSTOMER, "p1", cloud="government", sources=SOURCES, updated_by=ACTOR)
    assert cloud.value.reason == "cross_cloud"
    with pytest.raises(ForbiddenError):
        await admin.create(
            CUSTOMER,
            "p1",
            cloud="commercial",
            sources=SOURCES,
            updated_by=ACTOR,
            requested_customer_id="fabrikam",
        )
    assert await repo.list_by_kind(CUSTOMER, "producer") == []


async def test_rotate_replaces_digest_and_requires_current_etag() -> None:
    admin, _ = make()
    first = await create(admin)
    etag = first.document.etag.root
    rotated = await admin.rotate(CUSTOMER, "poller-1", if_match=etag, updated_by=ACTOR)
    assert rotated.issued is not None and first.issued is not None
    assert rotated.issued.secret != first.issued.secret
    body = rotated.document.body
    assert isinstance(body, ProducerRecord)
    assert body.secret_sha256 == rotated.issued.sha256
    with pytest.raises(StaleVersionError):
        await admin.rotate(CUSTOMER, "poller-1", if_match=etag, updated_by=ACTOR)


async def test_disable_enable_and_missing() -> None:
    admin, _ = make()
    created = await create(admin)
    off = await admin.set_status(
        CUSTOMER, "poller-1", "disabled", if_match=created.document.etag.root, updated_by=ACTOR
    )
    assert isinstance(off.document.body, ProducerRecord)
    assert off.document.body.status == "disabled"
    assert off.issued is None
    on = await admin.set_status(
        CUSTOMER, "poller-1", "active", if_match=off.document.etag.root, updated_by=ACTOR
    )
    assert isinstance(on.document.body, ProducerRecord)
    assert on.document.body.secret_sha256 == off.document.body.secret_sha256
    with pytest.raises(NotFoundError):
        await admin.get(CUSTOMER, "nope")


async def test_registration_shape() -> None:
    admin, _ = make()
    result = await create(admin)
    assert isinstance(result.document.body, ProducerRecord)
    reg = registration_from_record(result.document.body)
    assert reg["sources"] == {"bill-1": "billing", "gw-1": "gateway"}
    assert reg["customer_id"] == CUSTOMER and reg["cloud"] == "commercial"
