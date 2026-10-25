"""PRP-29 item 8: the action, review, reports and MCP-admin planes on the Cosmos emulator.

Needs the compose Cosmos emulator (``http://127.0.0.1:8081``); never starts or stops compose.
The REAL authz and planes builders run against the settings-built Cosmos client (the lifespan
bootstraps the registry containers, ``NS_ENV=local``). The data builder (item 7) is stood in by a
builder that publishes the audit repository and HITL service over the REAL Cosmos stores
(``audit``/``audit_tail``, ``hitl_items``/``hitl_decisions``) plus in-memory catalog and
aggregate readers. Only the token validator is a test stand-in (``conftest.py``).
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from typing import Any, Final

import httpx
import pytest
from fastapi import FastAPI
from neurosphere_api.actions import get_action_plane
from neurosphere_api.actions.models import DraftIntentBody
from neurosphere_api.app import create_app
from neurosphere_api.runtime import CompositionOverrides, compose_app
from neurosphere_api.runtime.builders import (
    AGGREGATE_READER,
    AUDIT_REPOSITORY,
    CATALOG_REPOSITORY,
    HITL_SERVICE,
    BuildContext,
    BuilderSpec,
    default_builders,
)
from neurosphere_api.runtime.builders import data as data_builder
from neurosphere_api.runtime.pseudonym import local_dev_pseudonym_key
from neurosphere_api.runtime.settings import StoreSettings
from neurosphere_core.actions import ActionCaller, StoredIntent
from neurosphere_core.actions.cosmos_store import CosmosIntentStore
from neurosphere_core.aggregates import InMemoryAggregateStore
from neurosphere_core.audit import AuditRepository
from neurosphere_core.audit.cosmos_store import CosmosAuditStore
from neurosphere_core.auth.jwt import JwtValidator
from neurosphere_core.auth.scope import PrincipalPseudonymizer
from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.catalog.repo import InMemoryCatalogRepository
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.hitl import DecisionLog, HitlService, ReviewPolicyRegistry
from neurosphere_core.hitl_cosmos.store import CosmosDecisionStore, CosmosHitlStore
from neurosphere_core.recommendations import InMemoryRecommendationStore
from starlette.requests import Request

from .conftest import real_stack_tenant

pytestmark = pytest.mark.integration

LOOPBACK: Final = "http://127.0.0.1:8081"
CUSTOMER: Final = "synthco"  # NS_ENV=local default customer binding
PLANE_COMPONENTS: Final = ("hitl", "action_plane", "reports", "mcp_admin")


class _NoReviewer:
    async def can_review(
        self, principal_id: str, customer_id: str, domain_id: str, permission: Permission
    ) -> bool:
        return False


def _cosmos_data(ctx: BuildContext) -> None:
    """Item 7's slot: audit and HITL on the real Cosmos containers, in-memory read ports."""
    client = ctx.cosmos_client()
    database = ctx.store_settings().database
    audit = AuditRepository(
        CosmosAuditStore.from_client(
            client, database=database, container="audit", tail_container="audit_tail"
        )
    )
    hitl = HitlService(
        CosmosHitlStore.from_client(client, database=database),
        DecisionLog(audit, CosmosDecisionStore.from_client(client, database=database)),
        audit,
        ReviewPolicyRegistry(),
        _NoReviewer(),
    )
    catalog = InMemoryCatalogRepository()
    metrics = InMemoryAggregateStore()
    state = ctx.app.state
    state.catalog_repository = catalog
    state.aggregate_reader = metrics
    state.recommendation_store = InMemoryRecommendationStore()
    state.audit_repository = audit
    ctx.publish(AUDIT_REPOSITORY, audit)
    ctx.publish(HITL_SERVICE, hitl)
    ctx.publish(AGGREGATE_READER, metrics)
    ctx.publish(CATALOG_REPOSITORY, catalog)
    for name in data_builder.COMPONENTS:
        ctx.ok(name)


