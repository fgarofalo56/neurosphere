"""PRP-29 item 11: every manifest page is served by the composed API on the seeded stack.

Needs the SEEDED real stack: the compose emulators plus the seed (``make stack-up``, or
``make seed-stack`` against a running stack) in the default ``neurosphere`` database. This suite
never starts or stops compose. The operator is a fixed synthetic object id that this suite grants
every role over the seeded domains through ``sbx_grant_operator`` (the same step a human runs).

The app is the production composition (``create_app`` + ``compose_app`` with the default builders
over the emulators). Only the token validator is a TEST stand-in, handed in through
``CompositionOverrides``: the ``ScopeDeriver`` over the Cosmos policy store, the revocation
checker and the pseudonym key are the composed ones. Nothing here is reachable from compose or
``main``.

The route -> calls map lives in ``services/api/tests/runtime_routes/manifest_calls.py`` (shared with
the CI-safe suite) and is derived from the frontend api modules. For each route every readable
domain is requested; every call must answer 200 and, for calls that declare a ``non_empty`` field,
at least one domain must return it non-empty (the seed does not fill every domain with every
category). The only exceptions are listed, with the reason, in ``EXPECTED_STATUS`` (non-200) and
``KNOWN_EMPTY`` (200 but empty). Both are strict: an entry that no longer holds fails the test, so
a fixed gap cannot linger in the list.

Run: ``NS_PROBE_COSMOS_URL=http://127.0.0.1:8081/ MSYS_NO_PATHCONV=1 uv run pytest -q -m integration
tests/integration/real_stack/test_manifest_routes.py``.
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, Final
from urllib.parse import urlencode

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
CALLS_FILE: Final = ROOT / "services/api/tests/runtime_routes/manifest_calls.py"
GRANT_SCRIPT: Final = ROOT / "scripts/sandbox/sbx_grant_operator.py"
PERSONAS: Final = ROOT / "sandbox/stack/personas.json"
MANIFEST: Final = ROOT / "frontend/src/app/route-manifest.json"
LOOPBACK: Final = "http://127.0.0.1:8081"
#: A fixed, synthetic, non-secret object id for this suite's operator.
OPERATOR_OID: Final = "5b0a9c8d-7e6f-4a5b-8c4d-3e2f1a0b9c8d"
ROLES: Final = ("viewer", "analyst", "domain_steward", "security_auditor", "admin")
#: The grant script's generator profile (the seed profile "small" is the generator's "tiny").
GENERATOR_PROFILE: Final = "tiny"

#: Expected non-200 answers: call key -> (status, why). Nothing else may be non-200.
EXPECTED_STATUS: Final[dict[str, tuple[int, str]]] = {
    "/api/v1/sandbox/status": (
        503,
        "sandbox mode reads the isolated `sandbox-neurosphere` database, which only the separate "
        "`make seed` (sandbox seed) creates; the real-stack seed does not",
    ),
}

#: 200 answers that are empty in every readable domain: call key -> why. OPEN findings, reported.
KNOWN_EMPTY: Final[dict[str, str]] = {
    "/api/v1/dashboards/domains/{domain}/cost?days=1": (
        "the seed's telemetry is dated 2026-10-01..04 and the 1-day window ends now"
    ),
    "/api/v1/map/domains/{domain}/viewport?node_budget=2000": (
        "the seed creates no catalog entities (the catalog container holds edges only), and the "
        "viewport lists agents, grounding sources, model deployments and people"
    ),
    "/api/v1/map/domains/{domain}/viewport": "same: no catalog entities to list",
    "/api/v1/replay/domains/{domain}/traces?page_size=25": (
        "the archive reader looks back 7 days from today and the seed's archive is dated "
        "2026-10-01..04"
    ),
}


def _seed_tenant() -> str:
    """The tenant the stack was seeded under: the personas' principals only exist there."""
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


calls = _load(CALLS_FILE, "ns_manifest_calls")


def _key(call: Any) -> str:
    query = urlencode(list(call.query))
    return f"{call.path}?{query}" if query else str(call.path)


def _pluck(body: Any, pointer: tuple[str | int, ...]) -> Any:
    for step in pointer:
        try:
            body = body[step]
        except (KeyError, IndexError, TypeError):
            return None
    return body


def _has(body: Any, field: str) -> bool:
    return bool(body.get(field)) if isinstance(body, dict) else False


