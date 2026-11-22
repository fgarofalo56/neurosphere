"""PRP-139 item 3: poller status -> run observation."""

from __future__ import annotations

import pytest
from neurosphere_workers.ingestion.billing_export.runner import TickStatus
from neurosphere_workers.ingestion.foundry_discovery.poller import TickStats
from neurosphere_workers.sources_status import (
    observe_billing,
    observe_foundry,
    observe_gateway,
)


def foundry(*statuses: str, created: int = 0, existing: int = 0) -> TickStats:
    stats = TickStats(created=created, existing=existing)
    for index, text in enumerate(statuses):
        stats.status[f"account{index}/project{index}"] = text
    return stats


def test_foundry_ok_counts_records_and_names_no_project() -> None:
    seen = observe_foundry(foundry("ok", "ok", created=3, existing=2))
    assert seen.state == "ok" and seen.reason is None
    assert seen.counts["records"] == 5 and seen.counts["projects_ok"] == 2
    assert not any("account" in key for key in seen.counts)


@pytest.mark.parametrize("error", ["ForbiddenError", "UnauthorizedError"])
def test_foundry_missing_role_is_failed_source_access_denied(error: str) -> None:
    seen = observe_foundry(foundry(f"failed:{error}"))
    assert (seen.state, seen.reason) == ("failed", "source_access_denied")


def test_foundry_other_failure_is_source_unreachable() -> None:
    seen = observe_foundry(foundry("failed:DependencyTransientError"))
    assert (seen.state, seen.reason) == ("failed", "source_unreachable")


def test_foundry_one_denied_of_two_is_partial_and_keeps_the_reason() -> None:
    seen = observe_foundry(foundry("ok", "failed:ForbiddenError", created=1))
    assert (seen.state, seen.reason) == ("partial", "source_access_denied")
    assert seen.counts["projects_failed"] == 1


def test_foundry_partial_and_idle() -> None:
    assert observe_foundry(foundry("partial")).state == "partial"
    assert observe_foundry(foundry()).state == "idle"


@pytest.mark.parametrize(
    ("code", "state", "reason"),
    [
        ("ok", "ok", None),
        ("unchanged", "ok", "unchanged"),
        ("incomplete", "partial", "incomplete_export"),
        ("read_failed", "failed", "source_access_denied"),
        ("ingest_failed", "failed", "ingest_failed"),
        ("idle", "idle", None),
    ],
)
def test_billing_status_codes(code: str, state: str, reason: str | None) -> None:
    seen = observe_billing(TickStatus(status=code, posted=7))
    assert (seen.state, seen.reason) == (state, reason)
    assert seen.counts["records"] == 7


def test_billing_counts_missing_blobs_by_number_never_by_name() -> None:
    seen = observe_billing(TickStatus(status="incomplete", blobs_missing=("a.csv", "b.csv")))
    assert seen.counts["blobs_missing"] == 2
    assert "a.csv" not in str(seen)


def test_gateway_without_outcomes_is_idle() -> None:
    seen = observe_gateway([])
    assert (seen.state, seen.reason) == ("idle", "no_gateways")


def test_gateway_all_ok_partial_and_failed() -> None:
    assert observe_gateway(["ok", "ok"]).counts == {
        "gateways_polled": 2,
        "gateways_partial": 0,
        "gateways_failed": 0,
    }
    assert observe_gateway(["ok", "rate_limited"]).state == "partial"
    assert observe_gateway(["ok", "stalled"]).reason == "partial_results"


@pytest.mark.parametrize("code", ["poll_failed:forbidden", "poll_failed:unauthorized"])
def test_gateway_denied_is_failed_when_every_gateway_failed(code: str) -> None:
    seen = observe_gateway([code, code])
    assert (seen.state, seen.reason) == ("failed", "source_access_denied")


def test_gateway_denied_among_good_ones_is_partial_with_the_reason() -> None:
    seen = observe_gateway(["ok", "poll_failed:forbidden"])
    assert (seen.state, seen.reason) == ("partial", "source_access_denied")


def test_gateway_ingest_cloud_and_unknown_failures_have_their_own_codes() -> None:
    assert observe_gateway(["ingest_failed"]).reason == "ingest_failed"
    assert observe_gateway(["cloud_mismatch"]).reason == "cloud_not_supported"
    assert observe_gateway(["poll_failed:dependency_transient"]).reason == "source_unreachable"
