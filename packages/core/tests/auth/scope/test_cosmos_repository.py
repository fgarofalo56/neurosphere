"""Cosmos policy repository over a fake async client.

Not-found is ``None``; every other failure fails closed (``dependency_transient``).
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from azure.core.exceptions import ServiceRequestError
from azure.cosmos.aio import CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from neurosphere_core.auth.scope import (
    POLICY_HEAD_ID,
    CosmosPolicyRepository,
    Role,
    principal_document_id,
)
from neurosphere_core.errors import DependencyTransientError

from .scope_helpers import CUSTOMER, FINANCE, principal_id_for, principal_policy, role

_SYSTEM = {"_rid": "abc", "_etag": '"0"', "_ts": 1, "_self": "dbs/x", "_attachments": "a/"}


class _FakeContainer:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.error: BaseException | None = None
        self.reads: list[tuple[str, str]] = []

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        self.reads.append((item, partition_key))
        if self.error is not None:
            raise self.error
        try:
            return dict(self.items[(item, partition_key)])
        except KeyError:
            raise CosmosResourceNotFoundError(status_code=404, message="missing") from None


class _FakeDatabase:
    def __init__(self, container: _FakeContainer) -> None:
        self._container = container
        self.requested: list[str] = []

    def get_container_client(self, name: str) -> _FakeContainer:
        self.requested.append(name)
        return self._container


class _FakeClient:
    def __init__(self, container: _FakeContainer) -> None:
        self.database = _FakeDatabase(container)

    def get_database_client(self, name: str) -> _FakeDatabase:
        assert name == "neurosphere"
        return self.database


def _repo() -> tuple[CosmosPolicyRepository, _FakeContainer]:
    container = _FakeContainer()
    repo = CosmosPolicyRepository(
        cast(CosmosClient, _FakeClient(container)), database="neurosphere"
    )
    return repo, container


def _store_principal(container: _FakeContainer, **overrides: Any) -> str:
    policy = principal_policy(roles=(role(Role.VIEWER, FINANCE),))
    doc = {**policy.model_dump(mode="json"), **_SYSTEM, **overrides}
    container.items[(policy.id, CUSTOMER)] = doc
    return policy.principal_id


async def test_reads_documents_and_strips_system_properties() -> None:
    repo, container = _repo()
    container.items[(POLICY_HEAD_ID, CUSTOMER)] = {
        "id": POLICY_HEAD_ID,
        "doc_type": "policy_head",
        "customer_id": CUSTOMER,
        "policy_version": "v7",
        **_SYSTEM,
    }
    pid = _store_principal(container)
    head = await repo.get_policy_head(CUSTOMER)
    assert head is not None and head.policy_version == "v7"
    policy = await repo.get_principal_policy(CUSTOMER, pid)
    assert policy is not None and policy.role_assignments[0].role is Role.VIEWER
    assert container.reads[-1] == (principal_document_id(pid), CUSTOMER)


async def test_missing_documents_are_none() -> None:
    repo, _ = _repo()
    assert await repo.get_policy_head(CUSTOMER) is None
    assert await repo.get_principal_policy(CUSTOMER, principal_id_for()) is None


@pytest.mark.parametrize(
    "error",
    [
        CosmosHttpResponseError(status_code=503, message="unavailable"),
        CosmosHttpResponseError(status_code=403, message="forbidden"),
        CosmosHttpResponseError(status_code=429, message="throttled"),
        ServiceRequestError("dns"),
        TimeoutError(),
    ],
)
async def test_store_failures_are_dependency_transient(error: BaseException) -> None:
    repo, container = _repo()
    container.error = error
    with pytest.raises(DependencyTransientError) as info:
        await repo.get_principal_policy(CUSTOMER, principal_id_for())
    assert info.value.status == 503
    assert "forbidden" not in str(info.value) and "unavailable" in str(info.value)


async def test_malformed_document_is_upstream_invalid() -> None:
    repo, container = _repo()
    pid = _store_principal(container, role_assignments=[{"role": "superuser"}])
    with pytest.raises(DependencyTransientError) as info:
        await repo.get_principal_policy(CUSTOMER, pid)
    assert info.value.status == 502


async def test_unknown_member_is_rejected_not_ignored() -> None:
    repo, container = _repo()
    pid = _store_principal(container, bypass=True)
    with pytest.raises(DependencyTransientError):
        await repo.get_principal_policy(CUSTOMER, pid)


async def test_document_for_other_customer_is_upstream_invalid() -> None:
    repo, container = _repo()
    pid = _store_principal(container, customer_id="fabrikam")
    with pytest.raises(DependencyTransientError) as info:
        await repo.get_principal_policy(CUSTOMER, pid)
    assert info.value.status == 502


def test_uses_policy_container_by_default() -> None:
    container = _FakeContainer()
    client = _FakeClient(container)
    CosmosPolicyRepository(cast(CosmosClient, client), database="neurosphere")
    assert client.database.requested == ["policy"]
