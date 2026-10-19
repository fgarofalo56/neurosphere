"""Reference counts each request once; variance, unknown and per-currency rules (PRP-14 item 4)."""

from __future__ import annotations

from typing import Any

from .support import entry, fetch, make_api, make_store, vendor_allocation


def _line(body: dict[str, Any], source: str, currency: str | None = "USD") -> dict[str, Any]:
    (found,) = [s for s in body["sources"] if s["source"] == source and s["currency"] == currency]
    return found


def test_a_request_seen_by_all_three_sources_is_in_the_reference_once() -> None:
    store = make_store(entry("r1", "10", {"gateway": "10", "app": "10", "billing": "10"}))
    h, client = make_api(store)
    body = fetch(h, client)
    assert body["reference"]["amount"] == {
        "value": 10.0,
        "status": "known",
        "complete": True,
        "price_version": None,
    }
    assert body["reference"]["currency"] == "USD"
    for source in ("gateway", "app", "billing"):
        line = _line(body, source)
        assert line["amount"]["value"] == 10.0
        assert line["coverage"]["value"] == 1.0
        assert line["variance"]["value"] == 0.0
        assert line["variance"]["status"] == "known"
        assert line["granularity"] == "request"
    assert body["disclaimer"] == "not_all_spend_observable"
    assert body["complete"] is True


def test_variance_is_source_minus_reference() -> None:
    store = make_store(
        entry("r1", "10", {"gateway": "9", "app": "10", "billing": "11.5"}),
        entry("r2", "5", {"gateway": "5", "app": "5", "billing": "5"}),
    )
    h, client = make_api(store)
    body = fetch(h, client)
    assert body["reference"]["amount"]["value"] == 15.0
    assert _line(body, "gateway")["variance"]["value"] == -1.0
    assert _line(body, "app")["variance"]["value"] == 0.0
    assert _line(body, "billing")["variance"]["value"] == 1.5


def test_an_unknown_source_amount_gives_unknown_variance_not_zero() -> None:
    store = make_store(entry("r1", "10", {"gateway": None, "app": "10", "billing": "10"}))
    h, client = make_api(store)
    body = fetch(h, client)
    gateway = _line(body, "gateway")
    assert gateway["amount"]["status"] == "unknown"
    assert gateway["amount"]["value"] is None
    assert gateway["variance"]["status"] == "unknown"
    assert gateway["variance"]["value"] is None
    assert gateway["coverage"]["value"] == 0.0  # reported on the entry, none known: really 0
    assert body["complete"] is False


def test_an_unknown_reference_gives_unknown_variance() -> None:
    store = make_store(entry("r1", None, {"gateway": "10", "app": "10", "billing": "10"}))
    h, client = make_api(store)
    body = fetch(h, client)
    assert body["reference"]["amount"]["status"] == "unknown"
    assert body["reference"]["amount"]["value"] is None
    assert _line(body, "app")["amount"]["value"] == 10.0
    assert _line(body, "app")["variance"]["status"] == "unknown"
    assert body["unknown_remainder"]["value"] == 1.0
    assert body["unknown_remainder"]["unit"] == "entries"
    assert body["complete"] is False


def test_a_source_with_no_data_has_unknown_coverage_not_zero() -> None:
    store = make_store(entry("r1", "10", {"gateway": "10", "billing": "10"}))
    h, client = make_api(store)
    body = fetch(h, client)
    app = _line(body, "app")
    assert app["coverage"]["status"] == "unknown"
    assert app["coverage"]["value"] is None
    assert app["amount"]["status"] == "unknown"
    assert app["variance"]["status"] == "unknown"
    assert app["granularity"] == "unknown"
    assert body["complete"] is False


def test_no_data_at_all_is_unknown_and_incomplete() -> None:
    h, client = make_api(make_store())
    body = fetch(h, client)
    assert body["sources"] == []
    assert body["reference"]["amount"]["status"] == "unknown"
    assert body["unknown_remainder"]["status"] == "unknown"
    assert body["freshness"]["watermark"] is None
    assert body["complete"] is False
    assert body["disclaimer"] == "not_all_spend_observable"


def test_currencies_are_reported_separately_and_never_added() -> None:
    store = make_store(
        entry("u1", "10", {"gateway": "10", "app": "10", "billing": "10"}, currency="USD"),
        entry("e1", "7", {"gateway": "7", "app": "7", "billing": "7"}, currency="EUR"),
    )
    h, client = make_api(store)
    body = fetch(h, client)
    refs = {r["currency"]: r["amount"]["value"] for r in body["references"]}
    assert refs == {"USD": 10.0, "EUR": 7.0}
    assert len(body["sources"]) == 6
    assert _line(body, "gateway", "USD")["amount"]["value"] == 10.0
    assert _line(body, "gateway", "EUR")["amount"]["value"] == 7.0
    assert all(v != 17.0 for v in (r["amount"]["value"] for r in body["references"]))
    # The single contract-level reference cannot name one currency, so it stays unknown.
    assert body["reference"]["amount"]["status"] == "unknown"
    assert body["reference"]["currency"] is None
    assert body["unknown_remainder"]["status"] == "unknown"


def test_vendor_allocation_feeds_billing_only_and_is_not_in_the_reference() -> None:
    store = make_store(
        entry("r1", "10", {"gateway": "10", "app": "10"}),
        vendor_allocation("v1", "4"),
    )
    h, client = make_api(store)
    body = fetch(h, client)
    assert body["reference"]["amount"]["value"] == 10.0  # allocation not double counted
    billing = _line(body, "billing")
    assert billing["granularity"] == "vendor"
    assert billing["amount"]["value"] == 4.0
    assert billing["coverage"]["status"] == "unknown"  # no per-request billing observation
    assert billing["variance"]["value"] == -6.0
    assert _line(body, "gateway")["amount"]["value"] == 10.0
    assert body["disclaimer"] == "not_all_spend_observable"


def test_response_carries_freshness_and_server_timing() -> None:
    store = make_store(entry("r1", "10", {"gateway": "10", "app": "10", "billing": "10"}))
    h, client = make_api(store)
    response = client.get(
        "/api/v1/reconciliation/domains/commercial:contoso:catalog:domain:finance",
        headers=h.auth("6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"),
    )
    assert response.status_code == 200
    assert response.headers["server-timing"].startswith("app;dur=")
    assert response.json()["window"]["end"] == "2026-10-20T00:00:00Z"


def test_days_is_bounded() -> None:
    h, client = make_api(make_store())
    for bad in ("0", "91", "abc"):
        response = client.get(
            "/api/v1/reconciliation/domains/commercial:contoso:catalog:domain:finance",
            params={"days": bad},
            headers=h.auth("6c1d2e3f-4a5b-4c6d-8e7f-90a1b2c3d4e5"),
        )
        assert response.status_code == 422
