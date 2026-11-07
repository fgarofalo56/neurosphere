"""The composed NeuroSphere API served over real HTTP on 127.0.0.1 (PRP-22 audit close-out, lane R).

Integration-only support for ``test_mcp_compose_roundtrip.py`` and ``test_mcp_real_stack_live.py``.
It needs the compose emulators ALREADY running (``docker compose up -d --wait``: Cosmos on
``127.0.0.1:8081``, Azurite, Event Hubs); it never starts or stops compose.

What runs is the production composition (``create_app`` + ``compose_app`` with the default
builders), configured ONLY through the process environment (no file):

* ``NS_ENV=local``, a throwaway Cosmos database (``NS_STORE_DATABASE=ns_mcp_live_<hex>``, created by
  the local bootstrap, deleted afterwards), the emulator key built at runtime (ignored by the
  emulator, never a literal);
* ``NS_MCP_RESOURCE_SERVER_URL`` / ``NS_MCP_AUDIENCES`` / ``NS_MCP_REQUIRED_SCOPE`` /
  ``NS_MCP_ALLOWED_HOSTS``, so the MCP builder mounts ``/mcp`` (it is disabled without them).

The only test stand-ins are the two token validators, handed in through
``CompositionOverrides`` exactly as ``tests/integration/real_stack/conftest.py`` does: a local dev
issuer (``DevIssuer``, ``NS_ENV=local`` only) trusted by the REST validator (REST audience) and by
the MCP validator (MCP audience). Everything after token validation is the composed production
path: the ``ScopeDeriver`` over the Cosmos policy store, the Cosmos revocation checker, the
settings-resolved pseudonym key, the Cosmos catalog, the Cosmos MCP registry and the SSRF-vetted
``ExternalMcpClient`` of the admin plane (real DNS, no stub).

Data: the synthetic sandbox catalog (``scripts/sandbox/sbx_seed_catalog.py --profile small``) is
seeded into the throwaway database, then principals are granted with the operator-grant code
(``scripts/sandbox/sbx_grant_operator.py``): a viewer on ONE sandbox domain, an analyst on the
same domain and an admin on all of them. Tokens are minted at runtime and never printed.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import importlib.util
import os
import socket
import sys
import threading
import time
import uuid
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import httpx
import uvicorn
from azure.cosmos.aio import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
)
from neurosphere_api.app import create_app
from neurosphere_api.runtime import CompositionOverrides, compose_app
from neurosphere_core.auth.jwt import DevIssuer, JwksCache, JwtConfig, JwtValidator, entra_jwks_uri
from neurosphere_core.cloud import CloudName, Settings

REPO: Final = Path(__file__).resolve().parents[3]
SANDBOX: Final = REPO / "scripts" / "sandbox"
COSMOS: Final = "http://127.0.0.1:8081"
TENANT: Final = "5e1c0a7d-2b3f-4c8e-9a1d-7f6e5d4c3b2a"
WORKER_OID: Final = "7d2e3f40-5b6c-4d7e-9f80-a1b2c3d4e5f6"
CUSTOMER: Final = "synthco"
REST_AUDIENCE: Final = "api://neurosphere-live-rest"
MCP_AUDIENCE: Final = "api://neurosphere-live-mcp"
MCP_HOST: Final = "mcp.neurosphere.test"
MCP_RESOURCE: Final = f"https://{MCP_HOST}/mcp"
MCP_SCOPE: Final = "mcp.invoke"
PROTOCOL: Final = "2026-07-28"
_KID: Final = "mcp-live-stand-in"
#: The smallest seed profile ``sbx_seed_catalog`` offers (``scripts/sandbox`` profiles.json).
SEED_PROFILE: Final = "small"


def _key() -> str:
    return base64.b64encode(b"emulator-ignores-this").decode()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _load(name: str) -> ModuleType:
    for path in (SANDBOX, REPO):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(f"mcp_live_{name}", SANDBOX / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def live_environment(database: str, port: int) -> dict[str, str]:
    """Every variable the composed app reads for this run (process environment only)."""
    return {
        "NS_ENV": "local",
        "NS_CLOUD": "commercial",
        "NS_COSMOS_ENDPOINT": COSMOS,
        "NS_COSMOS_KEY": _key(),
        "NS_BLOB_CONNECTION_STRING": "UseDevelopmentStorage=true",
        "NS_STORE_DATABASE": database,
        "NS_AUTH_TENANT_ID": TENANT,
        "NS_AUTH_AUDIENCES": REST_AUDIENCE,
        "NS_AUTH_CUSTOMER_ID": CUSTOMER,
        "NS_WORKER_OBJECT_ID": WORKER_OID,
        "NS_COPILOT_MODE": "disabled",
        "NS_SEARCH_PROVIDER": "fixture",
        "NS_FOUNDRY_ENABLED": "false",
        "NS_APIM_ENABLED": "false",
        "NS_CORS_ALLOWED_ORIGINS": "",
        "NS_MCP_RESOURCE_SERVER_URL": MCP_RESOURCE,
        "NS_MCP_AUDIENCES": f'["{MCP_AUDIENCE}"]',
        "NS_MCP_REQUIRED_SCOPE": MCP_SCOPE,
        "NS_MCP_ALLOWED_HOSTS": f'["127.0.0.1:{port}"]',
    }


@contextmanager
def patched_environ(values: Mapping[str, str]) -> Iterator[None]:
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class _UnrelatedEntraKeys:
    """Entra JWKS stand-in with one unrelated key: only the stand-in issuer's kid validates."""

    def __init__(self, tenant_id: str) -> None:
        self._url = entra_jwks_uri(CloudName.COMMERCIAL, tenant_id)
        self._jwks = DevIssuer(Settings(env="local"), tenant_id=tenant_id, kid="unrelated").jwks()

    @property
    def url(self) -> str:
        return self._url

    async def fetch(self) -> Any:
        return self._jwks


