"""``CosmosAdminConfigRepository`` against the compose Cosmos emulator (``integration``).

Run: ``docker compose up -d --wait`` then ``uv run pytest -q -m integration
packages/core/tests/admin``. Uses its own database (deleted afterwards); the CI-run sibling with a
fake container is ``test_config_store.py``. Proves real ETags, the composite Cosmos id, the
partition-pinned query (including ``ORDER BY`` on the emulator's default index) and retire.
"""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from neurosphere_core.admin import CosmosAdminConfigRepository, create_admin_config_container
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import StaleVersionError

pytestmark = pytest.mark.integration

EXAMPLES = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "contracts"
    / "schemas"
    / "admin"
    / "v1"
    / "examples"
    / "valid"
)
ACTOR = "commercial:contoso:entra:person:p-" + "0c" * 32


def _load(name: str) -> dict[str, Any]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.fixture
async def store(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[CosmosAdminConfigRepository]:
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())
    settings = Settings(env="local")
    name = f"ns_admin_config_it_{uuid.uuid4().hex[:8]}"
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(settings, lifetime=lifetime)
        try:
            db = await client.create_database_if_not_exists(id=name)
            await create_admin_config_container(db)
            yield CosmosAdminConfigRepository.from_client(client, database=name, cloud="commercial")
        finally:
            await client.delete_database(name)


async def test_versions_etags_and_retire_on_the_emulator(
    store: CosmosAdminConfigRepository,
) -> None:
    domain = _load("domain-definition.finance.json")
    created = await store.create("contoso", "domain", "finance", domain, updated_by=ACTOR)
    assert created.version.root == 1 and created.etag.root
    v2 = await store.replace(
        "contoso", "domain", "finance", domain, if_match=created.etag.root, updated_by=ACTOR
    )
    assert v2.version.root == 2 and v2.etag != created.etag
    with pytest.raises(StaleVersionError):
        await store.replace(
            "contoso", "domain", "finance", domain, if_match=created.etag.root, updated_by=ACTOR
        )
    retired = await store.retire(
        "contoso", "domain", "finance", if_match=v2.etag.root, updated_by=ACTOR
    )
    assert (retired.version.root, retired.status) == (3, "retired")
    assert await store.get("contoso", "domain", "finance") == retired
    assert await store.list_by_kind("contoso", "domain") == []
    assert [
        d.id.root for d in await store.list_by_kind("contoso", "domain", include_retired=True)
    ] == ["finance"]


async def test_same_id_in_two_kinds_does_not_collide(store: CosmosAdminConfigRepository) -> None:
    budget = _load("budget.annual-unfiltered.json")
    domain = _load("domain-definition.finance.json")
    await store.create("contoso", "budget", "finance", budget, updated_by=ACTOR)
    await store.create("contoso", "domain", "finance", domain, updated_by=ACTOR)
    assert [d.kind.root for d in await store.list_by_kind("contoso", "budget")] == ["budget"]
    assert [d.kind.root for d in await store.list_by_kind("contoso", "domain")] == ["domain"]
    with pytest.raises(StaleVersionError):
        await store.create("contoso", "domain", "finance", domain, updated_by=ACTOR)
