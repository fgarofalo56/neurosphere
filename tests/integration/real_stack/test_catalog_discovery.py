"""PRP-10 item 12: a trace through the ingest edge becomes catalog entities, edges and a search hit.

Needs the compose emulators ALREADY running (Cosmos 8081, Event Hubs 5672, Azurite 10000); this
suite never starts, stops or restarts compose. Export ``NS_PROBE_COSMOS_URL=http://127.0.0.1:8081/``.

What runs where (same split as ``test_seed.py``): the API (``create_app`` + ``configure_ingest`` +
``compose_app``, the production composition with only the token validator and the policy
repository swapped) and the ``ingestion`` + ``projections`` worker roles run IN THIS PROCESS against
the emulators; the compose ``api``/``workers`` containers (profile ``app``) need Entra ids and image
builds and are not used. Everything HTTP goes through the real routers.

The trace is synthetic sandbox data whose agents, tools, models and domain are renamed to
uuid-suffixed names, so the entities can only come from trace entity discovery (PRP-10 item 8): the
database is fresh and nothing is seeded into the catalog. A caller scoped to a different domain
must see none of it (404 or an empty result, never a 403 with details).

Run: ``NS_PROBE_COSMOS_URL=http://127.0.0.1:8081/ MSYS_NO_PATHCONV=1 uv run pytest -q -m integration
tests/integration/real_stack/test_catalog_discovery.py``. Emulator limits (G12): no auth, no RU
accounting.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from azure.storage.blob.aio import ContainerClient
from neurosphere_api.app import create_app
from neurosphere_api.ingest import IngestSettings
from neurosphere_api.ingest.bootstrap import configure_ingest_from_settings
from neurosphere_api.runtime import CompositionOverrides, compose_app
from neurosphere_api.runtime.pseudonym import local_dev_pseudonym_key
from neurosphere_core.auth.jwt import JwtValidator
from neurosphere_core.auth.jwt.config import normalize_tenant_id
from neurosphere_core.auth.scope import (
    InMemoryPolicyRepository,
    PolicyHead,
    PolicyRoleAssignment,
    PrincipalPolicy,
    PrincipalPseudonymizer,
    Role,
    principal_document_id,
)
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.stores import ensure_local_containers
from neurosphere_workers.runtime.factories import RuntimeConfig, role_factories
from neurosphere_workers.runtime.identity import resolve_pseudonym_key
from neurosphere_workers.runtime.supervisor import RoleSupervisor

from integration.ingestion.support import (
    Producer,
    azurite_connection_string,
    cloudevent,
    push_cloudevents,
    write_producers_file,
)
from integration.workers_runtime.support import (
    EVENTHUBS_CONNECTION,
    WORKER_OBJECT_ID,
    WORKER_TENANT_ID,
    sandbox_trace_bundle,
)

from .conftest import real_stack_tenant

pytestmark = pytest.mark.integration

CUSTOMER: Final = "synthco"
SOURCE: Final = "sandbox-gateway"
ENDPOINT: Final = "http://127.0.0.1:8081"
IN_SCOPE_OID: Final = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
OUT_OF_SCOPE_OID: Final = "7d2e3f40-5b6c-4d7e-8f90-a1b2c3d4e5f6"
CATALOG: Final = "/api/v1/catalog"
WAIT_SECONDS: Final = 90
POLL_SECONDS: Final = 3
BUDGET: Final = {"timeout_ms": 5000, "limit": 100, "max_depth": 2}
ROLES: Final = ("ingestion", "projections")


class Names:
    """Every identifier of the run; the suffix makes them absent from any seed."""

    def __init__(self, run: str) -> None:
        self.run = run
        prefix = f"commercial:{CUSTOMER}:sandbox"
        self.domain = f"{prefix}:domain:dom-{run}"
        self.other_domain = f"{prefix}:domain:other-{run}"
        self.parent_name = f"agt-{run}-parent"
        self.child_name = f"agt-{run}-child"
        self.parent = f"{prefix}:agent:{self.parent_name}"
        self.child = f"{prefix}:agent:{self.child_name}"
        self.tools = (f"{prefix}:tool:tl-{run}-a", f"{prefix}:tool:tl-{run}-b")
        self.model_names = (f"mdl-{run}-p", f"mdl-{run}-c")
        self.model_version = "2026-03"
        # The model-deployment ID is derived from the span source (slugged) + model + version.
        deployment = f"commercial:{CUSTOMER}:{SOURCE}:model_deployment"
        self.parent_model = f"{deployment}:{self.model_names[0]}-{self.model_version}"
        self.child_model = f"{deployment}:{self.model_names[1]}-{self.model_version}"

    @property
    def entity_ids(self) -> list[str]:
        return [
            self.parent,
            self.child,
            *self.tools,
            self.parent_model,
            self.child_model,
        ]

    @property
    def expected_edges(self) -> list[tuple[str, str, str]]:
        """(relation, source, target)."""
        return [
            ("invokes", self.parent, self.child),
            ("uses_model", self.parent, self.parent_model),
            ("uses_model", self.child, self.child_model),
            ("invokes", self.child, self.tools[0]),
            ("invokes", self.child, self.tools[1]),
        ]


def _fresh_trace(names: Names) -> list[dict[str, Any]]:
    """The sandbox delegation trace, renamed and re-timed so nothing in it exists elsewhere."""
    telemetry, _cost = sandbox_trace_bundle()
    text = json.dumps(telemetry)
    old_trace = telemetry[0]["trace_id"]
    old = telemetry[0]["canonical_agent_id"]
    child = next(
        d["canonical_agent_id"]
        for d in telemetry
        if d["span_kind"] == "agent_run" and d["canonical_agent_id"] != old
    )
    tool_refs = [
        r["ref"] for d in telemetry for r in d.get("data_source_refs", []) if ":tool:" in r["ref"]
    ]
    models = [d["model"] for d in telemetry if d["span_kind"] == "model_call"]
    versions = {d["model_version"] for d in telemetry if d["span_kind"] == "model_call"}
    domains = {d["domain_id"] for d in telemetry}
    assert len(domains) == 1 and len(set(tool_refs)) == 2 and len(set(models)) == 2, "bundle shape"
    # Longest tokens first so no replacement is a prefix of another.
    replacements = {
        old: names.parent,
        child: names.child,
        tool_refs[0]: names.tools[0],
        tool_refs[1]: names.tools[1],
        models[0]: names.model_names[0],
        models[1]: names.model_names[1],
        domains.pop(): names.domain,
        old_trace: uuid.uuid4().hex,
    }
    for version in versions:
        replacements[version] = names.model_version
    for src in sorted(replacements, key=len, reverse=True):
        text = text.replace(src, replacements[src])
    docs: list[dict[str, Any]] = json.loads(text)
    # External agent ids are not canonical ids; make them unique too.
    for doc in docs:
        doc["event_id"] = f"evt-{names.run}-{doc['event_id'][-2:]}"
        doc["request_id"] = f"req-{names.run}"
    docs.sort(key=lambda d: d["event_time"])
    first = datetime.fromisoformat(docs[0]["event_time"].replace("Z", "+00:00"))
    base = datetime.now(UTC) - timedelta(seconds=60)
    for doc in docs:
        at = datetime.fromisoformat(doc["event_time"].replace("Z", "+00:00"))
        doc["event_time"] = (base + (at - first)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return docs


def _principal(oid: str) -> str:
    return PrincipalPseudonymizer(local_dev_pseudonym_key()).principal_id(
        cloud=CloudName.COMMERCIAL,
        customer_id=CUSTOMER,
        tenant_id=real_stack_tenant(),
        object_id=oid,
        kind="user",
    )


def _api_policy(names: Names) -> InMemoryPolicyRepository:
    repo = InMemoryPolicyRepository()
    repo.put_head(PolicyHead(customer_id=CUSTOMER, policy_version="v1"))
    for oid, domain in ((IN_SCOPE_OID, names.domain), (OUT_OF_SCOPE_OID, names.other_domain)):
        principal = _principal(oid)
        repo.put_principal(
            PrincipalPolicy(
                id=principal_document_id(principal),
                customer_id=CUSTOMER,
                principal_id=principal,
                domain_memberships=(domain,),
                role_assignments=(
                    PolicyRoleAssignment(
                        assignment_id=f"ra-{oid[:4]}", role=Role.ANALYST, domain_ids=(domain,)
                    ),
                ),
            )
        )
    return repo


async def _seed_worker_policy(cosmos: Any, cfg: RuntimeConfig, domain: str) -> None:
    """Grant the worker principal viewer on the trace's domain (the one derivation path)."""
    key = resolve_pseudonym_key(cfg.auth, env="local")
    principal = PrincipalPseudonymizer(key).principal_id(
        cloud=CloudName.COMMERCIAL,
        customer_id=CUSTOMER,
        tenant_id=normalize_tenant_id(WORKER_TENANT_ID),
        object_id=WORKER_OBJECT_ID,
        kind="service_principal",
    )
    policy = PrincipalPolicy(
        id=principal_document_id(principal),
        customer_id=CUSTOMER,
        principal_id=principal,
        domain_memberships=(domain,),
        role_assignments=(
            PolicyRoleAssignment(assignment_id="ra-worker", role=Role.VIEWER, domain_ids=(domain,)),
        ),
    )
    container = cosmos.get_database_client(cfg.store.database).get_container_client(
        cfg.auth.policy_container
    )
    await container.upsert_item(body=policy.model_dump(mode="json"))
    head = PolicyHead(customer_id=CUSTOMER, policy_version="it-1")
    await container.upsert_item(body=head.model_dump(mode="json"))


