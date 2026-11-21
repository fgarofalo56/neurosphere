"""TEST-ONLY launcher: the composed API plus the worker roles, behind a stand-in token validator.

PRP-38 item 6. The headless real-stack Playwright run (``NS_REAL_STACK_MODE=ci``) needs an API it
can sign in to without Entra. This script composes the production app (``create_app`` +
``compose_app`` with the default builders over the compose emulators) and overrides ONLY the
authenticator with a validator that trusts an in-memory ``DevIssuer`` (the same recipe as
``conftest.py``). The ``ingestion``, ``projections`` and ``aggregates`` roles run in the same
process, as the compose ``workers`` service does.

It is never imported by ``main``, compose or any package, and binds loopback only. The issuer key
lives in memory; the operator's bearer token is written to ``NS_STAND_IN_TOKEN_FILE`` (a
gitignored path, mode 0600) so the browser harness can build its session. The token is never
printed.

    python tests/integration/real_stack/serve_stand_in_api.py        # serve (API + workers)
    python tests/integration/real_stack/serve_stand_in_api.py seed   # seed, grant the operator

Environment: ``NS_STAND_IN_API_PORT`` (default 8765), ``NS_STAND_IN_TOKEN_FILE``. Everything
else is set here for the emulators; an already-exported value wins.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import importlib.util
import os
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[3]
SEED_SCRIPT: Final = ROOT / "scripts" / "sandbox" / "sbx_seed_stack.py"
GRANT_SCRIPT: Final = ROOT / "scripts" / "sandbox" / "sbx_grant_operator.py"
TENANT: Final = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
AUDIENCE: Final = "api://neurosphere-real-stack-browser"
WORKER_OID: Final = "6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"
OPERATOR_OID: Final = "7d2e3f40-5b6c-4d7e-8f90-a1b2c3d4e5f6"
DATABASE: Final = "ns_browser_flows"
ROLES: Final = ("ingestion", "projections", "aggregates")


def _azurite_connection() -> str:
    """The development account's connection string, assembled from the SDK at runtime."""
    from azure.storage.blob.aio import ContainerClient

    probe = ContainerClient.from_connection_string("UseDevelopmentStorage=true;", "probe")
    credential = probe.credential
    name, secret = credential.account_name, credential.account_key  # type: ignore[union-attr]
    endpoint = probe.primary_endpoint.rsplit("/", 1)[0]
    return (
        "DefaultEndpointsProtocol=http;"
        + f"AccountName={name};"
        + f"AccountKey={secret};BlobEndpoint={endpoint};"
    )


def _eventhubs_connection() -> str:
    parts = [
        "Endpoint=sb://127.0.0.1",
        "SharedAccessKeyName=RootManageSharedAccessKey",
        "SharedAccessKey=" + "SAS_KEY" + "_VALUE",
        "UseDevelopmentEmulator=true",
    ]
    return ";".join(parts) + ";"


def apply_environment() -> None:
    values = {
        "NS_ENV": "local",
        "NS_COSMOS_ENDPOINT": "http://127.0.0.1:8081",
        "NS_COSMOS_KEY": base64.b64encode(b"emulator-ignores-this").decode(),
        "NS_EVENTHUBS_CONNECTION_STRING": _eventhubs_connection(),
        "NS_BLOB_CONNECTION_STRING": _azurite_connection(),
        "NS_STORE_DATABASE": DATABASE,
        "NS_INGESTION_CHECKPOINT_CONTAINER": "ns-ckpt-browser",
        "NS_INGESTION_MAX_WAIT_SECONDS": "1",
        "NS_ARCHIVE_CONTAINER": "ns-arch-browser",
        "NS_QUARANTINE_CONTAINER": "ns-quar-browser",
        "NS_AUTH_CUSTOMER_ID": "synthco",
        "NS_AUTH_TENANT_ID": TENANT,
        "NS_AUTH_AUDIENCES": AUDIENCE,
        "NS_WORKER_TENANT_ID": TENANT,
        "NS_WORKER_OBJECT_ID": WORKER_OID,
        "NS_WORKER_POLL_SECONDS": "1",
        "NS_WORKER_HEALTH_PORT": "0",
        "NS_SEED_POLL_SECONDS": "3",
        "NS_SEED_WAIT_SECONDS": "420",
        "NS_SEED_DRAIN_SECONDS": "45",
        # Same in-process catalog search as the compose stack (docker-compose.yml); without it the
        # agent matcher (PRP-72) is not composed and the find-an-agent page (PRP-75) answers 409.
        "NS_SEARCH_PROVIDER": "fixture",
    }
    for name, value in values.items():
        os.environ.setdefault(name, value)
    for name in ("NS_CLOUD", "NS_AUTH_PSEUDONYM_KEY", "NS_AUTH_PSEUDONYM_KEY_REFERENCE"):
        os.environ.pop(name, None)


