"""Point read ``get_result`` on the in-memory and Cosmos evaluation stores (PRP-19 round 2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from neurosphere_contracts.evaluation.v1.evaluation_result import EvaluationResult
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.evaluation.cosmos_store import CosmosEvaluationStore
from neurosphere_core.evaluation.store import InMemoryEvaluationStore
from neurosphere_core.scope import IdentityScope

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts/schemas"
FINANCE = "commercial:contoso:catalog:domain:finance"
OPERATIONS = "commercial:contoso:catalog:domain:operations"


def make_scope(
    *, domains: tuple[str, ...] = (FINANCE,), customer: str = "contoso", cloud: str = "commercial"
) -> IdentityScope:
    doc = json.loads(
        (CONTRACTS / "scope/v1/examples/valid/identity-scope.viewer.json").read_text("utf-8")
    )
    doc["allowed_domains"] = list(domains)
    doc["roles"] = [{"role": "viewer", "domain_ids": list(domains)}]
    doc["customer_id"] = customer
    doc["cloud"] = cloud
    return IdentityScope._from_verified_contract(ContractScope.model_validate(doc))


def make_result(evaluation_id: str = "eval:r-0001", **overrides: Any) -> EvaluationResult:
    doc = json.loads(
        (
            CONTRACTS / "evaluation/v1/examples/valid/evaluation-result.offline-llm-judge.json"
        ).read_text("utf-8")
    )
    doc["evaluation_id"] = evaluation_id
    doc.update(overrides)
    return EvaluationResult.model_validate(doc)


class FakeContainer:
    def __init__(self, error: Exception | None = None) -> None:
        self.docs: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
        self.reads: list[tuple[str, tuple[str, ...]]] = []
        self.queries = 0
        self.error = error

    async def read_item(self, item: str, partition_key: list[str]) -> dict[str, Any]:
        key = (item, tuple(partition_key))
        self.reads.append(key)
        if self.error is not None:
            raise self.error
        if key not in self.docs:
            raise CosmosResourceNotFoundError(status_code=404, message="not found")
        return dict(self.docs[key])

    def query_items(self, *args: Any, **kwargs: Any) -> Any:
        self.queries += 1
        raise AssertionError("get_result must not query")


def cosmos_doc(result: EvaluationResult, doc_id: str) -> dict[str, Any]:
    body = result.model_dump(mode="json")
    body.update(id=doc_id, doc_type="evaluation_result", sort_key=result.evaluation_id.root)
    return body


def cosmos_store(container: FakeContainer) -> CosmosEvaluationStore:
    return CosmosEvaluationStore(container, FakeContainer())  # type: ignore[arg-type]


async def test_memory_in_scope_get_returns_result() -> None:
    result = make_result()
    store = InMemoryEvaluationStore([result])
    assert await store.get_result(make_scope(), FINANCE, "eval:r-0001") == result


async def test_memory_unknown_id_is_none() -> None:
    store = InMemoryEvaluationStore([make_result()])
    assert await store.get_result(make_scope(), FINANCE, "eval:nope") is None


async def test_memory_other_domain_is_none() -> None:
    store = InMemoryEvaluationStore([make_result()])
    scope = make_scope()
    assert await store.get_result(scope, OPERATIONS, "eval:r-0001") is None
    both = make_scope(domains=(FINANCE, OPERATIONS))
    assert await store.get_result(both, OPERATIONS, "eval:r-0001") is None


@pytest.mark.parametrize("scope", [make_scope(customer="other"), make_scope(cloud="government")])
async def test_memory_other_customer_or_cloud_is_none(scope: IdentityScope) -> None:
    store = InMemoryEvaluationStore([make_result()])
    assert await store.get_result(scope, FINANCE, "eval:r-0001") is None


async def test_cosmos_point_read_uses_id_and_partition_key() -> None:
    container = FakeContainer()
    result = make_result()
    container.docs[("eval:r-0001", ("contoso", FINANCE))] = cosmos_doc(result, "eval:r-0001")
    got = await cosmos_store(container).get_result(make_scope(), FINANCE, "eval:r-0001")
    assert got == result
    assert container.reads == [("eval:r-0001", ("contoso", FINANCE))]
    assert container.queries == 0


async def test_cosmos_unsafe_id_is_encoded_like_put_result() -> None:
    container = FakeContainer()
    result = make_result("eval:a/b")
    doc_id = "b64-ZXZhbDphL2I"
    container.docs[(doc_id, ("contoso", FINANCE))] = cosmos_doc(result, doc_id)
    got = await cosmos_store(container).get_result(make_scope(), FINANCE, "eval:a/b")
    assert got == result


async def test_cosmos_404_is_none() -> None:
    container = FakeContainer()
    assert await cosmos_store(container).get_result(make_scope(), FINANCE, "eval:x") is None
    assert len(container.reads) == 1


async def test_cosmos_other_domain_never_reads() -> None:
    container = FakeContainer()
    assert await cosmos_store(container).get_result(make_scope(), OPERATIONS, "eval:r-0001") is None
    assert container.reads == []


@pytest.mark.parametrize("scope", [make_scope(cloud="government")])
async def test_cosmos_other_cloud_is_none(scope: IdentityScope) -> None:
    container = FakeContainer()
    container.docs[("eval:r-0001", ("contoso", FINANCE))] = cosmos_doc(make_result(), "eval:r-0001")
    assert await cosmos_store(container).get_result(scope, FINANCE, "eval:r-0001") is None


async def test_cosmos_non_404_error_propagates() -> None:
    err = CosmosHttpResponseError(status_code=500, message="boom")
    store = cosmos_store(FakeContainer(error=err))
    with pytest.raises(DependencyTransientError):
        await store.get_result(make_scope(), FINANCE, "eval:r-0001")
