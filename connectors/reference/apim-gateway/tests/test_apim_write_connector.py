"""Connector shape: manifest, registry, Government refusal, target checks, translator seam."""

from __future__ import annotations

from typing import get_args

import pytest
from apim_write_support import (  # pyright: ignore[reportMissingImports]
    GATEWAY,
    GOV_GATEWAY,
    PUBLICATION,
    make,
    publication_ops,
    request,
    target,
    upsert,
)
from neurosphere_connector.manifest import WriteAction
from neurosphere_connector.write import WriteConnector, WriteRequest, WriteTargetRegistry
from neurosphere_connector_apim_gateway import (
    ACTION_KINDS,
    ADVISORY_CONNECTOR_NAME,
    CONNECTOR_NAME,
    ApimArm,
    ApimGatewayAdvisoryConnector,
    ApimGatewayConnector,
    InMemoryApim,
    InMemoryApplyRecordStore,
    ResourceSpec,
    ResourceType,
    create_apim_connector,
    manifest_actions,
)
from neurosphere_connector_apim_gateway.connector import GOVERNMENT_ROW
from neurosphere_connector_apim_gateway.gateway import GatewayRef
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.capabilities.validate import default_matrix
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError


def test_action_kinds_are_the_prp_34_set() -> None:
    assert ACTION_KINDS == (
        "model_deployment_swap",
        "budget_cap_change",
        "grant_publish",
        "grant_unpublish",
        "mcp_server_publish",
        "mcp_server_unpublish",
    )


async def test_registers_as_write_target() -> None:
    conn, _, _ = make()
    assert isinstance(conn, WriteConnector)
    assert conn.advisory is False
    assert conn.manifest.name == CONNECTOR_NAME
    assert conn.manifest.advisory is False
    assert conn.manifest.write_support.actions == manifest_actions()
    registry = WriteTargetRegistry()
    registry.register(conn)
    for kind in manifest_actions():
        assert registry.supports(CONNECTOR_NAME, kind)


def test_manifest_lists_every_kind_the_contract_admits() -> None:
    allowed = set(get_args(WriteAction))
    assert manifest_actions() == [k for k in ACTION_KINDS if k in allowed]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "connector-manifest contract enum (write_support.actions) does not yet admit "
        "budget_cap_change, grant_publish, grant_unpublish, mcp_server_publish, "
        "mcp_server_unpublish; a contract change outside item 1 is needed"
    ),
)
def test_manifest_declares_all_prp_34_kinds() -> None:
    conn, _, _ = make()
    assert conn.manifest.write_support.actions == list(ACTION_KINDS)


def test_inmemory_double_satisfies_the_arm_protocol() -> None:
    assert isinstance(InMemoryApim(), ApimArm)


async def test_government_gateway_gets_the_advisory_connector_with_reason() -> None:
    conn = create_apim_connector(GOV_GATEWAY, InMemoryApim(), records=InMemoryApplyRecordStore())
    assert isinstance(conn, ApimGatewayAdvisoryConnector)
    assert conn.advisory is True
    assert conn.manifest.name == ADVISORY_CONNECTOR_NAME
    row = default_matrix().by_id(GOVERNMENT_ROW)
    assert row is not None and row.availability != "available"
    assert conn.reason == row.notes
    registry = WriteTargetRegistry()
    with pytest.raises(CapabilityUnavailableError):
        registry.register(conn)
    with pytest.raises(CapabilityUnavailableError):
        await conn.dry_run(request(*publication_ops(), tgt=target("government")))


async def test_commercial_factory_returns_the_write_connector() -> None:
    conn = create_apim_connector(GATEWAY, InMemoryApim(), records=InMemoryApplyRecordStore())
    assert isinstance(conn, ApimGatewayConnector)


async def test_write_connector_bound_to_government_refuses_every_method() -> None:
    apim = InMemoryApim(service_etag='"svc-1"')
    conn = ApimGatewayConnector(GOV_GATEWAY, apim, records=InMemoryApplyRecordStore())
    req = request(*publication_ops(), tgt=target("government"))
    for call in (conn.dry_run, conn.apply, conn.verify):
        with pytest.raises(CapabilityUnavailableError) as err:
            await call(req)
        assert err.value.reason == "gateway_manage_unavailable"
    assert apim.calls == []


@pytest.mark.parametrize(
    ("tgt", "reason"),
    [
        (target("government"), "cloud_mismatch"),
        (target(gateway_id="gw-" + "b" * 32), "wrong_entity"),
        (
            TargetRef(canonical_id="commercial:cust1:apim:grant:g1", entity_type="grant"),
            "wrong_entity",
        ),
    ],
)
async def test_wrong_targets_are_refused(tgt: TargetRef, reason: str) -> None:
    conn, apim, _ = make()
    with pytest.raises(InvalidSchemaError) as err:
        await conn.dry_run(request(*publication_ops(), tgt=tgt))
    assert err.value.reason == reason
    assert apim.writes() == []


async def test_empty_diff_is_refused() -> None:
    conn, _, _ = make()
    with pytest.raises(InvalidSchemaError) as err:
        await conn.dry_run(request(("test", "/plan_digest", "0" * 64)))
    assert err.value.reason == "empty_plan"


class _GrantTranslator:
    """A later item's translator: a different target kind mapped onto the same planner."""

    @property
    def entity_types(self) -> frozenset[str]:
        return frozenset({"grant"})

    async def current_version(
        self, arm: ApimArm, gateway: GatewayRef, request: WriteRequest
    ) -> str:
        current = await arm.get("products/ns-grant-g1")
        return current.etag if current and current.etag else "absent"

    def specs(self, gateway: GatewayRef, request: WriteRequest) -> list[ResourceSpec]:
        return [
            ResourceSpec(
                resource_type=ResourceType.PRODUCT,
                name="products/ns-grant-g1",
                payload=PUBLICATION["products/ns-grant-g1"],
            )
        ]


async def test_translator_seam_lets_later_items_add_target_kinds() -> None:
    conn, apim, _ = make()
    conn.register_translator(_GrantTranslator())
    req = request(
        upsert("products/ns-grant-g1", {}),
        version="absent",
        tgt=TargetRef(canonical_id="commercial:cust1:apim:grant:g1", entity_type="grant"),
    )
    dry = await conn.dry_run(req)
    applied = await conn.apply(req.model_copy(update={"proposed_diff": dry.planned_diff}))
    assert applied.version_after == apim.etag_of("products/ns-grant-g1")
    assert (await conn.rollback(applied)).status == "rolled_back"
    assert apim.snapshot() == {}
