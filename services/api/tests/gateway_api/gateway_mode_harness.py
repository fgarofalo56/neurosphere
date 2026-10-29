"""Harness for the gateway mode-switch API tests (PRP-34 item 2). Offline, no ARM.

The REAL authz stack, the real gateway and action routers (``create_app`` mounts both), the real
``ActionService``/``HitlService`` over in-memory stores, the in-memory gateway store, and the
REAL APIM write connector (with its mode step) over ``InMemoryApim`` registered as the
``apim-gateway`` write target. The API only ever calls ``dry_run`` on it.

People (customer ``contoso``):

* OPERATOR -- admin + domain steward on FINANCE: ``config.manage`` and ``action.propose``
* STEWARD  -- domain steward on FINANCE (no ``config.manage``)
* ADMIN    -- admin on FINANCE only (no ``action.propose``)
* VIEWER   -- viewer on FINANCE
* OUTSIDER -- admin + domain steward on OPERATIONS only

This directory has no ``__init__.py``: import by module name.
"""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
import httpx
from gateway_harness import RID  # pyright: ignore[reportMissingImports]
from neurosphere_api.actions import configure_action_plane
from neurosphere_api.gateway import GatewayPlane, GatewaySettings, configure_gateway_plane
from neurosphere_api.hitl import RecheckerReviewerAuthorizer
from neurosphere_connector.write import WriteTargetRegistry
from neurosphere_connector_apim_gateway import (
    ApimGatewayConnector,
    ApplyRecord,
    GatewayModeHandler,
    GatewayRef,
    InMemoryApim,
)
from neurosphere_core.actions import (
    ActionService,
    GrantTablePermissionRechecker,
    InMemoryExecutionControl,
    InMemoryIntentStore,
    RecordingActionAuditor,
)
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import Role
from neurosphere_core.cloud import CloudProfile
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.gateway import (
    GatewayRegistration,
    InMemoryGatewayRecordStore,
    InMemoryGatewayStore,
    gateway_id_for,
)
from neurosphere_core.gateway.mode import GatewayModeSwitch, evaluate_permissions
from neurosphere_core.hitl import (
    DecisionLog,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewPolicyRegistry,
)

OPERATOR: Final = helpers.NOBODY
STEWARD: Final = helpers.ALICE
ADMIN: Final = helpers.BOB
VIEWER: Final = helpers.CAROL
OUTSIDER: Final = "a05b6c7d-8e9f-4a01-b2c3-d4e5f6a7b8c9"
FINANCE: Final[str] = helpers.FINANCE
OPERATIONS: Final[str] = helpers.OPERATIONS
CUSTOMER: Final[str] = helpers.CUSTOMER
GATEWAYS: Final = "/api/v1/gateways"
ACTIONS: Final = "/api/v1/actions"
GATEWAY_ID: Final = gateway_id_for(CUSTOMER, FINANCE, RID)
AUDIT_CHAIN: Final = "contoso.gateway"
T0: Final = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
EXECUTE_PERMISSIONS: Final = ("action.propose", "action.execute")


def principal(object_id: str) -> str:
    return str(helpers.principal_id_for(object_id))


def _ids(prefix: str) -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter):012d}"


def registration(*, cloud: str = "commercial", **update: Any) -> GatewayRegistration:
    base = GatewayRegistration(
        id=GATEWAY_ID,
        customer_id=CUSTOMER,
        domain_id=FINANCE,
        cloud=cloud,  # type: ignore[arg-type]
        arm_resource_id=RID,
        name="apim-demo",
        tier="standard_v2",
        created_at=T0,
        updated_at=T0,
        registered_by="pn-admin",
    )
    return GatewayRegistration.model_validate({**base.model_dump(), **update})


def manage_fields() -> dict[str, Any]:
    allowed = [{"actions": ["Microsoft.ApiManagement/service/*"], "notActions": []}]
    return {
        "mode": "manage",
        "mode_changed_by": "pn-earlier",
        "mode_changed_at": T0,
        "mode_revision": 1,
        "preflight": evaluate_permissions(allowed, now=T0),
    }


