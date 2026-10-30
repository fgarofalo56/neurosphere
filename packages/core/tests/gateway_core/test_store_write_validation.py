"""Gateway stores validate a registration before writing it (PRP-34 item 2 review hand-off).

``model_copy(update=...)`` skips pydantic validators, so without a check before the write a
caller could persist ``manage`` mode without the audited switch and a passed preflight.
"""

from __future__ import annotations

from typing import Any

import pytest
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.gateway import (
    CosmosGatewayStore,
    GatewayRegistration,
    InMemoryGatewayStore,
    gateway_id_for,
)
from neurosphere_core.gateway.store import validated

from .fake_arm import RID
from .test_models_and_stores import CUSTOMER, DOMAIN, T0


def _registration() -> GatewayRegistration:
    return GatewayRegistration(
        id=gateway_id_for(CUSTOMER, DOMAIN, RID),
        customer_id=CUSTOMER,
        domain_id=DOMAIN,
        cloud="commercial",
        arm_resource_id=RID,
        name="apim-demo",
        tier="standard_v2",
        created_at=T0,
        updated_at=T0,
        registered_by="pseudo-abc",
    )


def _forged_manage(registration: GatewayRegistration) -> GatewayRegistration:
    # No preflight, no audited switch: the model forbids it, model_copy does not check.
    return registration.model_copy(update={"mode": "manage"})


class RecordingContainer:
    def __init__(self) -> None:
        self.writes: list[str] = []

    async def create_item(self, body: dict[str, Any]) -> dict[str, Any]:
        self.writes.append("create")
        return {**body, "_etag": '"1"'}

    async def replace_item(self, item: str, body: dict[str, Any], **_: Any) -> dict[str, Any]:
        self.writes.append("replace")
        return {**body, "_etag": '"2"'}


def test_validated_refuses_a_forged_document() -> None:
    good = _registration()
    assert validated(good) == good
    with pytest.raises(InvalidSchemaError) as info:
        validated(_forged_manage(good))
    assert info.value.reason == "gateway_registration_invalid"


async def test_in_memory_create_and_replace_refuse_before_writing() -> None:
    store = InMemoryGatewayStore()
    with pytest.raises(InvalidSchemaError):
        await store.create(_forged_manage(_registration()))
    assert await store.get(CUSTOMER, DOMAIN, _registration().id) is None
    saved = await store.create(_registration())
    with pytest.raises(InvalidSchemaError):
        await store.replace(_forged_manage(saved), if_match=saved.etag or "")
    current = await store.get(CUSTOMER, DOMAIN, saved.id)
    assert current is not None and current.mode == "observe" and current.etag == saved.etag


async def test_cosmos_create_and_replace_refuse_before_writing() -> None:
    container = RecordingContainer()
    store = CosmosGatewayStore(container)  # type: ignore[arg-type]
    with pytest.raises(InvalidSchemaError):
        await store.create(_forged_manage(_registration()))
    with pytest.raises(InvalidSchemaError):
        await store.replace(_forged_manage(_registration()), if_match='"1"')
    assert container.writes == []
    saved = await store.create(_registration())
    assert saved.mode == "observe" and container.writes == ["create"]
