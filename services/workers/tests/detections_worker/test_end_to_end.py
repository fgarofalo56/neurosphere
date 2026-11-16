"""PRP-61 item 6: tick (fake readers) -> in-memory store -> ``GET /api/v1/recommendations``.

In process: no compose, no network, no cloud. Proves the review path scope filter for the two new
kinds. It does NOT prove a live ARM, Resource Graph or APIM read (OPEN, PRP-64) or a Cosmos store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
import pytest
from neurosphere_api.recommendations import PREFIX
from neurosphere_core.auth.scope import Role
from neurosphere_core.detections import (
    AccountRead,
    AiAccount,
    CatalogRead,
    ContentFilterRule,
    DeploymentConfig,
    DeploymentConfigRead,
    GatewayFragmentRule,
    GatewayFragments,
    GatewayRead,
    ShadowAiRule,
)
from neurosphere_core.detections.fakes import (
    FakeAiAccountInventory,
    FakeCatalogDeploymentReader,
    FakeDeploymentConfigReader,
    FakeGatewayInventoryReader,
)
from neurosphere_core.recommendations import InMemoryRecommendationStore
from neurosphere_workers.detections.role import DetectionRunner

from .support import DOMAIN, OTHER_DOMAIN

ALICE, BOB = helpers.ALICE, helpers.BOB


@pytest.fixture(name="h")
async def harness_() -> Any:
    store = InMemoryRecommendationStore()
    rules = [
        ContentFilterRule(
            cloud="commercial",
            customer_id="contoso",
            reader=FakeDeploymentConfigReader(
                [
                    DeploymentConfigRead(
                        "acct-1", deployments=(DeploymentConfig("acct-1", "gpt-4o", None),)
                    )
                ]
            ),
        ),
        GatewayFragmentRule(
            cloud="commercial",
            customer_id="contoso",
            reader=FakeGatewayInventoryReader(
                GatewayRead(gateways=(GatewayFragments("gw-aaaa", frozenset()),))
            ),
            required_fragments=("pii-redact",),
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
    summary = await DetectionRunner(
        rules=rules,
        store=store,
        cloud="commercial",
        customer_id="contoso",
        domain_id=DOMAIN,
        interval_seconds=3600.0,
        clock=lambda: datetime.now(UTC),
    ).tick()
    assert summary.stored == 3
    h = helpers.harness(
        helpers.policy(ALICE, helpers.role(Role.VIEWER, DOMAIN), memberships=(DOMAIN,)),
        helpers.policy(BOB, helpers.role(Role.VIEWER, OTHER_DOMAIN), memberships=(OTHER_DOMAIN,)),
        routers={},
    )
    h.app.state.recommendation_store = store
    return h


def _get(h: Any, who: str, domain: str, **params: str) -> Any:
    return h.client.get(f"{PREFIX}/domains/{domain}", params=params, headers=h.auth(who))


def test_steward_of_the_domain_lists_unregistered_ai_resources(h: Any) -> None:
    response = _get(h, ALICE, DOMAIN, kind="unregistered_ai_resource")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["kind"] == "unregistered_ai_resource"
    assert item["advisory"] is True and item["method"] == "rule"
    assert item["owner"]["resolution"] == "unresolved"
    assert "score" not in item or item["score"] is None
    assert item["subject_ids"][0].startswith(
        "commercial:contoso:azure_resource_graph:ai_account:rogue-"
    )


def test_configuration_findings_are_listed_for_the_same_domain(h: Any) -> None:
    items = _get(h, ALICE, DOMAIN, kind="configuration_finding").json()["items"]
    assert len(items) == 2
    assert {i["generator"]["generator_id"] for i in items} == {
        "detect.content_filter_policy.unset_only",
        "detect.gateway_policy_fragment",
    }


def test_another_domain_never_sees_the_findings(h: Any) -> None:
    assert _get(h, BOB, DOMAIN, kind="unregistered_ai_resource").status_code == 403
    other = _get(h, BOB, OTHER_DOMAIN, kind="unregistered_ai_resource")
    assert other.status_code == 200 and other.json()["items"] == []


def test_runbook_makes_no_compliance_claim() -> None:
    from pathlib import Path

    from neurosphere_core.compliance import scan_for_claims

    text = (Path(__file__).resolve().parents[4] / "docs/runbooks/detections.md").read_text(
        encoding="utf-8"
    )
    assert scan_for_claims(text) == []
    assert "not FedRAMP authorized; the authorizing official decides" in text