def _validator(issuer: DevIssuer, audience: str) -> JwtValidator:
    config = JwtConfig(
        env="local",
        cloud=CloudName.COMMERCIAL,
        tenant_id=TENANT,
        audiences=(audience,),
        dev_issuer=issuer.trust(),
    )
    return JwtValidator(config, JwksCache(_UnrelatedEntraKeys(TENANT), ttl_seconds=3600))


@dataclass
class Principal:
    name: str
    object_id: str
    role: str
    domains: tuple[str, ...]


@dataclass
class LiveStack:
    port: int
    database: str
    issuer: DevIssuer
    principals: dict[str, Principal]
    domains: tuple[str, ...]
    environment: dict[str, str]
    seed_summary: str

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def token(
        self,
        who: str,
        *,
        audience: str = MCP_AUDIENCE,
        scopes: Sequence[str] = (MCP_SCOPE,),
    ) -> str:
        return self.issuer.mint(
            audience=audience,
            object_id=self.principals[who].object_id,
            now=time.time(),
            scopes=tuple(scopes),
        )

    def rest_headers(self, who: str) -> dict[str, str]:
        return bearer(self.token(who, audience=REST_AUDIENCE, scopes=()))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": "Bear" + "er " + token}


def rpc_body(method: str, params: dict[str, Any] | None = None, rid: int = 1) -> dict[str, Any]:
    body: dict[str, Any] = dict(params or {})
    body["_meta"] = {
        PROTOCOL_VERSION_META_KEY: PROTOCOL,
        CLIENT_CAPABILITIES_META_KEY: {},
        CLIENT_INFO_META_KEY: {"name": "ns-mcp-live", "version": "0.0.1"},
    }
    return {"jsonrpc": "2.0", "id": rid, "method": method, "params": body}


def _seeded_domains(seeder: ModuleType, environ: Mapping[str, str]) -> tuple[str, ...]:
    """The domain ids of the world the seeder generated (same config, same generator)."""
    from sandbox.world import World  # pyright: ignore[reportMissingImports]

    seed = seeder.seed
    config = seed.resolve_config(SEED_PROFILE, None, environ)
    return tuple(sorted(seed.world_domains(World(seed.generate_config(config)))))


