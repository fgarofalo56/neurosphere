"""PRP-31 round 2 item 12: the UI-surface write loop over the seeded real stack.

Needs the SEEDED real stack (compose emulators plus the seed, see
``docs/dev/local-setup.md`` "Real stack"). This suite never starts or stops compose. The app is the
production composition (``create_app`` + ``compose_app`` with the default builders); only the token
validator is a TEST stand-in handed in through ``CompositionOverrides``. The operator is a fixed
synthetic object id granted every role through ``sbx_grant_operator`` (the step a human runs).

The steps run in file order and share state (``-p no:randomly`` if the random-order plugin is on).
Steps that mutate the stack clean up what they can: the entities this loop creates are deprecated
(the catalog has no delete), the stale-agent plan is confirmed with the smallest possible window so
it marks nothing seeded, and emergency disable is always re-enabled in a ``finally``.

Run: ``NS_PROBE_COSMOS_URL=http://127.0.0.1:8081/ MSYS_NO_PATHCONV=1 uv run pytest -q -m integration
-p no:randomly tests/integration/real_stack/test_ui_surfaces_loop.py``.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import os
import re
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest
from fastapi.testclient import TestClient
from neurosphere_api.app import create_app
from neurosphere_api.runtime import CompositionOverrides, compose_app
from neurosphere_core.auth.jwt import DevIssuer, JwksCache, JwtConfig, JwtValidator, entra_jwks_uri
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.stores import ensure_local_containers

from .conftest import real_stack_audience, real_stack_tenant

pytestmark = pytest.mark.integration

ROOT: Final = Path(__file__).resolve().parents[3]
GRANT_SCRIPT: Final = ROOT / "scripts/sandbox/sbx_grant_operator.py"
PERSONAS: Final = ROOT / "sandbox/stack/personas.json"
LOOPBACK: Final = "http://127.0.0.1:8081"
#: A fixed, synthetic, non-secret object id for this suite's operator (its own, not the manifest
#: suite's, so the two suites never share a principal).
OPERATOR_OID: Final = "6c1b0d9e-8f70-4b6c-9d5e-4f3a2b1c0d9e"
#: The audit-only principal is the SEEDED ``auditor`` persona (``security_auditor``:
#: ``audit.read``, no ``data.read``) from ``sandbox/stack/personas.json``, with no extra grant.
AUDITOR: Final = "auditor"
CREATED_PREFIX: Final = "ui-loop-"
ROLES: Final = ("viewer", "analyst", "domain_steward", "security_auditor", "admin")
GENERATOR_PROFILE: Final = "tiny"
ENTITY_ID: Final = re.compile(r"^(commercial|government):[a-z0-9._-]+:manual:agent:[0-9a-f]{32}$")
SEARCH_BUDGET: Final = {"timeout_ms": 5000, "limit": 20, "max_depth": 1}


def _seed_tenant() -> str:
    return (
        os.environ.get("NS_AUTH_TENANT_ID") or os.environ.get("NS_ENTRA_TENANT_ID") or ""
    ) or real_stack_tenant()


def _audience() -> str:
    client_id = os.environ.get("NS_ENTRA_CLIENT_ID")
    configured = os.environ.get("NS_AUTH_AUDIENCES")
    return configured.split(",")[0].strip() if configured else client_id or real_stack_audience()


async def _ensure_containers() -> None:
    settings = Settings(env="local")
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(settings, lifetime=lifetime)
        await ensure_local_containers(client, settings)


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Stack:
    """The composed app plus one ``Authorization`` header per principal."""

    def __init__(self, client: TestClient, tokens: dict[str, dict[str, str]]) -> None:
        self.client = client
        self.tokens = tokens
        self.domain = ""
        #: Shared between the ordered steps.
        self.state: dict[str, Any] = {}

    def call(self, method: str, path: str, who: str = "operator", **kwargs: Any) -> Any:
        headers = {**self.tokens[who], **kwargs.pop("headers", {})}
        return self.client.request(method, path, headers=headers, **kwargs)


def _deprecate_leftovers(stack: Stack) -> None:
    """The catalog has no delete: deprecate every active entity this suite created."""
    listing = stack.call(
        "GET", f"/api/v1/catalog/domains/{stack.domain}/entities?lifecycle=active&page_size=500"
    )
    if listing.status_code != 200:
        return
    for item in listing.json()["items"]:
        if str(item.get("display_name", "")).startswith(CREATED_PREFIX):
            stack.call(
                "POST",
                f"/api/v1/catalog/entities/{item['id']}/deprecate",
                json={"reason_code": "other"},
                headers={"If-Match": item["etag"]},
            )


@pytest.fixture(scope="module")
def stack(compose_stack: None) -> Iterator[Stack]:
    tenant, audience = _seed_tenant(), _audience()
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("NS_ENV", "local")
        mp.setenv("NS_COSMOS_ENDPOINT", os.environ.get("NS_COSMOS_ENDPOINT", LOOPBACK))
        mp.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())
        mp.setenv("NS_BLOB_CONNECTION_STRING", "UseDevelopmentStorage=true")
        mp.setenv("NS_AUTH_TENANT_ID", tenant)
        mp.setenv("NS_AUTH_AUDIENCES", audience)
        mp.setenv("NS_SEARCH_PROVIDER", "fixture")
        for name in ("NS_STORE_DATABASE", "NS_AUTH_CUSTOMER_ID", "NS_COPILOT_MODE"):
            mp.delenv(name, raising=False)

        asyncio.run(_ensure_containers())
        grant = _load(GRANT_SCRIPT, "ns_grant_operator_ui_loop")
        for role in ROLES:
            argv = [
                *("--object-id", OPERATOR_OID),
                *("--role", role),
                *("--tenant-id", tenant),
                *("--profile", GENERATOR_PROFILE),
            ]
            code = grant.main(argv, env=dict(os.environ))
            assert code == 0, f"grant {role} exited {code}"

        issuer = DevIssuer(Settings(env="local"), tenant_id=tenant, kid="ui-loop-stand-in")
        unrelated = DevIssuer(Settings(env="local"), tenant_id=tenant, kid="unrelated")

        class Keys:
            url = entra_jwks_uri(CloudName.COMMERCIAL, tenant)

            async def fetch(self) -> Any:
                return unrelated.jwks()

        config = JwtConfig(
            env="local",
            cloud=CloudName.COMMERCIAL,
            tenant_id=tenant,
            audiences=(audience,),
            dev_issuer=issuer.trust(),
        )
        validator = JwtValidator(config, JwksCache(Keys(), ttl_seconds=3600))
        settings = Settings()
        app = create_app(settings)
        compose_app(app, settings, CompositionOverrides(authenticator=validator))

        def bearer(object_id: str) -> dict[str, str]:
            token = issuer.mint(audience=audience, object_id=object_id, now=time.time())
            return {"Authorization": f"Bearer {token}"}

        personas = json.loads(PERSONAS.read_text(encoding="utf-8"))["personas"]
        tokens = {"operator": bearer(OPERATOR_OID)}
        tokens.update({p["slug"]: bearer(p["object_id"]) for p in personas})
        with TestClient(app, raise_server_exceptions=False) as client:
            built = Stack(client, tokens)
            listing = built.call("GET", "/api/v1/me/domains")
            assert listing.status_code == 200, listing.text
            domains = sorted(item["domain_id"] for item in listing.json()["items"])
            assert domains, "the operator reads no domain after the grant"
            populated = [
                d
                for d in domains
                if built.call("GET", f"/api/v1/catalog/domains/{d}/entities?page_size=1")
                .json()
                .get("items")
            ]
            if not populated:
                pytest.skip("the stack is not seeded: see docs/dev/local-setup.md, Real stack")
            built.domain = populated[0]
            try:
                yield built
            finally:
                _deprecate_leftovers(built)


def _etag(response: Any) -> str:
    value = response.headers.get("etag")
    assert value, "the response carries no ETag"
    return str(value)


def _agent_body(name: str, *, create: bool = True) -> dict[str, Any]:
    """An agent document without server-owned keys (``lifecycle_status`` too, on update)."""
    body: dict[str, Any] = {
        "entity_type": "agent",
        "display_name": name,
        "agent_kind": "assistant",
        "platform": "synthetic",
        "source_id": "ui-surfaces-loop",
    }
    if create:
        body["lifecycle_status"] = "active"
    return body


def _owner_body(name: str) -> dict[str, Any]:
    return {
        "entity_type": "owner",
        "lifecycle_status": "active",
        "owner_kind": "team",
        "display_name": name,
    }


def _records(stack: Stack, who: str, domain: str) -> list[dict[str, Any]]:
    """Every record of ``domain``'s chain, read through the domain-path adapter as ``who``.

    The seeded ``sandbox:domain`` id is used unchanged. Since PRP-31 item 14b its chain is the
    source-qualified ``<customer>._7.sandbox.<name>``, so it holds only records written after
    14b (this loop's own writes in steps 2-6). Records the seed wrote earlier sit on the old
    aliased ``<customer>.<name>`` chain and are not read here (not migrated, see the README).
    """
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        query = f"?page_size=200&cursor={cursor}" if cursor else "?page_size=200"
        path = f"/api/v1/audit/domains/{domain}/records{query}"
        response = stack.call("GET", path, who)
        assert response.status_code == 200, response.text
        body = response.json()
        out.extend(body["items"])
        cursor = body.get("next_cursor")
        if not cursor:
            return out


def test_01_catalog_search(stack: Stack) -> None:
    listing = stack.call("GET", f"/api/v1/catalog/domains/{stack.domain}/entities?page_size=50")
    assert listing.status_code == 200, listing.text
    names = [i["display_name"] for i in listing.json()["items"] if i.get("display_name")]
    assert names, "the seeded domain lists no named entity"
    term = max(names[0].split(), key=len)  # a real word of a seeded display name
    body = {"term": term, "budget": SEARCH_BUDGET}
    response = stack.call("POST", f"/api/v1/catalog/domains/{stack.domain}/search", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    hits = result.get("nodes") or result.get("items") or []
    assert hits, f"no search hit in {stack.domain}: {sorted(result)}"


def test_02_create_entity(stack: Stack) -> None:
    name = f"ui-loop-agent-{uuid.uuid4().hex[:8]}"
    path = f"/api/v1/catalog/domains/{stack.domain}/entities"
    refused = stack.call("POST", path, json={**_agent_body(name), "domain_id": stack.domain})
    assert refused.status_code == 422, refused.text
    response = stack.call("POST", path, json=_agent_body(name))
    assert response.status_code == 201, response.text
    entity = response.json()
    assert ENTITY_ID.match(entity["id"]), entity["id"]
    assert entity["domain_id"] == stack.domain
    stack.state.update(entity=entity, etag=_etag(response), name=name)


def test_03_edit_with_if_match(stack: Stack) -> None:
    entity, first = stack.state["entity"], stack.state["etag"]
    path = f"/api/v1/catalog/domains/{stack.domain}/entities/{entity['id']}"
    body = {
        **_agent_body(stack.state["name"], create=False),
        "description": "edited by the ui surfaces loop",
    }
    response = stack.call("PUT", path, json=body, headers={"If-Match": first})
    assert response.status_code == 200, response.text
    second = _etag(response)
    assert second != first
    assert response.json()["description"] == "edited by the ui surfaces loop"
    stale = stack.call("PUT", path, json=body, headers={"If-Match": first})
    assert stale.status_code == 409, stale.text
    stack.state["etag"] = second


def test_04_deprecate_with_reason_code_and_audit(stack: Stack) -> None:
    entity_id = stack.state["entity"]["id"]
    path = f"/api/v1/catalog/entities/{entity_id}/deprecate"
    response = stack.call(
        "POST",
        path,
        json={"reason_code": "superseded"},
        headers={"If-Match": stack.state["etag"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["lifecycle_status"] == "deprecated"
    records = _records(stack, AUDITOR, stack.domain)
    hits = [
        r
        for r in records
        if (r.get("outcome") or {}).get("detail") == "entity_deprecate:reason=superseded"
        and r["subject"]["target"]["canonical_id"] == entity_id
    ]
    assert hits, "no audit record carries entity_deprecate:reason=superseded"
    assert hits[-1]["kind"] == "after"
    assert hits[-1]["outcome"]["verified"] is True


def test_05_recertify(stack: Stack) -> None:
    # Recertification applies to an active owner; a fresh one is created for this step.
    name = f"{CREATED_PREFIX}owner-{uuid.uuid4().hex[:8]}"
    created = stack.call(
        "POST", f"/api/v1/catalog/domains/{stack.domain}/entities", json=_owner_body(name)
    )
    assert created.status_code == 201, created.text
    entity_id = created.json()["id"]
    response = stack.call(
        "POST",
        f"/api/v1/catalog/entities/{entity_id}/recertify",
        json={"valid_for_days": 90, "reason_code": "periodic_review"},
        headers={"If-Match": _etag(created)},
    )
    assert response.status_code == 200, response.text
    stack.state["recertified"] = entity_id


def _find_edge(stack: Stack) -> tuple[str, str] | None:
    """A (domain, edge id) of a seeded edge the operator may curate, or None."""
    for domain in [stack.domain]:
        path = f"/api/v1/catalog/domains/{domain}/entities?entity_type=agent&page_size=200"
        listing = stack.call("GET", path)
        for item in listing.json().get("items", []):
            if str(item.get("display_name", "")).startswith(CREATED_PREFIX):
                continue
            body = {
                "node_id": item["id"],
                "direction": "both",
                "budget": {"timeout_ms": 5000, "limit": 50, "max_depth": 1},
            }
            graph = stack.call("POST", "/api/v1/catalog/lineage/neighbors", json=body)
            if graph.status_code != 200:
                continue
            for edge in graph.json().get("edges", []):
                if edge.get("domain_id") == domain and edge.get("edge_id"):
                    return domain, str(edge["edge_id"])
    return None


def test_06_curation_decision(stack: Stack) -> None:
    found = _find_edge(stack)
    if found is None:
        pytest.skip("OPEN: the seeded world has no curatable edge in the checked domain")
    domain, edge_id = found
    base = f"/api/v1/catalog/domains/{domain}/curation/edges/{edge_id}"
    view = stack.call("GET", base)
    assert view.status_code == 200, view.text
    edge = view.json()
    decision = {
        "decision": "accept",
        "reason": "confirmed by the ui surfaces loop",
        "expected_edge_version": edge["edge_version"],
        "expected_edge_etag": edge["edge_etag"],
    }
    forged = stack.call("POST", f"{base}/decisions", json={**decision, "actor": "someone-else"})
    assert forged.status_code == 422, forged.text
    response = stack.call("POST", f"{base}/decisions", json=decision)
    assert response.status_code == 201, response.text
    result = response.json()
    assert ":person:" in json.dumps(result), result
    records = _records(stack, AUDITOR, domain)
    mine = [r for r in records if r.get("channel") == "button" and edge_id in json.dumps(r)]
    assert mine, "no button-channel audit record names the decided edge"


def test_07_stale_agents_dry_run_then_confirm(stack: Stack) -> None:
    # The widest window: only an agent unobserved for ~10 years is a candidate, so no seeded
    # agent is marked. The plan is still derived and confirmed through the real routes.
    plan_response = stack.call(
        "POST", "/api/v1/catalog/reconcile/stale-agents/dry-run", json={"window_days": 3650}
    )
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()
    assert plan["truncated"] is False
    confirm = {
        "plan_id": plan["plan_id"],
        "as_of": plan["as_of"],
        "window_days": plan["window_days"],
        "candidates": [{"agent_id": c["agent_id"], "etag": c["etag"]} for c in plan["candidates"]],
    }
    outcome = stack.call("POST", "/api/v1/catalog/reconcile/stale-agents/confirm", json=confirm)
    assert outcome.status_code == 200, outcome.text
    assert all(i["status"] == "marked" for i in outcome.json()["items"]), outcome.text


def test_08_auditor_only_persona(stack: Stack) -> None:
    assert ":sandbox:domain:" in stack.domain, stack.domain  # a seeded, non-catalog source
    domains = stack.call("GET", "/api/v1/me/domains", AUDITOR)
    assert domains.status_code in (200, 403), domains.text
    if domains.status_code == 200:
        assert domains.json()["items"] == []
    listing = stack.call("GET", "/api/v1/audit/domains", AUDITOR)
    assert listing.status_code == 200, listing.text
    items = listing.json()["items"]
    assert items, "the auditor reads no audit domain"
    assert stack.domain in {i["domain_id"] for i in items}
    records = _records(stack, AUDITOR, stack.domain)
    # Fresh records written through the API by steps 2-6 of this run, on the qualified chain.
    created = stack.state["entity"]["id"]
    assert any(r["subject"]["target"]["canonical_id"] == created for r in records), created
    assert {r["chain_id"] for r in records} == {_chain(stack.domain)}
    verify = stack.call("GET", f"/api/v1/audit/domains/{stack.domain}/verify", AUDITOR)
    assert verify.status_code == 200, verify.text
    assert verify.json()["ok"] is True, verify.text
    assert verify.json()["chain_id"] == _chain(stack.domain)
    # The generic chain route maps the source-qualified chain back to the same seeded domain.
    by_chain = stack.call("GET", f"/api/v1/audit/chains/{_chain(stack.domain)}/verify", AUDITOR)
    assert by_chain.status_code == 200, by_chain.text
    assert by_chain.json() == verify.json()
    # The pre-14b aliased chain names the catalog domain of that name: not this auditor's.
    legacy = f"{stack.domain.split(':')[1]}.{stack.domain.rsplit(':', 1)[-1]}"
    refused = stack.call("GET", f"/api/v1/audit/chains/{legacy}/verify", AUDITOR)
    assert refused.status_code == 403, refused.text


def _chain(domain: str) -> str:
    """The source-qualified chain of a seeded domain, ``<customer>._<n>.<source>.<name>``."""
    _, customer, source, _, name = domain.split(":")
    return f"{customer}._{len(source)}.{source}.{name}"


def test_09_emergency_disable_round_trip(stack: Stack) -> None:
    path = "/api/v1/actions/emergency-disable"
    before = stack.call("GET", path)
    assert before.status_code == 200, before.text
    try:
        on = stack.call("PUT", path, json={"disabled": True, "reason": "ui_surfaces_loop"})
        assert on.status_code == 200, on.text
        read_on = stack.call("GET", path).json()
        assert read_on["disabled"] is True
        assert read_on["reason"] == "ui_surfaces_loop"
    finally:
        off = stack.call("PUT", path, json={"disabled": False})
        assert off.status_code == 200, off.text
    assert stack.call("GET", path).json()["disabled"] is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/evaluation/domains/{d}/results",
        "/api/v1/finops/domains/{d}/forecast",
        "/api/v1/federation/summary",
    ],
)
def test_10_reads_answer_200(path: str, stack: Stack) -> None:
    response = stack.call("GET", path.replace("{d}", stack.domain))
    if (
        response.status_code == 409
        and path.endswith("/forecast")
        and response.json().get("reason") == "price_version_unresolved"
    ):
        # The typed refusal, not a failure of the route: the compose price sheet
        # (infra/dev/ledger-prices.dev.json) prices only `synthetic-model`, so every sandbox
        # estimate is price_unresolved and there is nothing to forecast from.
        pytest.skip("OPEN: forecast answers 409 price_version_unresolved on the seeded world")
    assert response.status_code == 200, response.text
