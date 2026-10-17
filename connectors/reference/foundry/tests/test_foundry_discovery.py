"""Foundry discovery: per-cloud capability reporting, bounded reads, failure semantics."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any

import pytest
from neurosphere_connector.testing import ConnectorContractSuite
from neurosphere_connector_foundry import (
    FOUNDRY_ENDPOINTS,
    CapabilityStatus,
    FoundryDiscoveryConnector,
    capability_reports,
    project_endpoint,
)
from neurosphere_core.cloud.profile import CloudName
from neurosphere_core.errors import (
    ForbiddenError,
    RateLimitedError,
)

GOV_UNAVAILABLE = {
    "hosted_agents",
    "web_search",
    "bing_grounding",
    "fabric_tool",
    "agent_to_agent",
}


class FakeReader:
    def __init__(
        self,
        agents: list[Mapping[str, Any]] | None = None,
        deployments: list[Mapping[str, Any]] | None = None,
        fail_agents: Exception | None = None,
        fail_deployments: Exception | None = None,
    ) -> None:
        self.agents = agents or []
        self.deployments = deployments or []
        self.fail_agents = fail_agents
        self.fail_deployments = fail_deployments
        self.agents_pulled = 0

    async def list_agents(self, *, page_size: int) -> AsyncIterator[Mapping[str, Any]]:
        if self.fail_agents:
            raise self.fail_agents
        for a in self.agents:
            self.agents_pulled += 1
            yield a

    async def list_deployments(self) -> AsyncIterator[Mapping[str, Any]]:
        if self.fail_deployments:
            raise self.fail_deployments
        for d in self.deployments:
            yield d

    async def close(self) -> None:
        return None


def _connector(reader: FakeReader, cloud: CloudName = CloudName.GOVERNMENT, **kw: Any):
    return FoundryDiscoveryConnector(
        reader=reader,
        cloud=cloud,
        project_endpoint=project_endpoint(cloud, "res-one", "proj-one"),
        **kw,
    )


class TestFoundryContract(ConnectorContractSuite):
    @pytest.fixture
    def connector(self) -> FoundryDiscoveryConnector:
        return _connector(FakeReader())


def test_manifest_is_advisory_read_only() -> None:
    m = _connector(FakeReader()).manifest
    assert m.advisory is True
    assert m.write_support.supported is False
    assert "catalog_discovery" in m.capabilities
    assert m.documentation_url is not None


def test_endpoint_table_per_cloud() -> None:
    assert (
        project_endpoint(CloudName.GOVERNMENT, "res-one", "proj-one")
        == "https://res-one.services.ai.azure.us/api/projects/proj-one"
    )
    assert (
        project_endpoint(CloudName.COMMERCIAL, "res-one", "proj-one")
        == "https://res-one.services.ai.azure.com/api/projects/proj-one"
    )
    assert FOUNDRY_ENDPOINTS[CloudName.GOVERNMENT].token_scope == "https://ai.azure.us/.default"  # noqa: S105
    assert set(FOUNDRY_ENDPOINTS) == set(CloudName)


@pytest.mark.parametrize("bad", ["", "a b", "x/../y", "a@b", "-lead", "evil.com/#"])
def test_endpoint_rejects_unsafe_names(bad: str) -> None:
    with pytest.raises(ValueError, match="invalid Foundry"):
        project_endpoint(CloudName.GOVERNMENT, bad, "proj-one")


def test_government_reports_unavailable_not_empty() -> None:
    reports = {r.capability: r for r in capability_reports(CloudName.GOVERNMENT)}
    assert GOV_UNAVAILABLE <= set(reports)
    for name in GOV_UNAVAILABLE:
        assert reports[name].status is CapabilityStatus.UNAVAILABLE
        assert reports[name].reason
        assert str(reports[name].source).startswith("https://learn.microsoft")
    assert reports["workflows"].status is CapabilityStatus.PREVIEW
    assert reports["prompt_agents"].status is CapabilityStatus.AVAILABLE


def test_commercial_capabilities_are_unknown_not_claimed() -> None:
    reports = capability_reports(CloudName.COMMERCIAL)
    assert reports
    assert {r.status for r in reports} == {CapabilityStatus.UNKNOWN}


async def test_discovery_result_keeps_unavailable_rows_with_zero_agents() -> None:
    c = _connector(FakeReader(agents=[], deployments=[]))
    result = await c.discover()
    assert result.agents == []  # genuinely none found
    assert result.advisory is True
    by_name = {r.capability: r.status for r in result.capabilities}
    assert by_name["hosted_agents"] is CapabilityStatus.UNAVAILABLE


async def test_discovery_maps_fields_and_missing_stay_none() -> None:
    reader = FakeReader(
        agents=[{"id": "a1", "name": "alpha", "versions": {"latest": {"version": "2"}}}, {}],
        deployments=[{"name": "gpt", "model_name": "gpt-4.1", "sku": {"name": "Standard"}}],
    )
    result = await _connector(reader).discover()
    assert result.agents is not None
    assert result.agents[0].name == "alpha"
    assert result.agents[1].name is None and result.agents[1].versions is None
    assert result.deployments is not None
    d = result.deployments[0]
    assert d.model_name == "gpt-4.1"
    assert d.model_version is None  # unknown, not ""
    assert d.capabilities is None


async def test_bounded_reads_flag_truncation_and_stop() -> None:
    reader = FakeReader(agents=[{"name": f"a{i}"} for i in range(1000)])
    c = _connector(reader, max_items=3)
    result = await c.discover()
    assert result.agents is not None and len(result.agents) == 3
    assert result.agents_truncated is True
    assert reader.agents_pulled <= 4  # never loops past budget + 1 probe
    cov = await c.coverage()
    assert cov.partial is True


async def test_exact_budget_is_not_truncated() -> None:
    reader = FakeReader(agents=[{"name": "a"}, {"name": "b"}])
    result = await _connector(reader, max_items=2).discover()
    assert result.agents_truncated is False


async def test_one_failed_source_is_unknown_not_empty() -> None:
    reader = FakeReader(
        agents=[{"name": "a"}], fail_deployments=RateLimitedError(retry_after_seconds=5)
    )
    c = _connector(reader)
    result = await c.discover()
    assert result.deployments is None
    assert result.failed_sources == {"deployments": "rate_limited"}
    cov = await c.coverage()
    assert (cov.expected_sources, cov.answered_sources, cov.partial) == (2, 1, True)


async def test_all_sources_failing_raises_and_marks_health() -> None:
    reader = FakeReader(fail_agents=ForbiddenError(), fail_deployments=ForbiddenError())
    c = _connector(reader)
    with pytest.raises(ForbiddenError):
        await c.discover()
    assert (await c.health()).state.value != "healthy"


async def test_freshness_lag_unknown_not_zero() -> None:
    c = _connector(FakeReader())
    await c.discover()
    f = await c.freshness()
    assert f.lag_ms is None and f.observed_at is not None
