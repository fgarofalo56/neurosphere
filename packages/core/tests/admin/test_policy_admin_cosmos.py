"""``CosmosPolicyAdminRepository`` against the compose Cosmos emulator (``integration``).

Run: ``docker compose up -d --wait`` then ``uv run pytest -q -m integration
packages/core/tests/admin``. Uses its own database (deleted afterwards). The CI-run sibling with a
fake container is ``test_policy_admin.py``. Proves the real transactional batch: principal and
head land together, a stale ETag writes nothing, and the read repository sees the result.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator

import pytest
from azure.cosmos import PartitionKey
from neurosphere_core.auth.scope import CosmosPolicyRepository
from neurosphere_core.auth.scope.policy_admin import (
    FIRST_POLICY_VERSION,
    CosmosPolicyAdminRepository,
    empty_principal_policy,
)
from neurosphere_core.clients import ClientLifetime, create_cosmos_client
from neurosphere_core.cloud import Settings
from neurosphere_core.errors import StaleVersionError

from .admin_helpers import CUSTOMER, OPERATIONS, OTHER_OBJECT_ID, principal_id_for

pytestmark = pytest.mark.integration


@pytest.fixture
async def repos(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[CosmosPolicyAdminRepository, CosmosPolicyRepository]]:
    monkeypatch.setenv("NS_COSMOS_KEY", base64.b64encode(b"emulator-ignores-this").decode())
    settings = Settings(env="local")
    name = f"ns_policy_admin_it_{uuid.uuid4().hex[:8]}"
    async with ClientLifetime() as lifetime:
        client = create_cosmos_client(settings, lifetime=lifetime)
        try:
            db = await client.create_database_if_not_exists(id=name)
            await db.create_container_if_not_exists(
                id="policy", partition_key=PartitionKey(path="/customer_id")
            )
            yield (
                CosmosPolicyAdminRepository.from_client(client, database=name),
                CosmosPolicyRepository(client, database=name),
            )
        finally:
            await client.delete_database(name)


async def test_batch_writes_principal_and_head_together(
    repos: tuple[CosmosPolicyAdminRepository, CosmosPolicyRepository],
) -> None:
    admin, reader = repos
    pid = principal_id_for()
    doc = empty_principal_policy(CUSTOMER, pid)
    etag = await admin.put_principal_policy(doc, if_match=None)
    head = await reader.get_policy_head(CUSTOMER)
    assert head is not None and head.policy_version == FIRST_POLICY_VERSION
    assert await reader.get_principal_policy(CUSTOMER, pid) == doc

    member = doc.model_copy(update={"domain_memberships": (OPERATIONS,)})
    etag2 = await admin.put_principal_policy(member, if_match=etag)
    assert etag2 != etag
    head = await reader.get_policy_head(CUSTOMER)
    assert head is not None and head.policy_version == "admin-2"

    with pytest.raises(StaleVersionError):
        await admin.put_principal_policy(doc, if_match=etag)
    with pytest.raises(StaleVersionError):
        await admin.put_principal_policy(doc, if_match=None)
    head = await reader.get_policy_head(CUSTOMER)
    assert head is not None and head.policy_version == "admin-2"  # batch failed as a whole
    assert await reader.get_principal_policy(CUSTOMER, pid) == member


async def test_list_principals_reads_one_partition(
    repos: tuple[CosmosPolicyAdminRepository, CosmosPolicyRepository],
) -> None:
    admin, _ = repos
    for object_id in (None, OTHER_OBJECT_ID):
        pid = principal_id_for() if object_id is None else principal_id_for(object_id)
        await admin.put_principal_policy(empty_principal_policy(CUSTOMER, pid), if_match=None)
    listed = await admin.list_principals(CUSTOMER)
    assert len(listed) == 2
    assert await admin.list_principals("fabrikam") == []
