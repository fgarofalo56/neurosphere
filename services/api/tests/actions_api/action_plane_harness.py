"""Harness for the action and review-queue API tests (PRP-17 item 4). No network.

The REAL authz stack (dev-issuer JWTs, scope derivation over an in-memory policy store) from
``services/api/tests/authz``, the real action and review routers, the real ``ActionService`` and
``HitlService`` over in-memory stores, a grant-table ``PermissionRechecker`` (stand-in for item
2's policy rechecker) and a fake write connector that counts calls and refuses ``apply`` /
``rollback`` outright (the API must never reach them).

People (all in customer ``contoso``):

* ALICE -- domain steward on FINANCE (the maker in most tests)
* BOB   -- domain steward on FINANCE (the checker)
* CAROL -- viewer on FINANCE
* DAVE  -- admin on FINANCE (kill switch)
* ERIN  -- viewer on FINANCE, steward on OPERATIONS

This directory has no ``__init__.py`` (same convention as ``services/api/tests/evaluation``):
import by module name.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
from neurosphere_api.actions import (
    PREFIX,
    ActionApiSettings,
    build_router,
    configure_action_plane,
)
from neurosphere_api.hitl import PREFIX as REVIEW_PREFIX
from neurosphere_api.hitl import RecheckerReviewerAuthorizer
from neurosphere_api.hitl import build_router as build_review_router
from neurosphere_connector import build_manifest
from neurosphere_connector.write import (
    ApplyResult,
    DryRunResult,
    RollbackResult,
    VerifyResult,
    WriteRequest,
    WriteTargetRegistry,
)
from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest, Granularity
from neurosphere_core.actions import (
    ActionService,
    GrantTablePermissionRechecker,
    InMemoryExecutionControl,
    InMemoryIntentStore,
    RecordingActionAuditor,
)
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import Role
from neurosphere_core.errors import StaleVersionError
from neurosphere_core.hitl import (
    DecisionLog,
    HitlService,
    InMemoryDecisionStore,
    InMemoryHitlStore,
    ReviewPolicyRegistry,
)

ALICE: str = helpers.ALICE
BOB: str = helpers.BOB
CAROL: str = helpers.CAROL
DAVE: str = helpers.NOBODY
ERIN: str = "a05b6c7d-8e9f-4a01-b2c3-d4e5f6a7b8c9"
FINANCE: str = helpers.FINANCE
OPERATIONS: str = helpers.OPERATIONS
CUSTOMER: str = helpers.CUSTOMER

TARGET_ID: Final = "commercial:contoso:foundry:model_deployment:eastus2/chat-prod"
TARGET_VERSION: Final = "etag-0x8dce1f2a3b4c5d6"
KIND: Final = "model_deployment_swap"
CONNECTOR_NAME: Final = "foundry-model-swap"
STEWARD_PERMISSIONS: Final = (
    "action.propose",
    "action.execute",
    "action.approve",
    "catalog.curate",
)


def principal(object_id: str) -> str:
    return str(helpers.principal_id_for(object_id))


class FakeSwapConnector:
    """Write connector stand-in: ``dry_run`` only. ``apply``/``verify``/``rollback`` explode."""

    def __init__(self, current_version: str = TARGET_VERSION) -> None:
        self.current_version = current_version
        self.dry_runs: list[WriteRequest] = []
        self.forbidden_calls: list[str] = []
        self.error: Exception | None = None

    @property
    def manifest(self) -> ConnectorManifest:
        return build_manifest(
            name=CONNECTOR_NAME,
            version="0.1.0",
            capabilities=["health_reporting"],
            supported_clouds=["commercial"],
            granularity=Granularity(time_grain="unknown", subject_level="deployment"),
            scopes=["https://management.azure.com/.default"],
            write_actions=[KIND],
        )

    @property
    def advisory(self) -> bool:
        return False

    async def dry_run(self, request: WriteRequest) -> DryRunResult:
        self.dry_runs.append(request)
        if self.error is not None:
            raise self.error
        if request.target_version != self.current_version:
            raise StaleVersionError("deployment changed", reason="target_version_changed")
        return DryRunResult(
            target=request.target,
            target_version=request.target_version,
            planned_diff=request.proposed_diff,
            would_change=True,
        )

    async def apply(self, request: WriteRequest) -> ApplyResult:
        self.forbidden_calls.append("apply")
        raise AssertionError("the API must never apply a change")

    async def verify(self, request: WriteRequest) -> VerifyResult:
        self.forbidden_calls.append("verify")
        raise AssertionError("the API must never verify a change")

    async def rollback(self, applied: ApplyResult) -> RollbackResult:
        self.forbidden_calls.append("rollback")
        raise AssertionError("the API must never roll back a change")


def draft_body(
    key: str = "idem-2026-10-20-chat-prod-0001",
    *,
    kind: str = KIND,
    channel: str = "rest",
    new_version: str = "2026-06-15",
    target_id: str = TARGET_ID,
) -> dict[str, Any]:
    return {
        "action_kind": kind,
        "target": {"canonical_id": target_id, "entity_type": "model_deployment"},
        "target_version": TARGET_VERSION,
        "proposed_diff": {
            "format": "json_patch",
            "operations": [
                {"op": "test", "path": "/model/version", "value": "2024-08-06"},
                {"op": "replace", "path": "/model/version", "value": new_version},
            ],
        },
        "evidence": [
            {
                "evidence_id": "rec-0042",
                "kind": "recommendation",
                "ref": "commercial:contoso:neurosphere:recommendation:rec-0042",
                "observed_at": None,
            }
        ],
        "idempotency_key": key,
        "channel": channel,
    }


def _ids(prefix: str) -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"{prefix}-{next(counter):012d}"


@dataclass
class Api:
    h: Any
    connector: FakeSwapConnector
    registry: WriteTargetRegistry
    intents: InMemoryIntentStore
    auditor: RecordingActionAuditor
    rechecker: GrantTablePermissionRechecker
    control: InMemoryExecutionControl
    actions: ActionService
    hitl: HitlService
    hitl_store: InMemoryHitlStore
    decision_log: DecisionLog
    audit: AuditRepository
    responses: list[Any] = field(default_factory=list[Any])

    # -- HTTP ----------------------------------------------------------------------------------

    def _send(self, method: str, who: str | None, url: str, **kwargs: Any) -> Any:
        headers = self.h.auth(who) if who else {}
        response = self.h.client.request(method, url, headers=headers, **kwargs)
        self.responses.append(response)
        return response

    def call(self, method: str, who: str | None, path: str, **kwargs: Any) -> Any:
        return self._send(method, who, f"{PREFIX}{path}", **kwargs)

    def review(self, method: str, who: str | None, path: str, **kwargs: Any) -> Any:
        return self._send(method, who, f"{REVIEW_PREFIX}{path}", **kwargs)

    def intents_path(self, domain: str = FINANCE) -> str:
        return f"/domains/{domain}/intents"

    def draft(
        self,
        who: str = ALICE,
        body: dict[str, Any] | None = None,
        *,
        domain: str = FINANCE,
        **kw: Any,
    ) -> Any:
        return self.call("POST", who, self.intents_path(domain), json=body or draft_body(**kw))

    def step(self, who: str, intent_id: str, verb: str, body: Any = None) -> Any:
        return self.call("POST", who, f"{self.intents_path()}/{intent_id}/{verb}", json=body)

    def get_intent(self, intent_id: str, who: str = ALICE) -> Any:
        return self.call("GET", who, f"{self.intents_path()}/{intent_id}")

    # -- lifecycle shortcuts ------------------------------------------------------------------

    def drafted(self, **kw: Any) -> dict[str, Any]:
        response = self.draft(**kw)
        assert response.status_code == 201, response.text
        return response.json()

    def validated(self, **kw: Any) -> dict[str, Any]:
        intent_id = self.drafted(**kw)["intent"]["intent_id"]
        response = self.step(ALICE, intent_id, "validate")
        assert response.status_code == 200, response.text
        return response.json()

    def presented(self, **kw: Any) -> dict[str, Any]:
        intent_id = self.validated(**kw)["intent"]["intent_id"]
        response = self.step(ALICE, intent_id, "confirmation")
        assert response.status_code == 200, response.text
        return response.json()

    def awaiting_approval(self, **kw: Any) -> dict[str, Any]:
        view = self.presented(**kw)
        response = self.step(
            ALICE,
            view["intent"]["intent_id"],
            "confirm",
            {"confirmation_hash": view["intent"]["confirmation_hash"]},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def all_text(self) -> Iterator[str]:
        for response in self.responses:
            yield response.text
            yield str(dict(response.headers))


def make_api(
    *,
    with_connector: bool = True,
    settings: ActionApiSettings | None = None,
    wire: bool = True,
) -> Api:
    h = helpers.harness(
        helpers.policy(ALICE, helpers.role(Role.DOMAIN_STEWARD, FINANCE)),
        helpers.policy(BOB, helpers.role(Role.DOMAIN_STEWARD, FINANCE)),
        helpers.policy(CAROL, helpers.role(Role.VIEWER, FINANCE)),
        helpers.policy(DAVE, helpers.role(Role.ADMIN, FINANCE)),
        helpers.policy(
            ERIN,
            helpers.role(Role.VIEWER, FINANCE),
            helpers.role(Role.DOMAIN_STEWARD, OPERATIONS),
        ),
        routers={PREFIX: build_router(), REVIEW_PREFIX: build_review_router()},
    )

    def clock() -> datetime:
        return datetime.fromtimestamp(h.clock(), UTC)

    rechecker = GrantTablePermissionRechecker()
    for who in (ALICE, BOB):
        for permission in STEWARD_PERMISSIONS:
            rechecker.grant(principal(who), CUSTOMER, FINANCE, permission)
    for permission in STEWARD_PERMISSIONS:
        rechecker.grant(principal(ERIN), CUSTOMER, OPERATIONS, permission)
    intents = InMemoryIntentStore()
    auditor = RecordingActionAuditor()
    control = InMemoryExecutionControl()
    actions = ActionService(
        intents,
        auditor=auditor,
        rechecker=rechecker,
        execution_control=control,
        clock=clock,
        id_factory=_ids("00000000-0000-4000-8000"),
    )
    audit = AuditRepository(InMemoryAuditStore(), id_factory=_ids("33333333-3333-4333-8333"))
    decision_log = DecisionLog(audit, InMemoryDecisionStore())
    hitl_store = InMemoryHitlStore()
    policies = ReviewPolicyRegistry()
    hitl = HitlService(
        hitl_store,
        decision_log,
        audit,
        policies,
        RecheckerReviewerAuthorizer(rechecker),
        id_factory=_ids("22222222-2222-4222-8222"),
    )
    connector = FakeSwapConnector()
    registry = WriteTargetRegistry()
    if with_connector:
        registry.register(connector)
    if wire:
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
            settings=settings,
            clock=clock,
        )
    return Api(
        h=h,
        connector=connector,
        registry=registry,
        intents=intents,
        auditor=auditor,
        rechecker=rechecker,
        control=control,
        actions=actions,
        hitl=hitl,
        hitl_store=hitl_store,
        decision_log=decision_log,
        audit=audit,
    )


def problem(response: Any) -> dict[str, Any]:
    assert response.headers["content-type"].startswith("application/problem+json"), response.text
    return response.json()