def _load_seed() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sbx_seed_stack_browser", SEED_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    with contextlib.suppress(OSError):
        path.chmod(0o600)


async def serve() -> int:
    import uvicorn
    from neurosphere_api.app import create_app
    from neurosphere_api.runtime import CompositionOverrides, compose_app
    from neurosphere_core.auth.jwt import (
        DevIssuer,
        JwksCache,
        JwtConfig,
        JwtValidator,
        entra_jwks_uri,
    )
    from neurosphere_core.clients import ClientLifetime, create_cosmos_client
    from neurosphere_core.cloud import CloudName, Settings
    from neurosphere_core.stores import ensure_local_containers
    from neurosphere_workers.runtime.factories import RuntimeConfig, role_factories
    from neurosphere_workers.runtime.supervisor import RoleSupervisor

    tenant = os.environ["NS_AUTH_TENANT_ID"]
    audience = os.environ["NS_AUTH_AUDIENCES"].split(",")[0].strip()
    issuer = DevIssuer(Settings(env="local"), tenant_id=tenant, kid="browser-stand-in")
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
    cfg = RuntimeConfig.from_env()
    async with ClientLifetime() as lifetime:
        cosmos = create_cosmos_client(cfg.settings, lifetime=lifetime)
        await ensure_local_containers(cosmos, Settings(env="local"), database=cfg.store.database)

    app = create_app(settings)
    compose_app(app, settings, CompositionOverrides(authenticator=validator))

    token_file = os.environ.get("NS_STAND_IN_TOKEN_FILE")
    if token_file:
        token = issuer.mint(
            audience=audience,
            object_id=os.environ.get("NS_STAND_IN_OPERATOR_OID", OPERATOR_OID),
            now=time.time(),
            lifetime_seconds=6 * 3600,
        )
        await asyncio.to_thread(_write_token, Path(token_file), token)

    supervisor = RoleSupervisor(role_factories(cfg, ROLES))
    runner = asyncio.create_task(supervisor.run())
    port = int(os.environ.get("NS_STAND_IN_API_PORT", "8765"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    try:
        await server.serve()
    finally:
        supervisor.request_shutdown()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(runner, timeout=60)
    return 0


def seed() -> int:
    operator = os.environ.get("NS_STAND_IN_OPERATOR_OID", OPERATOR_OID)
    code = int(_load_seed().main(["--profile", "small", "--operator-object-id", operator]))
    if code != 0:
        return code
    # The review queue needs a reviewer: "admin is not a reviewer", so add the steward role.
    spec = importlib.util.spec_from_file_location("ns_grant_operator_browser", GRANT_SCRIPT)
    assert spec and spec.loader
    grant = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = grant
    spec.loader.exec_module(grant)
    argv = [
        *("--object-id", operator),
        *("--role", "domain_steward"),
        *("--tenant-id", os.environ["NS_AUTH_TENANT_ID"]),
        *("--profile", "tiny"),
    ]
    return int(grant.main(argv, env=dict(os.environ)))


def main(argv: list[str]) -> int:
    apply_environment()
    if argv[:1] == ["seed"]:
        return seed()
    if argv:
        print("usage: serve_stand_in_api.py [seed]", file=sys.stderr)
        return 2
    return asyncio.run(serve())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