@dataclass
class ModeEnv:
    h: Any
    store: InMemoryGatewayStore
    audit: AuditRepository
    apim: InMemoryApim
    intents: InMemoryIntentStore
    rechecker: GrantTablePermissionRechecker
    records: InMemoryGatewayRecordStore[ApplyRecord]
    registry: WriteTargetRegistry
    responses: list[httpx.Response] = field(default_factory=list[httpx.Response])

    def call(self, method: str, who: str | None, url: str, **kwargs: Any) -> httpx.Response:
        headers = {} if who is None else self.h.auth(who)
        response = self.h.client.request(method, url, headers=headers, **kwargs)
        self.responses.append(response)
        return response

    def mode(
        self,
        who: str | None,
        mode: str,
        *,
        key: str = "idem-gateway-mode-000001",
        domain: str = FINANCE,
        gateway_id: str = GATEWAY_ID,
        **extra: Any,
    ) -> httpx.Response:
        body = {"mode": mode, "idempotency_key": key, **extra}
        path = f"{GATEWAYS}/domains/{domain}/gateways/{gateway_id}/mode"
        return self.call("POST", who, path, json=body)

    def step(self, who: str, intent_id: str, verb: str) -> httpx.Response:
        return self.call("POST", who, f"{ACTIONS}/domains/{FINANCE}/intents/{intent_id}/{verb}")

    def draft_intent(self, body: dict[str, Any], who: str = OPERATOR) -> httpx.Response:
        return self.call("POST", who, f"{ACTIONS}/domains/{FINANCE}/intents", json=body)

    def seed(self, value: GatewayRegistration) -> GatewayRegistration:
        return asyncio.run(self.store.create(value))

    def current(self) -> GatewayRegistration:
        found = asyncio.run(self.store.get(CUSTOMER, FINANCE, GATEWAY_ID))
        assert found is not None
        return found

    def audit_records(self) -> list[Any]:
        return list(asyncio.run(self.audit.read_range(AUDIT_CHAIN, limit=200)))


def make_mode_env(
    *,
    permissions: list[dict[str, Any]] | None = None,
    gateway_plane: bool = True,
    seed: GatewayRegistration | None = None,
) -> ModeEnv:
    h = helpers.harness(
        helpers.policy(
            OPERATOR,
            helpers.role(Role.ADMIN, FINANCE),
            helpers.role(Role.DOMAIN_STEWARD, FINANCE),
        ),
        helpers.policy(STEWARD, helpers.role(Role.DOMAIN_STEWARD, FINANCE)),
        helpers.policy(ADMIN, helpers.role(Role.ADMIN, FINANCE)),
        helpers.policy(VIEWER, helpers.role(Role.VIEWER, FINANCE)),
        helpers.policy(
            OUTSIDER,
            helpers.role(Role.ADMIN, OPERATIONS),
            helpers.role(Role.DOMAIN_STEWARD, OPERATIONS),
        ),
    )

    def clock() -> datetime:
        return datetime.fromtimestamp(h.clock(), UTC)

    store = InMemoryGatewayStore()
    audit = AuditRepository(InMemoryAuditStore(), id_factory=_ids("33333333-3333-4333-8333"))
    rechecker = GrantTablePermissionRechecker()
    for permission in EXECUTE_PERMISSIONS:
        rechecker.grant(principal(OPERATOR), CUSTOMER, FINANCE, permission)
    intents = InMemoryIntentStore()
    control = InMemoryExecutionControl()
    actions = ActionService(
        intents,
        auditor=RecordingActionAuditor(),
        rechecker=rechecker,
        execution_control=control,
        clock=clock,
        id_factory=_ids("00000000-0000-4000-8000"),
    )
    policies = ReviewPolicyRegistry()
    hitl = HitlService(
        InMemoryHitlStore(),
        DecisionLog(audit, InMemoryDecisionStore()),
        audit,
        policies,
        RecheckerReviewerAuthorizer(rechecker),
        id_factory=_ids("22222222-2222-4222-8222"),
    )
    apim = InMemoryApim(service_etag='"svc-1"')
    if permissions is not None:
        apim.permission_entries = permissions
    records: InMemoryGatewayRecordStore[ApplyRecord] = InMemoryGatewayRecordStore(ApplyRecord)
    gateway = GatewayRef(gateway_id=GATEWAY_ID, cloud=CloudName.COMMERCIAL, arm_resource_id=RID)
    switch = GatewayModeSwitch(
        store, customer_id=CUSTOMER, domain_id=FINANCE, gateway_id=GATEWAY_ID, activity=records
    )
    connector = ApimGatewayConnector(
        gateway, apim, records=records, mode=GatewayModeHandler(gateway, apim, switch)
    )
    registry = WriteTargetRegistry()
    registry.register(connector)
    configure_action_plane(
        h.app,
        action_service=actions,
        intent_store=intents,
        hitl_service=hitl,
        review_policies=policies,
        write_targets=registry,
        permission_rechecker=rechecker,
        execution_control=control,
        audit_repository=audit,
        clock=clock,
    )
    if gateway_plane:

        def factory(profile: CloudProfile) -> httpx.AsyncClient:
            raise AssertionError("the mode switch API never calls ARM")

        configure_gateway_plane(
            h.app,
            GatewayPlane(store=store, audit=audit, arm_factory=factory, settings=GatewaySettings()),
        )
    env = ModeEnv(
        h=h,
        store=store,
        audit=audit,
        apim=apim,
        intents=intents,
        rechecker=rechecker,
        records=records,
        registry=registry,
    )
    env.seed(seed if seed is not None else registration())
    return env


def problem(response: httpx.Response) -> dict[str, Any]:
    assert response.headers["content-type"].startswith("application/problem+json"), response.text
    return response.json()