def _builders() -> tuple[BuilderSpec, ...]:
    stub = BuilderSpec("cosmos-data", data_builder.COMPONENTS, _cosmos_data)
    return tuple(stub if spec.name == "data" else spec for spec in default_builders())


@pytest.fixture
def loopback_cosmos(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Listed before ``emulator_env`` so it keeps this 127.0.0.1 endpoint."""
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", LOOPBACK)
    yield


@pytest.fixture
def planes_app(
    loopback_cosmos: None, emulator_env: None, stand_in_validator: JwtValidator
) -> tuple[FastAPI, Any]:
    settings = Settings()
    app = create_app(settings)
    registry = compose_app(
        app,
        settings,
        CompositionOverrides(authenticator=stand_in_validator),
        builders=_builders(),
    )
    return app, registry


def _caller(object_id: str) -> ActionCaller:
    pid = PrincipalPseudonymizer(local_dev_pseudonym_key()).principal_id(
        cloud=CloudName.COMMERCIAL,
        customer_id=CUSTOMER,
        tenant_id=real_stack_tenant(),
        object_id=object_id,
        kind="user",
    )
    return ActionCaller.model_validate(
        {
            "principal_id": pid,
            "actor": {
                "principal_pseudonym": pid.rsplit(":", 1)[-1],
                "principal_kind": "user",
                "on_behalf_of": None,
            },
            "scope_hash": "sha256:" + hashlib.sha256(object_id.encode()).hexdigest(),
            "correlation_id": f"it-planes-{uuid.uuid4().hex}",
            "channel": "rest",
        }
    )


def _draft_body(run: str) -> DraftIntentBody:
    return DraftIntentBody.model_validate(
        {
            "action_kind": "model_deployment_swap",
            "target": {
                "canonical_id": f"commercial:{CUSTOMER}:foundry:agent:it-{run}",
                "entity_type": "agent",
            },
            "target_version": "etag-it-1",
            "proposed_diff": {
                "format": "json_patch",
                "operations": [{"op": "replace", "path": "/model/version", "value": "2026-06-15"}],
            },
            "evidence": [],
            "idempotency_key": f"idem-it-planes-{run}",
            "channel": "rest",
        }
    )


async def test_planes_are_ok_and_a_drafted_intent_persists_unexecuted(
    planes_app: tuple[FastAPI, Any],
) -> None:
    app, registry = planes_app
    for name in PLANE_COMPONENTS:
        assert registry.get(name).state == "ok", registry.get(name)
    run = uuid.uuid4().hex[:16]
    domain = f"commercial:{CUSTOMER}:catalog:domain:it-planes-{run}"
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        # The lifespan bootstrapped the containers; nothing failed at startup.
        ready = await client.get("/readyz")
        deps = ready.json()["dependencies"]
        for name in ("cosmos_containers", *PLANE_COMPONENTS):
            assert not [k for k in deps if k.startswith(f"composition.{name}.")], deps

        plane = get_action_plane(_request(app))
        assert isinstance(plane.intents, CosmosIntentStore)
        outcome = await plane.actions.draft(
            _caller(str(uuid.uuid4())),
            _draft_body(run).to_draft_request(),
            customer_id=CUSTOMER,
            domain_id=domain,
        )
        assert outcome.created is True
        intent_id = outcome.stored.intent.intent_id.root

        # The kill switch is read from Cosmos as well (its container exists and answers).
        await plane.control.get(CUSTOMER)

    # Read back through an INDEPENDENT client and store on the emulator database: it persisted,
    # still drafted, never confirmed and never executed.
    async with ClientLifetime() as lifetime:
        settings = Settings()
        client = create_cosmos_client(settings, lifetime=lifetime)
        fresh = CosmosIntentStore.from_client(client, database=StoreSettings().database)
        stored = await fresh.get(CUSTOMER, domain, intent_id)
    assert isinstance(stored, StoredIntent)
    assert stored.state == "drafted"
    assert stored.execution is None
    assert stored.intent.confirmation_hash is None


def _request(app: FastAPI) -> Request:
    return Request({"type": "http", "app": app, "headers": []})
