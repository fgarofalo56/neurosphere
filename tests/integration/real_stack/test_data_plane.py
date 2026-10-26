"""PRP-29 item 7: the composed data plane answers 200 for a seeded domain on the emulators.

Needs the compose emulators (Cosmos on 127.0.0.1:8081, Azurite on 127.0.0.1:10000); never starts or
stops compose. Each test uses a throwaway Cosmos database and a throwaway archive container, both
deleted afterwards. Data is seeded through the store and blob APIs. Only the token validator and
the in-memory policy store are test stand-ins; every data component is the production builder over
the emulators.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from azure.storage.blob.aio import ContainerClient
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.runtime import CompositionOverrides, compose_app
from neurosphere_api.runtime.builders.blob import azurite_connection_string
from neurosphere_api.runtime.pseudonym import local_dev_pseudonym_key
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.aggregates import AggregateStatus
from neurosphere_core.aggregates.cosmos import CosmosAggregateStore
from neurosphere_core.aggregates.models import CostPoint, format_bucket
from neurosphere_core.auth.jwt import JwtValidator
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    PolicyHead,
    PolicyRoleAssignment,
    PrincipalPolicy,
    PrincipalPseudonymizer,
    Role,
    principal_document_id,
)
from neurosphere_core.catalog.repo.cosmos import CosmosCatalogRepository
from neurosphere_core.catalog.repo.documents import parse_entity
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.ledger import DEFAULT_COST_CATEGORY, CostLedger, Observation
from neurosphere_core.ledger.cosmos import CosmosLedgerStore
from neurosphere_core.scope import IdentityScope
from neurosphere_workers.ingestion.wiring import LedgerSettings

from .conftest import real_stack_tenant

pytestmark = pytest.mark.integration

LOOPBACK = "http://127.0.0.1:8081"
CUSTOMER = "synthco"  # the NS_ENV=local default customer binding
DOMAIN = f"commercial:{CUSTOMER}:catalog:domain:finance"
OPERATOR = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
TRACE = "a" * 32
EXAMPLE = (
    Path(__file__).resolve().parents[3]
    / "packages/contracts/schemas/catalog/v1/examples/valid/agent.minimal-and-typical.json"
)


@pytest.fixture
def throwaway(monkeypatch: pytest.MonkeyPatch, emulator_env: None) -> Iterator[tuple[str, str]]:
    """(database, archive container) names; both deleted afterwards."""
    monkeypatch.setenv("NS_COSMOS_ENDPOINT", LOOPBACK)
    database = f"ns_dp_{uuid.uuid4().hex[:10]}"
    container = f"ns-dp-{uuid.uuid4().hex[:10]}"
    monkeypatch.setenv("NS_STORE_DATABASE", database)
    monkeypatch.setenv("NS_ARCHIVE_CONTAINER", container)

    async def create_archive() -> None:
        async with ContainerClient.from_connection_string(
            azurite_connection_string(), container
        ) as blobs:
            await blobs.create_container()

    asyncio.run(create_archive())
    try:
        yield database, container
    finally:

        async def cleanup() -> None:
            async with ClientLifetime() as lifetime:
                client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
                await client.delete_database(database)
            async with ContainerClient.from_connection_string(
                azurite_connection_string(), container
            ) as blobs:
                await blobs.delete_container()

        asyncio.run(cleanup())


def _policy_repository() -> InMemoryPolicyRepository:
    operator = PrincipalPseudonymizer(local_dev_pseudonym_key()).principal_id(
        cloud=CloudName.COMMERCIAL,
        customer_id=CUSTOMER,
        tenant_id=real_stack_tenant(),
        object_id=OPERATOR,
        kind="user",
    )
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version="v1"))
    repo.put_principal(
        PrincipalPolicy(
            id=principal_document_id(operator),
            customer_id=CUSTOMER,
            principal_id=operator,
            domain_memberships=(DOMAIN,),
            role_assignments=(
                PolicyRoleAssignment(
                    assignment_id="ra-analyst", role=Role.ANALYST, domain_ids=(DOMAIN,)
                ),
            ),
        )
    )
    return repo


def _scope() -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "principal": {
                "principal_id": f"commercial:{CUSTOMER}:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": [DOMAIN],
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + "0" * 64,
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def _observation(day: datetime, n: int) -> Observation:
    return Observation(
        observation_kind="gateway",
        doc_id=f"{n:064x}",
        kind="estimated",
        amount=Decimal("2.50"),
        currency="USD",
        price_version_id="pv-integration",
        observed_at=day,
        cloud="commercial",
        source_id="integration-source",
        domain_id=DOMAIN,
    )


async def _seed(database: str, container: str) -> None:
    now = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0)
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(Settings(env="local"), lifetime=lifetime)
        db = client.get_database_client(database)

        # aggregates: one cost point for today plus the freshness status
        aggregates = CosmosAggregateStore(db.get_container_client("aggregates"))
        start = format_bucket(now.replace(hour=0))
        point = CostPoint(
            id=f"cost-{start}",
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
            grain="day",
            bucket_start=start,
            series_key="estimated:USD",
            complete=True,
            kind="estimated",
            currency="USD",
            amount=Decimal("12.50"),
            entry_count=5,
            known_count=5,
        )
        await aggregates.replace_bucket(CUSTOMER, DOMAIN, "day", start, [point])
        await aggregates.put_status(
            AggregateStatus(customer_id=CUSTOMER, watermark=format_bucket(now))
        )

        # ledger: ten estimated days so the forecast has a price version to cite
        ledger = CostLedger(
            CosmosLedgerStore(db.get_container_client(LedgerSettings().ledger_container))
        )
        for n in range(10):
            day = now - timedelta(days=n + 1)
            await ledger.record(
                CUSTOMER, f"req-{n}", DEFAULT_COST_CATEGORY, _observation(day, n + 1)
            )

        # catalog: one agent in the domain (the map's node)
        raw: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        raw.update(
            id=f"commercial:{CUSTOMER}:foundry:agent:support-bot",
            customer_id=CUSTOMER,
            domain_id=DOMAIN,
            current_version_id=None,
            external_agent_id=None,
            attributes=None,
        )
        catalog = CosmosCatalogRepository(db.get_container_client("catalog"))
        await catalog.create_entity(_scope(), parse_entity(raw))

    # replay: one archived span in the worker's layout
    span = {
        "message": {"kind": "telemetry", "customer_id": CUSTOMER},
        "contract": {
            "trace_id": TRACE,
            "span_id": f"{1:016x}",
            "parent_span_id": None,
            "domain_id": DOMAIN,
            "span_kind": "tool_call",
            "outcome": "success",
            "duration_ms": 12,
            "sampling": {"rate": 1.0, "method": "head", "reason": "integration"},
        },
        "event_time": now.isoformat(),
        "ingestion_time": now.isoformat(),
        "late": False,
    }
    name = f"{CUSTOMER}/{DOMAIN}/{now:%Y/%m/%d}/{'1' * 64}.json.gz"
    payload = gzip.compress(json.dumps(span).encode("utf-8"), mtime=0)
    async with ContainerClient.from_connection_string(azurite_connection_string(), container) as c:
        await c.upload_blob(name, payload, overwrite=True)


def test_seeded_domain_answers_200_on_every_data_route(
    throwaway: tuple[str, str],
    stand_in_validator: JwtValidator,
    stand_in_token: Callable[..., dict[str, str]],
) -> None:
    database, container = throwaway
    settings = Settings()
    app = create_app(settings)
    registry = compose_app(
        app,
        settings,
        CompositionOverrides(
            authenticator=stand_in_validator, policy_repository=_policy_repository()
        ),
    )
    headers = stand_in_token(OPERATOR)
    with TestClient(app, raise_server_exceptions=False) as client:  # runs the lifespan
        # The lifespan created the registry containers on the emulator; now seed through stores.
        asyncio.run(_seed(database, container))
        failed = {
            name: registry.get(name).reason
            for name in ("catalog", "aggregates", "ledger", "federation", "replay", "map")
            if registry.get(name).state != "ok"
        }
        assert failed == {}
        routes = {
            "dashboards": f"/api/v1/dashboards/domains/{DOMAIN}/cost?days=7",
            "map": f"/api/v1/map/domains/{DOMAIN}/viewport",
            "replay": f"/api/v1/replay/domains/{DOMAIN}/traces",
            "federation": "/api/v1/federation/summary",
            "finops": f"/api/v1/finops/domains/{DOMAIN}/forecast",
        }
        statuses = {
            name: client.get(path, headers=headers).status_code for name, path in routes.items()
        }
        replay = client.get(f"/api/v1/replay/domains/{DOMAIN}/traces", headers=headers).json()
        map_body = client.get(routes["map"], headers=headers).json()
    assert statuses == dict.fromkeys(routes, 200)
    assert [t["trace_id"] for t in replay["items"]] == [TRACE]
    assert map_body["nodes"], "the seeded agent must appear on the map"
