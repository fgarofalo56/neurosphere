"""PRP-61 item 5: the ``configuration_findings`` evidence source and its library mapping."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from neurosphere_core.compliance import build_bundle, load_library
from neurosphere_core.compliance.sources import ConfigurationFindingsSource, SourceRequest
from neurosphere_core.detections import (
    AccountRead,
    AiAccount,
    CatalogRead,
    ContentFilterRule,
    DeploymentConfig,
    DeploymentConfigRead,
    ShadowAiRule,
    finding_to_recommendation,
)
from neurosphere_core.detections.fakes import (
    FakeAiAccountInventory,
    FakeCatalogDeploymentReader,
    FakeDeploymentConfigReader,
)
from neurosphere_core.recommendations.store import InMemoryRecommendationStore

from .helpers import make_scope

DOMAIN = "commercial:contoso:catalog:domain:operations"
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


async def _store_with_findings(*, now: datetime = NOW) -> InMemoryRecommendationStore:
    store = InMemoryRecommendationStore()
    rules = [
        ContentFilterRule(
            cloud="commercial",
            customer_id="contoso",
            reader=FakeDeploymentConfigReader(
                [
                    DeploymentConfigRead(
                        "a",
                        deployments=(
                            DeploymentConfig("a", "d1", None),
                            DeploymentConfig("a", "d2", None),
                        ),
                    )
                ]
            ),
        ),
        ShadowAiRule(
            cloud="commercial",
            customer_id="contoso",
            inventory=FakeAiAccountInventory(
                AccountRead(accounts=(AiAccount("rogue", "/subscriptions/x/rogue", "eastus", "s"),))
            ),
            catalog=FakeCatalogDeploymentReader(CatalogRead()),
        ),
    ]
    for rule in rules:
        for finding in (await rule.evaluate()).findings:
            await store.put(
                finding_to_recommendation(
                    finding,
                    cloud="commercial",
                    customer_id="contoso",
                    domain_id=DOMAIN,
                    now=now,
                    interval_seconds=900.0,
                )
            )
    return store


def _request(cap: int = 2000) -> SourceRequest:
    return SourceRequest(
        scope=make_scope([DOMAIN]),
        domain_id=DOMAIN,
        window_start=NOW - timedelta(days=30),
        window_end=NOW,
        cap=cap,
    )


def _measures(obs: object) -> dict[str, int | None]:
    return {m.name: m.value for m in obs.measures}  # type: ignore[attr-defined]


async def test_counts_open_findings_per_kind() -> None:
    store = await _store_with_findings(now=NOW - timedelta(minutes=5))
    obs = await ConfigurationFindingsSource(store).observe(_request())
    assert obs.status == "observed" and not obs.truncated
    assert _measures(obs) == {
        "records": 3,
        "configuration_finding": 2,
        "unregistered_ai_resource": 1,
    }


async def test_expired_findings_are_not_counted() -> None:
    store = await _store_with_findings(now=NOW - timedelta(hours=3))
    obs = await ConfigurationFindingsSource(store).observe(_request())
    assert _measures(obs)["records"] == 0


async def test_cap_marks_partial_and_truncated() -> None:
    store = await _store_with_findings(now=NOW - timedelta(minutes=5))
    obs = await ConfigurationFindingsSource(store).observe(_request(cap=1))
    assert obs.status == "partial" and obs.truncated


async def test_no_store_is_unavailable_with_unknown_counts() -> None:
    obs = await ConfigurationFindingsSource(None).observe(_request())
    assert obs.status == "unavailable" and obs.reason_code == "store_unconfigured"
    assert set(_measures(obs).values()) == {None}


async def test_bundle_shows_the_source_as_observed_and_mapped() -> None:
    library = load_library()
    mapped = [
        c.control.control_id
        for fw in library.frameworks
        for c in fw.controls
        if any(s.root == "configuration_findings" for s in c.mapping.evidence_sources.root)
    ]
    assert "sr-11-7.vi.inventory" in mapped and "omb-m-25-21.4.b.iii" in mapped
    store = await _store_with_findings(now=NOW - timedelta(minutes=5))
    bundle = await build_bundle(
        library,
        "sr_11_7",
        DOMAIN,
        make_scope([DOMAIN]),
        [ConfigurationFindingsSource(store)],
        now=NOW,
    )
    seen = {o.source_id.root: o for o in bundle.observations}
    assert seen["configuration_findings"].status == "observed"