@pytest.fixture
def stack_env(monkeypatch: pytest.MonkeyPatch, emulator_env: None) -> dict[str, str]:
    run = uuid.uuid4().hex[:8]
    env = {
        "NS_COSMOS_ENDPOINT": ENDPOINT,
        "NS_EVENTHUBS_CONNECTION_STRING": EVENTHUBS_CONNECTION,
        "NS_BLOB_CONNECTION_STRING": azurite_connection_string(),
        "NS_STORE_DATABASE": f"it_cd_{run}",
        "NS_INGESTION_CHECKPOINT_CONTAINER": f"ns-ckpt-{run}",
        "NS_INGESTION_MAX_WAIT_SECONDS": "1",
        "NS_ARCHIVE_CONTAINER": f"ns-arch-{run}",
        "NS_QUARANTINE_CONTAINER": f"ns-quar-{run}",
        "NS_AUTH_CUSTOMER_ID": CUSTOMER,
        "NS_WORKER_TENANT_ID": WORKER_TENANT_ID,
        "NS_WORKER_OBJECT_ID": WORKER_OBJECT_ID,
        "NS_WORKER_POLL_SECONDS": "1",
        "NS_WORKER_HEALTH_PORT": "0",
        "NS_SEARCH_PROVIDER": "fixture",
        "NS_SEARCH_REFRESH_SECONDS": "5",
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    for name in ("NS_CLOUD", "NS_AUTH_PSEUDONYM_KEY", "NS_AUTH_PSEUDONYM_KEY_REFERENCE"):
        monkeypatch.delenv(name, raising=False)
    return env


async def _wait(
    probe: Callable[[], Any], what: str, limit_s: float = WAIT_SECONDS
) -> tuple[Any, float]:
    """Bounded poll (>= 2 s between probes). Returns (last probe value, seconds waited)."""
    started = time.monotonic()
    value = await probe()
    while value and time.monotonic() - started < limit_s:
        await asyncio.sleep(POLL_SECONDS)
        value = await probe()
    return value, time.monotonic() - started


@contextlib.asynccontextmanager
async def _api(
    names: Names, validator: JwtValidator, producers_file: Path
) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings()
    app = create_app(settings)
    configured = configure_ingest_from_settings(
        app,
        settings,
        IngestSettings(
            producers_file=producers_file, rate_limit_rps=100_000, rate_limit_burst=100_000
        ),
    )
    assert configured is True
    compose_app(
        app,
        settings,
        CompositionOverrides(authenticator=validator, policy_repository=_api_policy(names)),
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://api.invalid"
        ) as client:
            yield client


async def test_trace_becomes_entities_edges_and_search_hit_for_in_scope_caller_only(
    stack_env: dict[str, str],
    stand_in_validator: JwtValidator,
    stand_in_token: Callable[..., dict[str, str]],
    tmp_path: Path,
) -> None:
    run = stack_env["NS_STORE_DATABASE"].rsplit("_", 1)[1]
    names = Names(run)
    docs = _fresh_trace(names)
    producer = Producer("p-disc", CUSTOMER, "commercial", {SOURCE: "gateway"})
    producers_file = write_producers_file(tmp_path, [producer])
    inside, outside = stand_in_token(IN_SCOPE_OID), stand_in_token(OUT_OF_SCOPE_OID)
    cfg = RuntimeConfig.from_env()
    database = cfg.store.database
    supervisor = RoleSupervisor(role_factories(cfg, ROLES))
    runner: asyncio.Task[None] | None = None
    seen: dict[str, Any] = {}

    async with ClientLifetime() as lifetime:
        cosmos = create_cosmos_client(cfg.settings, lifetime=lifetime)
        try:
            await ensure_local_containers(cosmos, cfg.settings, database=database)
            await _seed_worker_policy(cosmos, cfg, names.domain)
            async with _api(names, stand_in_validator, producers_file) as client:
                before = await client.get(f"{CATALOG}/entities/{names.parent}", headers=inside)
                assert before.status_code in (403, 404), before.text

                pushed = await push_cloudevents(
                    client, producer, [cloudevent("telemetry", d) for d in docs]
                )
                assert pushed.accepted == len(docs), pushed
                runner = asyncio.create_task(supervisor.run())

                async def missing_entities() -> list[str]:
                    found: list[str] = []
                    for entity_id in names.entity_ids:
                        got = await client.get(f"{CATALOG}/entities/{entity_id}", headers=inside)
                        if got.status_code != 200:
                            found.append(entity_id)
                    return found

                async def neighbors(node_id: str, headers: dict[str, str]) -> httpx.Response:
                    return await client.post(
                        f"{CATALOG}/lineage/neighbors",
                        headers=headers,
                        json={"node_id": node_id, "direction": "out", "budget": BUDGET},
                    )

                async def edges_by_key() -> dict[tuple[str, str, str], dict[str, Any]]:
                    found: dict[tuple[str, str, str], dict[str, Any]] = {}
                    for node in (names.parent, names.child):
                        got = await neighbors(node, inside)
                        if got.status_code == 200:
                            for edge in got.json()["edges"]:
                                key = (edge["relation_type"], edge["source_id"], edge["target_id"])
                                found[key] = edge
                    return found

                seen["absent_entities"], seen["entities_seconds"] = await _wait(
                    missing_entities, "entities"
                )

                async def missing_edges() -> list[tuple[str, str, str]]:
                    have = await edges_by_key()
                    seen["edges"] = have
                    return [key for key in names.expected_edges if key not in have]

                seen["absent_edges"], seen["edges_seconds"] = await _wait(
                    missing_edges, "edges", max(WAIT_SECONDS - seen["entities_seconds"], 10.0)
                )

                async def search_miss() -> bool:
                    got = await client.post(
                        f"{CATALOG}/search",
                        headers=inside,
                        json={"term": names.parent_name, "budget": BUDGET},
                    )
                    seen["search_status"] = got.status_code
                    if got.status_code != 200:
                        seen["search_body"] = got.text[:500]
                        return True
                    seen["search_ids"] = [n["id"] for n in got.json()["nodes"]]
                    return names.parent not in seen["search_ids"]

                seen["search_miss"], seen["search_seconds"] = await _wait(search_miss, "search", 60)

                # The out-of-scope caller (another domain) sees none of it.
                hidden: dict[str, int] = {}
                bodies: list[str] = []
                for entity_id in names.entity_ids:
                    got = await client.get(f"{CATALOG}/entities/{entity_id}", headers=outside)
                    hidden[entity_id] = got.status_code
                    bodies.append(got.text)
                seen["outside_entities"] = hidden
                seen["outside_bodies"] = bodies
                seen["absent_code"] = before.json().get("code")
                out_neighbors = await neighbors(names.parent, outside)
                seen["outside_neighbors_status"] = out_neighbors.status_code
                seen["outside_neighbors"] = (
                    out_neighbors.json() if out_neighbors.status_code == 200 else None
                )
                out_search = await client.post(
                    f"{CATALOG}/search",
                    headers=outside,
                    json={"term": names.parent_name, "budget": BUDGET},
                )
                seen["outside_search_status"] = out_search.status_code
                seen["outside_search_ids"] = (
                    [n["id"] for n in out_search.json()["nodes"]]
                    if out_search.status_code == 200
                    else None
                )
            states = {r["name"]: f"{r['state']}:{r['reason']}" for r in supervisor.snapshot()}
        finally:
            supervisor.request_shutdown()
            if runner is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(runner, timeout=120)
            with contextlib.suppress(Exception):
                await cosmos.delete_database(database)
            for name in (
                stack_env["NS_ARCHIVE_CONTAINER"],
                stack_env["NS_QUARANTINE_CONTAINER"],
                stack_env["NS_INGESTION_CHECKPOINT_CONTAINER"],
            ):
                with contextlib.suppress(Exception):
                    async with ContainerClient.from_connection_string(
                        stack_env["NS_BLOB_CONNECTION_STRING"], name
                    ) as blob:
                        await blob.delete_container()

    print(
        "DISCOVERY TIMING: entities "
        f"{seen['entities_seconds']:.1f}s, edges {seen['edges_seconds']:.1f}s, "
        f"search {seen['search_seconds']:.1f}s; roles={states}"
    )

    # Entities discovered from the trace alone.
    assert seen["absent_entities"] == [], f"not discovered: {seen['absent_entities']}; {states}"

    # Edges: INVOKES / USES_MODEL, inferred, with evidence pointers into the trace.
    assert seen["absent_edges"] == [], f"edges missing: {seen['absent_edges']}; {states}"
    for key in names.expected_edges:
        edge = seen["edges"][key]
        assert edge["status"] == "inferred", edge
        assert edge["evidence_ids"], edge
        assert all(e.startswith(("event:", "trace:")) for e in edge["evidence_ids"]), edge
        assert any(e.startswith("event:") for e in edge["evidence_ids"]), edge
        assert any(e.startswith("trace:") for e in edge["evidence_ids"]), edge

    # Search for the agent name returns the discovered agent.
    assert seen["search_status"] == 200, seen.get("search_body")
    assert not seen["search_miss"], f"search did not return {names.parent}: {seen['search_ids']}"

    # Out-of-scope caller: the product answers a direct read with the generic authorization denial
    # (403 ``forbidden``, PRP-06), identical to the answer for an entity that does not exist, and
    # carries no entity detail; lineage and search return nothing. 404 is also acceptable.
    assert set(seen["outside_entities"].values()) <= {403, 404}, seen["outside_entities"]
    for body in seen["outside_bodies"]:
        assert not any(k in body for k in ("discovered_from", "display_name", "attributes")), body
    assert {json.loads(b).get("code") for b in seen["outside_bodies"]} <= {
        seen["absent_code"],
        "not_found",
    }, seen["outside_bodies"]
    assert seen["outside_neighbors_status"] in (200, 404), seen["outside_neighbors_status"]
    if seen["outside_neighbors"] is not None:
        assert seen["outside_neighbors"]["nodes"] == []
        assert seen["outside_neighbors"]["edges"] == []
    assert seen["outside_search_status"] == 200, seen["outside_search_status"]
    assert seen["outside_search_ids"] == []