async def _grant(module: ModuleType, env: dict[str, str], who: Principal) -> str:
    principal_id = module._principal_id(  # pyright: ignore[reportPrivateUsage]
        env=env, tenant=TENANT, customer=CUSTOMER, cloud="commercial", object_id=who.object_id
    )
    return await module._run_real(  # pyright: ignore[reportPrivateUsage]
        env,
        COSMOS,
        _key(),
        customer_id=CUSTOMER,
        principal_id=principal_id,
        role=who.role,
        domain_ids=who.domains,
    )


class ServerThread:
    def __init__(self, app: Any, port: int) -> None:
        config = uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="warning", lifespan="on", ws="none"
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self.server.run, name=f"ns-mcp-live-{port}", daemon=True
        )

    def start(self, timeout: float = 120.0) -> None:
        self.thread.start()
        deadline = time.monotonic() + timeout
        while not self.server.started:
            if not self.thread.is_alive():
                raise RuntimeError("the composed API exited during startup")
            if time.monotonic() > deadline:
                raise TimeoutError("the composed API did not start")
            time.sleep(0.1)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=60)


@asynccontextmanager
async def live_stack() -> AsyncIterator[LiveStack]:
    """Seed, grant, compose and serve; tear everything down (server, database) afterwards."""
    port = free_port()
    database = f"ns_mcp_live_{uuid.uuid4().hex[:12]}"
    env = live_environment(database, port)
    with patched_environ(env):
        environ = dict(os.environ)
        try:
            seeder = _load("sbx_seed_catalog")
            code = await asyncio.to_thread(seeder.main, ["--profile", SEED_PROFILE], env=environ)
            if code != 0:
                raise RuntimeError(f"catalog seed exited {code}")
            domains = _seeded_domains(seeder, environ)
            granter = _load("sbx_grant_operator")
            assert len(domains) >= 2, domains
            principals = {
                name: Principal(name, str(uuid.uuid4()), role, scope)
                for name, role, scope in (
                    ("viewer", "viewer", domains[:1]),
                    ("analyst", "analyst", domains[:1]),
                    ("admin", "admin", domains),
                )
            }
            for who in principals.values():
                await _grant(granter, environ, who)

            issuer = DevIssuer(Settings(env="local"), tenant_id=TENANT, kid=_KID)
            settings = Settings()
            app = create_app(settings)
            compose_app(
                app,
                settings,
                CompositionOverrides(
                    authenticator=_validator(issuer, REST_AUDIENCE),
                    backends={"mcp_validator": _validator(issuer, MCP_AUDIENCE)},
                ),
            )
            server = ServerThread(app, port)
            server.start()
            try:
                yield LiveStack(
                    port=port,
                    database=database,
                    issuer=issuer,
                    principals=principals,
                    domains=domains,
                    environment={k: v for k, v in env.items() if k != "NS_COSMOS_KEY"},
                    seed_summary=f"sbx_seed_catalog --profile {SEED_PROFILE} exit={code}",
                )
            finally:
                server.stop()
        finally:
            async with CosmosClient(COSMOS, _key(), enable_endpoint_discovery=False) as client:
                # Not found = the run failed before the local bootstrap created it.
                with contextlib.suppress(CosmosResourceNotFoundError):
                    await client.delete_database(database)


def http_client(stack: LiveStack) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=stack.base_url, timeout=30.0)


def rpc_headers(method: str, name: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": PROTOCOL,
        "Mcp-Method": method,
        "Host": MCP_HOST,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    return headers


async def mcp_rpc(
    http: httpx.AsyncClient,
    method: str,
    params: dict[str, Any] | None = None,
    *,
    token: str | None,
) -> httpx.Response:
    """One 2026-07-28 single-exchange JSON-RPC POST to the live ``/mcp`` route."""
    name = None
    if method == "tools/call" and params is not None:
        name = str(params["name"])
    headers = rpc_headers(method, name)
    if token is not None:
        headers.update(bearer(token))
    return await http.post("/mcp", json=rpc_body(method, params), headers=headers)


def record_domains(response: httpx.Response) -> set[str]:
    result = response.json()["result"]
    assert result["isError"] is False, result
    return {row["data"]["domain_id"] for row in result["structuredContent"]["records"]}
