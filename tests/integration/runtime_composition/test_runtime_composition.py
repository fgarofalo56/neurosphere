"""PRP-35 smoke: the composed compose stack holds data and (not) writes.

Needs the emulators, the `api` service (profile `app`) and a completed seed, all on 127.0.0.1:

    docker compose --profile app up -d --build --wait api
    docker compose --profile seed run --rm --build seed
    uv run pytest -q -m integration tests/integration/runtime_composition

Everything skips cleanly when the api or the Cosmos emulator is not reachable, or the catalog is
not seeded. The seed grants the worker principal under ``NS_ENTRA_TENANT_ID`` (the same variable
compose reads); export the same value for the seed and this test, otherwise the placeholder
GUID below is used by both. No credential is committed: the only secret-like value is the
documented DEV-ONLY ingest bearer token from docs/runbooks/ingest.md.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import urllib.error
import urllib.request
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
API = "http://127.0.0.1:8000"
COSMOS = ("127.0.0.1", 8081)
# DEV ONLY throwaway producer (infra/dev/ingest-producers.dev.json, docs/runbooks/ingest.md).
DEV_TOKEN = "dev-ingest.ns-dev-only-ingest-secret"
DEV_SOURCE = "dev-source"
TENANT = os.environ.get("NS_ENTRA_TENANT_ID") or str(uuid.UUID(int=1))
WORKER_OID = os.environ.get("NS_WORKER_OBJECT_ID") or "7d2e3f40-5b6c-4d7e-9f80-a1b2c3d4e5f6"


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _http(
    method: str, path: str, *, body: bytes | None = None, headers: dict[str, str] | None = None
) -> tuple[int, bytes]:
    request = urllib.request.Request(API + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@pytest.fixture(scope="module")
def api_up() -> None:
    if not _port_open("127.0.0.1", 8000):
        pytest.skip("api is not running on 127.0.0.1:8000 (docker compose --profile app up api)")
    status, _ = _http("GET", "/readyz")
    if status != 200:
        pytest.skip(f"api /readyz answered {status}")


@pytest.fixture(scope="module")
def emulator_up() -> None:
    if not _port_open(*COSMOS):
        pytest.skip("Cosmos emulator is not running on 127.0.0.1:8081")


def _ingest_event() -> bytes:
    event_id = uuid.uuid4().hex
    return json.dumps(
        [
            {
                "specversion": "1.0",
                "id": event_id,
                "source": "urn:neurosphere:runtime-composition-smoke",
                "type": "com.neurosphere.telemetry.v1",
                "data": {"event_id": event_id, "source_id": DEV_SOURCE},
            }
        ]
    ).encode()


# -- ingest ------------------------------------------------------------------------------------


def test_ingest_is_configured_and_not_503(api_up: None) -> None:
    status, body = _http("GET", "/readyz")
    assert status == 200
    assert "composition.ingest.disabled" not in json.loads(body)["dependencies"]


def test_dev_producer_authenticates_on_the_ingest_edge(api_up: None) -> None:
    # An empty OTLP document is accepted by a configured edge: 2xx, never 503 ingest_not_configured.
    status, body = _http(
        "POST",
        "/v1/ingest/otlp/traces",
        body=json.dumps({"resourceSpans": []}).encode(),
        headers={"Authorization": f"Bearer {DEV_TOKEN}", "content-type": "application/json"},
    )
    assert 200 <= status < 300, (status, body[:300])


def test_wrong_secret_is_rejected_not_503(api_up: None) -> None:
    status, _ = _http(
        "POST",
        "/v1/ingest/otlp/traces",
        body=b"{}",
        headers={"Authorization": "Bearer dev-ingest.wrong", "content-type": "application/json"},
    )
    assert status == 401


# -- seeded catalog and search (in-process, scoped as the workers' own principal) ----------------


@pytest_asyncio.fixture
async def catalog() -> AsyncIterator[tuple[Any, Any, Any]]:
    import sys

    for path in (REPO_ROOT / "scripts" / "sandbox", REPO_ROOT):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    import sbx_seed_stack as seed  # type: ignore[import-not-found]

    environ = {
        **os.environ,
        "NS_ENV": "local",
        "NS_COSMOS_ENDPOINT": "http://127.0.0.1:8081",
        "NS_STORE_DATABASE": "neurosphere",
        "NS_AUTH_CUSTOMER_ID": "synthco",
        "NS_AUTH_TENANT_ID": TENANT,
        "NS_WORKER_OBJECT_ID": WORKER_OID,
    }
    config = seed.resolve_config("small", None, environ)
    async with AsyncExitStack() as stack:
        with seed.scoped_environ({**environ, **config.environ()}):
            backends = await seed.open_backends(config, stack)
            scope = await seed.worker_scope(backends, config)
            yield backends.catalog, scope, config


@pytest.mark.usefixtures("emulator_up")
async def test_catalog_is_seeded(catalog: tuple[Any, Any, Any]) -> None:
    from neurosphere_core.catalog.protocol import EntityFilter
    from neurosphere_core.paging import PageRequest

    repo, scope, _ = catalog
    page = await repo.list_entities(scope, EntityFilter(), PageRequest(page_size=50))
    if not page.items:
        pytest.skip("catalog is empty: run `docker compose --profile seed run --rm seed`")
    assert len(page.items) > 0


@pytest.mark.usefixtures("emulator_up")
async def test_catalog_search_returns_a_hit(catalog: tuple[Any, Any, Any]) -> None:
    from neurosphere_api.runtime.builders.search import IndexedGraphQuery
    from neurosphere_contracts.query.v1.budget import Budget
    from neurosphere_core.catalog.protocol import EntityFilter, GraphSearchRequest
    from neurosphere_core.paging import PageRequest
    from neurosphere_core.search.indexer import CatalogIndexer, FixtureSearchStore

    repo, scope, _ = catalog
    page = await repo.list_entities(scope, EntityFilter(), PageRequest(page_size=50))
    if not page.items:
        pytest.skip("catalog is empty: run `docker compose --profile seed run --rm seed`")
    store = FixtureSearchStore()
    graph = IndexedGraphQuery(repo, store, CatalogIndexer(repo, store), refresh_seconds=30.0)
    # Search for a seeded entity's own display name; the hit set must contain that entity.
    entity = next(e for e in page.items if getattr(e, "display_name", None))
    term = str(entity.display_name)
    result = await graph.search(
        scope,
        GraphSearchRequest(term=term, budget=Budget(timeout_ms=5000, limit=100, max_depth=0)),
    )
    assert result.nodes, f"no hit for {term!r}"
    assert entity.id in {n.id for n in result.nodes}


# -- write registry ----------------------------------------------------------------------------


@pytest.mark.usefixtures("emulator_up")
def test_write_registry_is_empty_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from neurosphere_api.main import create

    for name, value in {
        "NS_ENV": "local",
        "NS_CLOUD": "commercial",
        "NS_COSMOS_ENDPOINT": "http://127.0.0.1:8081",
        # The emulator ignores the key; built at runtime so no key literal is committed.
        "NS_COSMOS_KEY": base64.b64encode(b"emulator-ignores-this").decode(),
        "NS_STORE_DATABASE": "neurosphere",
        "NS_AUTH_TENANT_ID": TENANT,
        "NS_AUTH_AUDIENCES": str(uuid.UUID(int=2)),
        "NS_AUTH_CUSTOMER_ID": "synthco",
        "NS_FOUNDRY_ENABLED": "false",
        "NS_APIM_ENABLED": "false",
    }.items():
        monkeypatch.setenv(name, value)
    app = create()
    registry = app.state.write_targets
    assert registry.names() == ()
    assert not registry.supports("foundry-model-swap", "model_deployment_swap")