class Stack:
    def __init__(
        self, client: TestClient, tokens: dict[str, dict[str, str]], domains: list[str]
    ) -> None:
        self.client = client
        self.tokens = tokens
        self.domains = domains

    def get(self, path: str, query: tuple[tuple[str, str], ...], persona: str | None) -> Any:
        headers = self.tokens[persona or "operator"]
        return self.client.get(path, params=list(query), headers=headers)


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
        for name in ("NS_STORE_DATABASE", "NS_AUTH_CUSTOMER_ID", "NS_COPILOT_MODE"):
            mp.delenv(name, raising=False)  # the seeded defaults: neurosphere / synthco / disabled

        asyncio.run(_ensure_containers())  # harmless on a seeded stack; lets an empty one skip
        grant = _load(GRANT_SCRIPT, "ns_grant_operator")
        for role in ROLES:
            argv = [
                *("--object-id", OPERATOR_OID),
                *("--role", role),
                *("--tenant-id", tenant),
                *("--profile", GENERATOR_PROFILE),
            ]
            code = grant.main(argv, env=dict(os.environ))
            assert code == 0, f"grant {role} exited {code}"

        issuer = DevIssuer(Settings(env="local"), tenant_id=tenant, kid="manifest-stand-in")
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
            listing = client.get("/api/v1/me/domains", headers=tokens["operator"])
            assert listing.status_code == 200, listing.text
            domains = [item["domain_id"] for item in listing.json()["items"]]
            assert domains, "the operator reads no domain after the grant"
            seeded = any(
                client.get(f"/api/v1/recommendations/domains/{d}", headers=tokens["operator"])
                .json()
                .get("items")
                for d in domains
            )
            if not seeded:
                pytest.skip("the stack is not seeded: run `make stack-up` or `make seed-stack`")
            analyst = client.get("/api/v1/me/domains", headers=tokens["analyst"])
            assert analyst.status_code == 200, (
                "the seeded analyst persona is unknown here: export the tenant the stack was "
                "seeded under (NS_ENTRA_TENANT_ID or NS_AUTH_TENANT_ID)"
            )
            yield Stack(client, tokens, domains)


def test_the_call_map_covers_exactly_the_manifest() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))["routes"]
    assert len(manifest) == 26
    assert sorted(calls.MANIFEST_CALLS) == sorted(manifest)


@pytest.mark.parametrize("route", sorted(calls.MANIFEST_CALLS))
def test_route_is_served_with_data(route: str, stack: Stack) -> None:
    failures: list[str] = []
    seen_data: dict[str, bool] = {}
    for domain in stack.domains:
        captured: dict[str, str] = {}
        for call in calls.MANIFEST_CALLS[route]:
            if any(need not in captured for need in call.needs):
                continue  # nothing was listed in this domain to open a detail page with
            path = call.path.replace("{domain}", domain)
            for name, value in captured.items():
                path = path.replace("{" + name + "}", value)
            response = stack.get(path, call.query, call.as_persona)
            expected = EXPECTED_STATUS.get(_key(call))
            if expected is not None:
                if response.status_code != expected[0]:
                    failures.append(f"{path}: {response.status_code}, expected {expected[0]}")
                continue
            if response.status_code != 200:
                failures.append(f"{path}: {response.status_code} {response.text[:200]}")
                continue
            body = response.json()
            for name, pointer in call.capture:
                value = _pluck(body, pointer)
                if isinstance(value, str) and name not in captured:
                    captured[name] = value
            if call.non_empty is not None:
                key = _key(call)
                seen_data[key] = seen_data.get(key, False) or _has(body, call.non_empty)
    assert not failures, "\n".join(failures)
    empty = {key for key, ok in seen_data.items() if not ok}
    unexpected = sorted(empty - set(KNOWN_EMPTY))
    assert not unexpected, f"200 but empty in every readable domain: {unexpected}"
    fixed = sorted(key for key in seen_data if seen_data[key] and key in KNOWN_EMPTY)
    assert not fixed, f"now has data; remove from KNOWN_EMPTY: {fixed}"


def test_copilot_routes_answer_the_disabled_503(stack: Stack) -> None:
    """Copilot defaults to disabled in the real stack: 503 copilot_unconfigured, never a 500."""
    response = stack.client.get("/api/v1/copilot/conversations", headers=stack.tokens["operator"])
    assert response.status_code == 503, response.text
    assert response.json()["reason"] == "copilot_unconfigured"
