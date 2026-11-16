"""Compliance read API (PRP-56 item 5): authorization, determinism, audit and no-claim."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
import pytest
from neurosphere_api.authz import route_inventory
from neurosphere_api.compliance import PREFIX, build_router, get_clock
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore
from neurosphere_core.auth.scope import Role
from neurosphere_core.compliance import DISCLAIMER, scan_for_claims
from neurosphere_core.evaluation.store import InMemoryEvaluationStore
from neurosphere_core.ledger import InMemoryLedgerStore

ALICE: str = helpers.ALICE  # security auditor on FINANCE
BOB: str = helpers.BOB  # viewer on FINANCE
CAROL: str = helpers.CAROL  # security auditor on OPERATIONS
FINANCE: str = helpers.FINANCE
OPERATIONS: str = helpers.OPERATIONS
OTHER_CUSTOMER_FINANCE: str = helpers.OTHER_CUSTOMER_FINANCE
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
FRAMEWORKS = ("nist_ai_rmf", "sr_11_7", "hipaa_technical_safeguards", "omb_m_25_21")


class Api:
    def __init__(self, *, with_stores: bool = True) -> None:
        self.h = helpers.harness(
            helpers.policy(ALICE, helpers.role(Role.SECURITY_AUDITOR, FINANCE)),
            helpers.policy(BOB, helpers.role(Role.VIEWER, FINANCE)),
            helpers.policy(CAROL, helpers.role(Role.SECURITY_AUDITOR, OPERATIONS)),
            routers={PREFIX: build_router()},
        )
        self.audit = AuditRepository(InMemoryAuditStore())
        if with_stores:
            state = self.h.app.state
            state.audit_repository = self.audit
            state.evaluation_store = InMemoryEvaluationStore()
            state.ledger_store = InMemoryLedgerStore()
        self.h.app.dependency_overrides[get_clock] = lambda: lambda: NOW

    def get(self, who: str | None, path: str, **params: Any) -> Any:
        headers = self.h.auth(who) if who else {}
        return self.h.client.get(f"{PREFIX}{path}", params=params or None, headers=headers)

    def records(self, chain: str) -> list[Any]:
        return list(asyncio.run(self.audit.read_range(chain, start=0, limit=100)))


@pytest.fixture
def api() -> Api:
    return Api()


def test_framework_list_and_detail(api: Api) -> None:
    listing = api.get(ALICE, "/frameworks")
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert {f["framework_id"] for f in body["frameworks"]} == set(FRAMEWORKS)
    detail = api.get(ALICE, "/frameworks/hipaa_technical_safeguards").json()
    assert any(c["control_id"] == "hipaa.164.312.b" for c in detail["controls"])
    assert api.get(ALICE, "/frameworks/finra").status_code == 404


def test_viewer_is_forbidden_everywhere(api: Api) -> None:
    for path, params in (
        ("/frameworks", {}),
        ("/frameworks/nist_ai_rmf", {}),
        (f"/domains/{FINANCE}/bundle", {"framework_id": "nist_ai_rmf"}),
        (f"/domains/{FINANCE}/bundle/export", {"framework_id": "nist_ai_rmf"}),
    ):
        assert api.get(BOB, path, **params).status_code == 403, path


def test_anonymous_is_401_and_cross_domain_is_403(api: Api) -> None:
    path = f"/domains/{OPERATIONS}/bundle"
    assert api.get(None, path, framework_id="nist_ai_rmf").status_code == 401
    assert api.get(ALICE, path, framework_id="nist_ai_rmf").status_code == 403
    other_customer = f"/domains/{OTHER_CUSTOMER_FINANCE}/bundle"
    assert api.get(ALICE, other_customer, framework_id="nist_ai_rmf").status_code == 403


def test_missing_framework_id_is_422(api: Api) -> None:
    assert api.get(ALICE, f"/domains/{FINANCE}/bundle").status_code == 422


def test_unknown_framework_is_404(api: Api) -> None:
    response = api.get(ALICE, f"/domains/{FINANCE}/bundle", framework_id="finra")
    assert response.status_code == 404


@pytest.mark.parametrize("framework_id", FRAMEWORKS)
def test_bundle_shape_and_no_claim(api: Api, framework_id: str) -> None:
    response = api.get(ALICE, f"/domains/{FINANCE}/bundle", framework_id=framework_id)
    assert response.status_code == 200, response.text
    bundle = response.json()
    assert bundle["domain_id"] == FINANCE
    assert bundle["framework_id"] == framework_id
    assert bundle["digest"].startswith("sha256:")
    assert {c["summary"] for c in bundle["controls"]} <= {
        "evidence_present",
        "evidence_partial",
        "no_evidence",
        "customer_responsibility",
    }
    assert scan_for_claims(response.text) == []


def test_customer_id_in_the_query_is_ignored(api: Api) -> None:
    response = api.get(
        ALICE,
        f"/domains/{FINANCE}/bundle",
        framework_id="nist_ai_rmf",
        customer_id="fabrikam",
        domain_id=OPERATIONS,
    )
    assert response.status_code == 200
    assert response.json()["domain_id"] == FINANCE


def test_unconfigured_stores_degrade_to_unavailable() -> None:
    api = Api(with_stores=False)
    response = api.get(ALICE, f"/domains/{FINANCE}/bundle", framework_id="nist_ai_rmf")
    assert response.status_code == 200
    statuses = {o["source_id"]: o["status"] for o in response.json()["observations"]}
    assert set(statuses.values()) == {"unavailable"}


def test_export_json_is_deterministic_with_digest_header(api: Api) -> None:
    path = f"/domains/{FINANCE}/bundle/export"
    first = api.get(ALICE, path, framework_id="nist_ai_rmf", format="json")
    # Same inputs and clock, same bytes. (A second read on the same API would see the first
    # read's own allowed-read audit record, which is a real input change.)
    second = Api().get(ALICE, path, framework_id="nist_ai_rmf", format="json")
    assert first.status_code == 200
    assert first.content == second.content
    assert first.headers["x-bundle-digest"] == json.loads(first.content)["digest"]
    assert "attachment" in first.headers["content-disposition"]
    assert first.headers["cache-control"] == "no-store"


def test_export_markdown_has_the_disclaimer(api: Api) -> None:
    response = api.get(
        ALICE, f"/domains/{FINANCE}/bundle/export", framework_id="sr_11_7", format="md"
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert DISCLAIMER in " ".join(response.text.split())
    assert scan_for_claims(response.text) == []


def test_export_rejects_other_formats(api: Api) -> None:
    response = api.get(
        ALICE, f"/domains/{FINANCE}/bundle/export", framework_id="sr_11_7", format="csv"
    )
    assert response.status_code == 422


def test_allowed_read_is_audited_without_bundle_content(api: Api) -> None:
    response = api.get(ALICE, f"/domains/{FINANCE}/bundle", framework_id="nist_ai_rmf")
    assert response.status_code == 200
    records = api.records("contoso.finance")
    assert len(records) == 1
    assert records[0].operation == "compliance.bundle"
    assert records[0].subject.target.canonical_id == FINANCE
    assert "owners" not in json.dumps(records[0].model_dump(mode="json"))


def test_denied_read_writes_no_allowed_record(api: Api) -> None:
    assert api.get(BOB, f"/domains/{FINANCE}/bundle", framework_id="nist_ai_rmf").status_code == 403
    assert api.records("contoso.finance") == []


def test_route_inventory_declares_evidence_read(api: Api) -> None:
    entries = {e.path: e.permissions for e in route_inventory(api.h.app)}
    for path in (
        f"{PREFIX}/frameworks",
        f"{PREFIX}/frameworks/{{framework_id}}",
        f"{PREFIX}/domains/{{domain}}/bundle",
        f"{PREFIX}/domains/{{domain}}/bundle/export",
    ):
        assert entries[path] == ("evidence.read",), path
