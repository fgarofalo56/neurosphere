"""Scan -> plan through the real API app (no live calls, mocked Resource Graph reader).

The caller is authorized for subscriptions A and B; the tenant also holds C. The scan returns only
A and B and says so (visibility limited). That scan result is fed to the plan endpoint, and a shared
service nobody consented to is `needs_consent`, never `reuse`.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

import pytest

# Sibling test package of the API service (same trick as services/api/tests/deployment).
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services" / "api" / "tests"))

from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    BOB,
    FINANCE,
    Harness,
    harness,
    policy,
    role,
)
from neurosphere_api.deploy.plan import PlanRequest
from neurosphere_api.deploy.plan import build_router as build_plan_router
from neurosphere_api.deploy.scan import (
    SCAN_QUERY,
    ScanResponse,
    ScanService,
    configure_scan,
)
from neurosphere_api.deploy.scan import (
    build_router as build_scan_router,
)
from neurosphere_core.auth.scope import Role
from neurosphere_core.capabilities import DeploymentProfile

SUB_A = "aaaaaaaa-0000-4000-8000-000000000001"
SUB_B = "bbbbbbbb-0000-4000-8000-000000000002"
SUB_C = "cccccccc-0000-4000-8000-000000000003"
COMMERCIAL = DeploymentProfile(
    cloud="commercial", regions=("eastus2",), hosting="aks", analytics="synapse"
)


def _row(sub: str, rtype: str, name: str) -> dict[str, Any]:
    return {
        "id": f"/subscriptions/{sub}/resourceGroups/rg/providers/{rtype}/{name}",
        "name": name,
        "type": rtype,
        "location": "eastus2",
        "subscriptionId": sub.upper(),
        "tags": {"owner": "platform"},
        "sku": "Standard",
    }


class MockResourceGraph:
    """Resource Graph stand-in: the caller can read A and B only, whatever is asked."""

    readable = frozenset({SUB_A, SUB_B})
    rows: ClassVar[list[dict[str, Any]]] = [
        _row(SUB_A, "Microsoft.KeyVault/vaults", "kv-shared"),
        _row(SUB_B, "Microsoft.Storage/storageAccounts", "stb"),
        _row(SUB_C, "Microsoft.EventHub/namespaces", "eh-c"),
    ]

    def __init__(self) -> None:
        self.queried: list[list[str]] = []

    async def list_readable_subscriptions(self) -> frozenset[str]:
        return self.readable

    async def query(self, subscriptions: Sequence[str], query: str) -> list[dict[str, Any]]:
        assert query == SCAN_QUERY
        self.queried.append(list(subscriptions))
        return [r for r in self.rows if r["subscriptionId"].lower() in self.readable]


@pytest.fixture
def stack() -> tuple[Harness, MockResourceGraph]:
    h = harness(
        policy(BOB, role(Role.ADMIN, FINANCE)),
        routers={"/v1/deploy/scan": build_scan_router(), "/v1/deploy/plan": build_plan_router()},
    )
    reader = MockResourceGraph()
    configure_scan(h.app, ScanService(reader))
    return h, reader


def test_scan_result_feeds_plan_and_unconsented_shared_service_needs_consent(
    stack: tuple[Harness, MockResourceGraph],
) -> None:
    h, reader = stack
    consent = {
        "consent_id": "scan-consent-1",
        "consented_by": "owner@example.com",
        "consented_subscriptions": [SUB_A, SUB_B, SUB_C],
    }
    scan_resp = h.client.post(
        "/v1/deploy/scan",
        json={"consent": consent, "subscription_ids": [SUB_A, SUB_B, SUB_C]},
        headers=h.auth(BOB),
    )
    assert scan_resp.status_code == 200, scan_resp.text
    scan = scan_resp.json()
    assert scan["visibility_limited"] is True
    assert {s["subscription_id"]: s["status"] for s in scan["subscriptions"]} == {
        SUB_A: "visible",
        SUB_B: "visible",
        SUB_C: "not_visible",
    }
    assert reader.queried == [[SUB_A, SUB_B]]  # C is never queried
    assert all(r["subscription_id"] != SUB_C for s in scan["subscriptions"] for r in s["resources"])

    body = PlanRequest(
        profile=COMMERCIAL, scan=ScanResponse.model_validate(scan), consents=[]
    ).model_dump(mode="json")
    plan_resp = h.client.post("/v1/deploy/plan", json=body, headers=h.auth(BOB))
    assert plan_resp.status_code == 200, plan_resp.text
    items = plan_resp.json()["plan"]["items"]
    kv = next(i for i in items if i["service"] == "key_vault")
    assert kv["status"] == "needs_consent"
    assert kv["shared"] is True
    assert kv["existing_resource_id"].endswith("/kv-shared")
    assert not any(i["status"] == "reuse" for i in items)
    # The resource in the invisible subscription never reaches the plan.
    assert not any(SUB_C in (i.get("existing_resource_id") or "") for i in items)
