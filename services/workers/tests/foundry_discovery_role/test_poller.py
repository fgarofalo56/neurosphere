"""FoundryDiscoveryPoller: create-if-absent drafts, curated protection, capabilities, 429."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, cast

import pytest
from neurosphere_connector_foundry import (
    DiscoveryResult,
    FoundryDiscoveryConnector,
    project_endpoint,
)
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import DependencyTransientError, RateLimitedError
from neurosphere_workers.ingestion.foundry_discovery import (
    FoundryDiscoveryPoller,
    ProjectTarget,
)

CUSTOMER = "synthco"
SCOPE = object()


class FakeScopes:
    async def get(self) -> Any:
        return SCOPE


class FakeRepo:
    """Dict-backed stand-in with the catalog repository's create/get semantics."""

    def __init__(self) -> None:
        self.docs: dict[str, Any] = {}
        self.updates = 0

    async def get_entity(self, _scope: Any, entity_id: str) -> Any:
        return self.docs.get(entity_id)

    async def create_entity(self, _scope: Any, entity: Any) -> Any:
        self.docs[entity.id] = entity
        return entity

    async def update_entity(self, *_a: Any, **_k: Any) -> Any:
        self.updates += 1
        raise AssertionError("discovery must never update")


class FakeReader:
    def __init__(
        self,
        agents: Sequence[Mapping[str, Any]],
        deployments: Sequence[Mapping[str, Any]],
        error: Exception | None = None,
    ) -> None:
        self._agents = agents
        self._deployments = deployments
        self._error = error

    async def list_agents(self, *, page_size: int) -> AsyncIterator[Mapping[str, Any]]:
        del page_size
        if self._error:
            raise self._error
        for a in self._agents:
            yield a

    async def list_deployments(self) -> AsyncIterator[Mapping[str, Any]]:
        if self._error:
            raise self._error
        for d in self._deployments:
            yield d

    async def close(self) -> None:
        return None


AGENTS = [{"id": "asst_1", "name": "Helper", "versions": None}]
DEPLOYMENTS = [
    {
        "name": "gpt-4o-prod",
        "model_name": "gpt-4o",
        "model_version": "2024-08-06",
        "model_publisher": "OpenAI",
        "sku": {"name": "GlobalStandard"},
    }
]


def _poller(
    reader: FakeReader, repo: FakeRepo, cloud: CloudName = CloudName.COMMERCIAL
) -> FoundryDiscoveryPoller:
    connector = FoundryDiscoveryConnector(
        reader=reader,  # type: ignore[arg-type]
        cloud=cloud,
        project_endpoint=project_endpoint(cloud, "res-one", "proj-one"),
    )
    return FoundryDiscoveryPoller(
        targets=[ProjectTarget("res-one/proj-one", connector)],
        repository=cast(Any, repo),
        scope_provider=FakeScopes(),
        customer_id=CUSTOMER,
        domain_id=f"commercial:{CUSTOMER}:neurosphere:domain:d1",
        cloud=cloud.value,
    )


DEPLOY_ID = f"commercial:{CUSTOMER}:foundry:model_deployment:gpt-4o-prod"
AGENT_ID = f"commercial:{CUSTOMER}:foundry:agent:res-one.proj-one.helper"


async def test_tick_creates_drafts_once_and_second_tick_creates_nothing() -> None:
    repo = FakeRepo()
    poller = _poller(FakeReader(AGENTS, DEPLOYMENTS), repo)
    await poller.tick()
    assert set(repo.docs) == {DEPLOY_ID, AGENT_ID}
    for entity in repo.docs.values():
        dumped = entity.model_dump(mode="json")
        assert dumped["lifecycle_status"] == "draft"
        assert dumped["attributes"]["discovered_from"] == "foundry"
    dep = repo.docs[DEPLOY_ID].model_dump(mode="json")
    assert dep["model_name"] == "gpt-4o"
    assert dep["provider"] == "openai"
    assert dep["sku"] == "GlobalStandard"
    assert poller.last_status.created == 2
    await poller.tick()
    assert poller.last_status.created == 0
    assert poller.last_status.existing == 2


async def test_existing_curated_entity_is_untouched() -> None:
    repo = FakeRepo()
    curated = object()
    repo.docs[DEPLOY_ID] = curated
    await _poller(FakeReader(AGENTS, DEPLOYMENTS), repo).tick()
    assert repo.docs[DEPLOY_ID] is curated
    assert repo.updates == 0
    assert AGENT_ID in repo.docs


async def test_government_reports_unavailable_capabilities(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repo = FakeRepo()
    poller = _poller(FakeReader([], []), repo, CloudName.GOVERNMENT)
    with caplog.at_level(logging.INFO):
        await poller.tick()
    unavailable = poller.last_status.unavailable["res-one/proj-one"]
    assert "hosted_agents" in unavailable
    assert "web_search" in unavailable
    assert repo.docs == {}  # no entity for a capability
    logged = [
        r
        for r in caplog.records
        if getattr(r, "event", "") == "worker.foundry_discovery_capabilities"
    ]
    assert logged
    assert "hosted_agents" in logged[0].unavailable  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "error", [RateLimitedError(retry_after_seconds=1), DependencyTransientError()]
)
async def test_upstream_failure_does_not_raise(error: Exception) -> None:
    repo = FakeRepo()
    poller = _poller(FakeReader([], [], error=error), repo)
    await poller.tick()
    assert repo.docs == {}
    assert poller.last_status.projects_failed == 1
    assert poller.last_status.status["res-one/proj-one"].startswith("failed:")


async def test_unknown_source_creates_nothing_for_it() -> None:
    # An agent listing that failed is unknown (None), not empty: deployments still land.
    repo = FakeRepo()

    class HalfReader(FakeReader):
        async def list_agents(self, *, page_size: int) -> AsyncIterator[Mapping[str, Any]]:
            del page_size
            raise RateLimitedError(retry_after_seconds=1)
            yield {}  # pragma: no cover

    await _poller(HalfReader([], DEPLOYMENTS), repo).tick()
    assert set(repo.docs) == {DEPLOY_ID}


def test_result_type_exported() -> None:
    assert DiscoveryResult is not None
