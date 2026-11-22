"""PRP-137 item 6: the poller aliases a discovered agent's external id to the discovered agent."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from neurosphere_connector_foundry import FoundryDiscoveryConnector, project_endpoint
from neurosphere_core.agent_identity import agent_alias_key
from neurosphere_core.cloud.profile import CloudName
from neurosphere_workers.ingestion.foundry_discovery import FoundryDiscoveryPoller, ProjectTarget

from .test_poller import AGENT_ID, AGENTS, CUSTOMER, DEPLOYMENTS, FakeReader, FakeRepo

WORKER_SCOPE = SimpleNamespace(cloud="commercial", customer_id=CUSTOMER)


class _Scopes:
    async def get(self) -> Any:
        return WORKER_SCOPE


class AliasRepo(FakeRepo):
    """Adds the alias half of the catalog repository: one active alias per key."""

    def __init__(self) -> None:
        super().__init__()
        self.active: dict[str, Any] = {}
        self.puts = 0
        self.refuse: Exception | None = None

    async def resolve_alias(self, _scope: Any, key: Any) -> str | None:
        found = self.active.get(key.alias_value)
        return None if found is None else str(found.canonical_id)

    async def put_alias(self, _scope: Any, alias: Any) -> Any:
        self.puts += 1
        if self.refuse is not None:
            raise self.refuse
        if alias.status == "active":
            self.active[alias.alias_value] = alias
        return alias


def _poller(repo: AliasRepo) -> FoundryDiscoveryPoller:
    cloud = CloudName.COMMERCIAL
    connector = FoundryDiscoveryConnector(
        reader=cast(Any, FakeReader(AGENTS, DEPLOYMENTS)),
        cloud=cloud,
        project_endpoint=project_endpoint(cloud, "res-one", "proj-one"),
    )
    return FoundryDiscoveryPoller(
        targets=[ProjectTarget("res-one/proj-one", connector)],
        repository=cast(Any, repo),
        scope_provider=_Scopes(),
        customer_id=CUSTOMER,
        domain_id=f"commercial:{CUSTOMER}:neurosphere:domain:d1",
        cloud="commercial",
    )


async def test_alias_is_written_for_a_discovered_agent_with_an_external_id() -> None:
    repo = AliasRepo()
    poller = _poller(repo)
    await poller.tick()
    alias = repo.active["asst_1"]
    assert alias.canonical_id == AGENT_ID
    assert alias.provenance.method == "import"
    assert poller.last_status.aliases_declared == 1

    await poller.tick()  # idempotent: nothing is written twice
    assert repo.puts == 1
    assert poller.last_status.aliases_unchanged == 1
    assert poller.last_status.aliases_declared == 0


async def test_a_key_aliased_to_another_agent_is_counted_not_raised_or_repointed() -> None:
    repo = AliasRepo()
    other = f"commercial:{CUSTOMER}:foundry:agent:someone-else"
    repo.active["asst_1"] = SimpleNamespace(canonical_id=other, status="active")
    poller = _poller(repo)
    await poller.tick()
    assert poller.last_status.alias_collisions == 1
    assert poller.last_status.aliases_declared == 0
    assert repo.puts == 0
    assert repo.active["asst_1"].canonical_id == other
    assert AGENT_ID in repo.docs  # the draft entity was still created


async def test_a_refused_alias_write_is_counted_by_reason_and_never_raised() -> None:
    repo = AliasRepo()
    repo.refuse = PermissionError("denied")
    poller = _poller(repo)
    await poller.tick()
    assert poller.last_status.alias_refused == {"PermissionError": 1}
    assert AGENT_ID in repo.docs
    assert agent_alias_key("foundry", "asst_1").alias_value == "asst_1"
