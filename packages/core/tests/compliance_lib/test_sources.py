"""Evidence sources (PRP-56 item 3): counts only, unavailable and not_collected, truncation."""

from __future__ import annotations

from neurosphere_core.compliance.sources import (
    AuditChainSource,
    CatalogOwnershipSource,
    CostAttributionSource,
    EvaluationResultsSource,
    EvidenceSource,
    HitlDecisionsSource,
)

from .helpers import (
    DOMAIN,
    OTHER_DOMAIN,
    FakeCatalog,
    FakeLedger,
    audit_repo_with,
    evaluation_store_with,
    hitl_store_with,
    ledger_entry,
    make_request,
    owner,
    review_item,
)


def measures(obs: object) -> dict[str, int | None]:
    return {m.name: m.value for m in obs.measures}  # type: ignore[attr-defined]


async def test_catalog_counts_owners_and_never_returns_bodies() -> None:
    catalog = FakeCatalog(
        [
            owner(1, by="2026-11-01T00:00:00Z", at="2026-10-20T00:00:00Z"),
            owner(2, by="2027-02-01T00:00:00Z", at=None),
            owner(3, by=None, at=None),
        ]
    )
    obs = await CatalogOwnershipSource(catalog).observe(make_request())  # type: ignore[arg-type]
    assert obs.status == "observed" and not obs.truncated
    assert measures(obs) == {
        "records": 3,
        "owners_with_recertify_by": 2,
        "owners_overdue": 1,
        "owners_recertified_in_window": 1,
    }
    assert obs.latest_at is not None and obs.latest_at.root == "2026-10-20T00:00:00Z"
    dumped = obs.model_dump_json()
    assert "Secret Team" not in dumped and "team-1" not in dumped


async def test_catalog_cap_truncates_and_reports_partial() -> None:
    catalog = FakeCatalog([owner(n, by=None, at=None) for n in range(10)], page_size=3)
    obs = await CatalogOwnershipSource(catalog).observe(make_request(cap=6))  # type: ignore[arg-type]
    assert obs.truncated and obs.status == "partial" and obs.reason_code == "capped"
    assert measures(obs)["records"] == 6


async def test_missing_and_failing_store_is_unavailable_with_unknown_counts() -> None:
    missing = await CatalogOwnershipSource(None).observe(make_request())
    assert missing.status == "unavailable" and missing.reason_code == "store_unconfigured"
    assert set(measures(missing).values()) == {None}
    down = FakeCatalog([])
    down.fail = True
    broken = await CatalogOwnershipSource(down).observe(make_request())  # type: ignore[arg-type]
    assert broken.status == "unavailable" and broken.reason_code == "store_error"
    assert measures(broken)["records"] is None


async def test_audit_chain_intact_and_empty() -> None:
    repo = await audit_repo_with(4)
    obs = await AuditChainSource(repo).observe(make_request())
    assert obs.status == "observed"
    assert measures(obs) == {"records": 4, "chain_intact": 1}
    assert obs.latest_at is not None
    empty = await AuditChainSource(repo).observe(make_request(domain=OTHER_DOMAIN))
    assert measures(empty) == {"records": 0, "chain_intact": None}


async def test_audit_chain_verify_cap_is_partial_not_zero() -> None:
    repo = await audit_repo_with(5)
    obs = await AuditChainSource(repo).observe(make_request(cap=3))
    assert obs.status == "partial" and obs.truncated
    assert measures(obs) == {"records": 5, "chain_intact": None}


async def test_audit_unconfigured() -> None:
    obs = await AuditChainSource(None).observe(make_request())
    assert obs.status == "unavailable"


async def test_hitl_counts_decisions_in_window() -> None:
    store = await hitl_store_with(
        [
            review_item(1, decided=True, state="approved"),
            review_item(2, decided=True, state="rejected"),
            review_item(3, decided=False),
        ]
    )
    obs = await HitlDecisionsSource(store).observe(make_request())
    assert obs.status == "observed"
    assert measures(obs) == {
        "records": 2,
        "items_seen": 3,
        "decided_approved": 1,
        "decided_rejected": 1,
    }
    dumped = obs.model_dump_json()
    assert "catalog:agent" not in dumped


async def test_hitl_outage_is_unavailable() -> None:
    store = await hitl_store_with([review_item(1, decided=True)])
    store.outage = True
    obs = await HitlDecisionsSource(store).observe(make_request())
    assert obs.status == "unavailable"


async def test_evaluation_counts_and_truncation() -> None:
    store = evaluation_store_with(4)
    obs = await EvaluationResultsSource(store).observe(make_request())
    assert measures(obs)["records"] == 4 and measures(obs)["results_completed"] == 4
    capped = await EvaluationResultsSource(store).observe(make_request(cap=2))
    assert capped.truncated and capped.status == "partial"
    assert measures(capped)["records"] == 2


async def test_evaluation_outside_window_is_a_real_zero() -> None:
    store = evaluation_store_with(2, completed_at="2026-01-01T00:00:00Z")
    obs = await EvaluationResultsSource(store).observe(make_request())
    assert obs.status == "observed" and measures(obs)["records"] == 0


async def test_cost_counts_tagged_and_untagged_for_the_domain_only() -> None:
    ledger = FakeLedger(
        [
            ledger_entry(DOMAIN, "cc-1"),
            ledger_entry(DOMAIN, None),
            ledger_entry(OTHER_DOMAIN, "cc-2"),
        ]
    )
    obs = await CostAttributionSource(ledger).observe(make_request())  # type: ignore[arg-type]
    assert measures(obs) == {
        "records": 2,
        "entries_with_cost_center": 1,
        "entries_without_cost_center": 1,
    }


async def test_cost_without_cost_center_attribute_is_not_collected_never_zero() -> None:
    ledger = FakeLedger([ledger_entry(DOMAIN, None, has_attr=False)])
    obs = await CostAttributionSource(ledger).observe(make_request())  # type: ignore[arg-type]
    assert obs.status == "not_collected" and obs.reason_code == "cost_center_absent"
    assert set(measures(obs).values()) == {None}


async def test_cost_cap_and_failure() -> None:
    ledger = FakeLedger([ledger_entry(DOMAIN, "cc") for _ in range(5)])
    obs = await CostAttributionSource(ledger).observe(make_request(cap=2))  # type: ignore[arg-type]
    assert obs.truncated and measures(obs)["records"] == 2
    ledger.fail = True
    down = await CostAttributionSource(ledger).observe(make_request())  # type: ignore[arg-type]
    assert down.status == "unavailable"


def test_sources_satisfy_the_protocol() -> None:
    for source in (
        CatalogOwnershipSource(None),
        AuditChainSource(None),
        HitlDecisionsSource(None),
        EvaluationResultsSource(None),
        CostAttributionSource(None),
    ):
        assert isinstance(source, EvidenceSource)
