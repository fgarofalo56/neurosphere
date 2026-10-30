"""``gateway_mode_change`` and the observe-mode guard on the APIM connector (PRP-34 item 2)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from apim_write_support import (  # pyright: ignore[reportMissingImports]
    ARM_ID,
    GATEWAY,
    GATEWAY_ID,
    SERVICE_ETAG,
    mode_handler,
    publication_ops,
    request,
)
from neurosphere_connector.write import WriteRequest, WriteTargetRegistry
from neurosphere_connector_apim_gateway import (
    CONNECTOR_NAME,
    MODE_TARGET_TYPE,
    PERMISSIONS_PATH,
    ApimGatewayConnector,
    ApimPermissionsReader,
    ApplyRecord,
    GatewayModeHandler,
    GatewayRef,
    HttpApimArm,
    InMemoryApim,
)
from neurosphere_contracts.actions.v1.action_intent import ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    InvalidSchemaError,
    StaleVersionError,
)
from neurosphere_core.gateway import (
    GatewayRegistration,
    InMemoryGatewayRecordStore,
    InMemoryGatewayStore,
)
from neurosphere_core.gateway.mode import (
    GATEWAY_APPLYING,
    GATEWAY_OBSERVE_MODE,
    GATEWAY_PREFLIGHT_FAILED,
    GatewayModeSwitch,
    mode_change_diff,
    mode_target,
    mode_target_version,
)

T0 = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
CUSTOMER = "cust1"
DOMAIN = "commercial:cust1:catalog:domain:ai"
MAKER = "pn-maker-0001"
READER: list[dict[str, Any]] = [{"actions": ["*/read"], "notActions": []}]


class Env:
    def __init__(self, apim: InMemoryApim, store: InMemoryGatewayStore) -> None:
        self.apim = apim
        self.store = store
        self.records: InMemoryGatewayRecordStore[ApplyRecord] = InMemoryGatewayRecordStore(
            ApplyRecord
        )
        switch = GatewayModeSwitch(
            store,
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
            gateway_id=GATEWAY_ID,
            activity=self.records,
            clock=lambda: T0,
        )
        self.mode = GatewayModeHandler(GATEWAY, apim, switch)
        counter = iter(range(1, 1000))
        self.conn = ApimGatewayConnector(
            GATEWAY,
            apim,
            records=self.records,
            id_factory=lambda: f"apply-{next(counter)}",
            mode=self.mode,
        )

    async def registration(self) -> GatewayRegistration:
        found = await self.store.get(CUSTOMER, DOMAIN, GATEWAY_ID)
        assert found is not None
        return found

    async def mode_request(self, desired: str, *, by: str = MAKER) -> WriteRequest:
        registration = await self.registration()
        return WriteRequest(
            target=TargetRef.model_validate(mode_target(registration)),
            target_version=mode_target_version(registration),
            proposed_diff=ProposedDiff.model_validate(
                {"format": "json_patch", "operations": mode_change_diff(desired, by)}  # type: ignore[arg-type]
            ),
        )

    async def to_manage(self) -> None:
        applied = await self.conn.apply(await self.mode_request("manage"))
        assert applied.version_after == "mode-r1-manage"


async def _env(permissions: list[dict[str, Any]] | None = None) -> Env:
    apim = InMemoryApim(service_etag=SERVICE_ETAG)
    if permissions is not None:
        apim.permission_entries = permissions
    store = InMemoryGatewayStore()
    await store.create(
        GatewayRegistration(
            id=GATEWAY_ID,
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
            cloud="commercial",
            arm_resource_id=ARM_ID,
            name="apim-demo",
            tier="standard_v2",
            created_at=T0,
            updated_at=T0,
            registered_by="pn-admin",
        )
    )
    return Env(apim, store)


async def _reviewed(conn: ApimGatewayConnector, req: WriteRequest) -> WriteRequest:
    result = await conn.dry_run(req)
    return req.model_copy(update={"proposed_diff": result.planned_diff})


def test_mode_change_is_a_declared_write_action() -> None:
    registry = WriteTargetRegistry()
    apim = InMemoryApim()
    registry.register(
        ApimGatewayConnector(
            GATEWAY,
            apim,
            records=InMemoryGatewayRecordStore(ApplyRecord),
            mode=mode_handler(apim),
        )
    )
    assert registry.supports(CONNECTOR_NAME, "gateway_mode_change")
    assert MODE_TARGET_TYPE == "apim_gateway_mode"
    assert isinstance(apim, ApimPermissionsReader)


async def test_dry_run_runs_the_preflight_and_writes_nothing() -> None:
    env = await _env()
    req = await env.mode_request("manage")
    result = await env.conn.dry_run(req)
    assert result.would_change is True
    assert result.planned_diff == req.proposed_diff
    assert [c.path for c in env.apim.calls] == [PERMISSIONS_PATH]
    assert env.apim.writes() == []
    assert (await env.registration()).mode == "observe"


async def test_denied_write_fails_the_preflight_on_dry_run_and_apply() -> None:
    env = await _env(READER)
    req = await env.mode_request("manage")
    with pytest.raises(CapabilityUnavailableError) as dry:
        await env.conn.dry_run(req)
    assert dry.value.reason == GATEWAY_PREFLIGHT_FAILED
    with pytest.raises(CapabilityUnavailableError) as applied:
        await env.conn.apply(req)
    assert applied.value.reason == GATEWAY_PREFLIGHT_FAILED
    registration = await env.registration()
    assert registration.mode == "observe"
    assert registration.mode_revision == 0
    assert env.apim.writes() == []


async def test_apply_flips_verify_reads_back_and_rollback_restores() -> None:
    env = await _env()
    req = await env.mode_request("manage")
    applied = await env.conn.apply(req)
    assert applied.version_before == "mode-r0-observe"
    assert applied.version_after == "mode-r1-manage"
    registration = await env.registration()
    assert registration.mode == "manage"
    assert registration.mode_changed_by == MAKER
    assert registration.preflight is not None and registration.preflight.passed
    verified = await env.conn.verify(req)
    assert verified.matched
    assert verified.observed_version == "mode-r1-manage"
    rolled = await env.conn.rollback(applied)
    assert rolled.status == "rolled_back"
    assert (await env.registration()).mode == "observe"
    assert env.apim.writes() == []  # the gateway itself is never written by a mode change


async def test_verify_reports_a_mismatch_when_the_flip_did_not_land() -> None:
    env = await _env()
    req = await env.mode_request("manage")
    verified = await env.conn.verify(req)
    assert not verified.matched
    assert "/mode" in verified.mismatched_paths


async def test_rollback_after_a_later_switch_is_not_needed() -> None:
    env = await _env()
    applied = await env.conn.apply(await env.mode_request("manage"))
    await env.conn.apply(await env.mode_request("observe"))
    assert (await env.conn.rollback(applied)).status == "not_needed"
    assert (await env.registration()).mode == "observe"


async def test_mode_change_is_refused_while_a_plan_is_applying() -> None:
    env = await _env()
    await env.records.append(
        ApplyRecord(
            id="apply-x",
            gateway_id=GATEWAY_ID,
            target="commercial:cust1:apim:apim_gateway:" + GATEWAY_ID,
            plan_digest="0" * 64,
            status="applying",
        )
    )
    req = await env.mode_request("manage")
    with pytest.raises(CapabilityUnavailableError) as info:
        await env.conn.dry_run(req)
    assert info.value.reason == GATEWAY_APPLYING
    with pytest.raises(CapabilityUnavailableError):
        await env.conn.apply(req)
    assert (await env.registration()).mode == "observe"


async def test_stale_or_foreign_mode_requests_are_refused() -> None:
    env = await _env()
    req = await env.mode_request("manage")
    with pytest.raises(StaleVersionError):
        await env.conn.dry_run(req.model_copy(update={"target_version": "mode-r9-observe"}))
    other = req.model_copy(
        update={
            "target": TargetRef(
                canonical_id=f"commercial:cust1:apim:apim_gateway_mode:gw-{'b' * 32}",
                entity_type=MODE_TARGET_TYPE,
            )
        }
    )
    with pytest.raises(InvalidSchemaError):
        await env.conn.dry_run(other)


async def test_resource_plans_are_refused_in_observe_mode() -> None:
    env = await _env()
    with pytest.raises(CapabilityUnavailableError) as info:
        await env.conn.dry_run(request(*publication_ops()))
    assert info.value.reason == GATEWAY_OBSERVE_MODE
    assert env.apim.calls == []


async def test_switching_back_to_observe_leaves_published_resources_serving() -> None:
    env = await _env()
    await env.to_manage()
    reviewed = await _reviewed(env.conn, request(*publication_ops()))
    await env.conn.apply(reviewed)
    published = env.apim.snapshot()
    assert "apis/llm" in published
    writes_before = len(env.apim.writes())
    await env.conn.apply(await env.mode_request("observe"))
    assert (await env.registration()).mode == "observe"
    assert env.apim.snapshot() == published
    assert len(env.apim.writes()) == writes_before
    for call in (env.conn.dry_run, env.conn.apply):
        with pytest.raises(CapabilityUnavailableError) as info:
            await call(reviewed)
        assert info.value.reason == GATEWAY_OBSERVE_MODE
    # An unpublish (delete plan) is refused the same way.
    unpublish = request(("remove", "/resources/apis~1llm", None))
    with pytest.raises(CapabilityUnavailableError) as refused:
        await env.conn.dry_run(unpublish)
    assert refused.value.reason == GATEWAY_OBSERVE_MODE
    assert env.apim.snapshot() == published


async def test_a_connector_without_a_mode_handler_is_refused() -> None:
    # PRP-34 item 2 review: a missing handler would skip the observe guard (fail-open).
    env = await _env()
    with pytest.raises(TypeError):
        ApimGatewayConnector(GATEWAY, env.apim, records=env.records, mode=None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ApimGatewayConnector(GATEWAY, env.apim, records=env.records)  # type: ignore[call-arg]
    assert env.apim.calls == []


async def test_handler_must_match_the_connector_gateway() -> None:
    env = await _env()
    other = GatewayRef(
        gateway_id="gw-" + "b" * 32, cloud=CloudName.COMMERCIAL, arm_resource_id=ARM_ID
    )
    with pytest.raises(ValueError):
        ApimGatewayConnector(other, env.apim, records=env.records, mode=env.mode)
    with pytest.raises(ValueError):
        GatewayModeHandler(
            other,
            env.apim,
            GatewayModeSwitch(
                env.store,
                customer_id=CUSTOMER,
                domain_id=DOMAIN,
                gateway_id=GATEWAY_ID,
                activity=env.records,
            ),
        )


# -- HttpApimArm.permissions ---------------------------------------------------------------------

Handler = Callable[[httpx.Request], httpx.Response]


def _http(handler: Handler) -> tuple[HttpApimArm, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return handler(req)

    client = httpx.AsyncClient(
        base_url="https://management.azure.com", transport=httpx.MockTransport(record)
    )
    return HttpApimArm(client, ARM_ID), seen


async def test_permissions_is_one_get_at_the_service_scope_with_paging() -> None:
    page2 = f"https://management.azure.com{ARM_ID}/{PERMISSIONS_PATH}?api-version=2022-04-01&p=2"

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.params.get("p") == "2":
            return httpx.Response(200, json={"value": [{"actions": ["*/read"]}]})
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "actions": ["Microsoft.ApiManagement/service/*"],
                        "notActions": [],
                        "dataActions": ["x"],
                    }
                ],
                "nextLink": page2,
            },
        )

    arm, seen = _http(handler)
    entries = await arm.permissions()
    assert entries == [
        {"actions": ["Microsoft.ApiManagement/service/*"], "notActions": []},
        {"actions": ["*/read"], "notActions": []},
    ]
    assert [r.method for r in seen] == ["GET", "GET"]
    assert seen[0].url.path == f"{ARM_ID}/providers/Microsoft.Authorization/permissions"
    assert seen[0].url.params["api-version"] == "2022-04-01"


async def test_permissions_paging_never_leaves_the_management_host() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": [], "nextLink": "https://evil.example.com/next"})

    arm, seen = _http(handler)
    with pytest.raises(DependencyTransientError):
        await arm.permissions()
    assert len(seen) == 1


async def test_permissions_errors_map_by_status() -> None:
    arm, _ = _http(lambda req: httpx.Response(403, json={}))
    with pytest.raises(Exception) as info:
        await arm.permissions()
    assert getattr(info.value, "code", None) == "forbidden"
    arm, _ = _http(lambda req: httpx.Response(200, json={"value": "nope"}))
    with pytest.raises(DependencyTransientError):
        await arm.permissions()
