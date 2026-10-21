"""Scope on replay routes: 403 outside the path domain, other customers' and other domains' spans
never returned, fail closed when the reader is missing, pagination bounded, payload bodies off."""

from neurosphere_api.replay import PayloadPolicy, get_trace_reader
from replay_support import (  # pyright: ignore[reportMissingImports]
    ALICE,
    BOB,
    FINANCE,
    OPERATIONS,
    OTHER_TRACE,
    TRACE,
    make_api,
    sid,
    span,
)


def test_viewer_outside_domain_is_403_and_leaks_nothing() -> None:
    api = make_api(span(1, None, domain=OPERATIONS))
    response = api.trace(ALICE, OPERATIONS)
    assert response.status_code == 403
    assert sid(1) not in response.text
    assert api.get(ALICE, f"/domains/{OPERATIONS}/traces").status_code == 403


def test_unauthenticated_is_401() -> None:
    assert make_api().trace(None, FINANCE).status_code == 401


def test_trace_of_another_domain_is_404_like_an_absent_trace() -> None:
    api = make_api(span(1, None, domain=OPERATIONS))
    other = api.trace(ALICE, FINANCE)  # trace exists, but only in OPERATIONS
    absent = api.trace(ALICE, FINANCE, OTHER_TRACE)
    assert other.status_code == absent.status_code == 404
    strip = {"correlation_id", "instance"}
    assert {k: v for k, v in other.json().items() if k not in strip} == {
        k: v for k, v in absent.json().items() if k not in strip
    }


def test_other_customers_spans_are_never_returned() -> None:
    api = make_api(
        span(1, None),
        span(2, 1, customer="fabrikam", offset_ms=10),
    )
    body = api.trace(ALICE, FINANCE).json()
    assert [s["span_id"] for s in body["spans"]] == [sid(1)]
    assert body["completeness"]["withheld_span_count"] == 0


def test_other_customers_trace_is_404() -> None:
    api = make_api(span(1, None, customer="fabrikam"))
    assert api.trace(ALICE, FINANCE).status_code == 404
    assert api.get(ALICE, f"/domains/{FINANCE}/traces").json()["items"] == []


def test_cross_domain_span_is_dropped_and_reported_as_gap() -> None:
    api = make_api(
        span(1, None),
        span(2, 1, offset_ms=10),
        span(3, 2, offset_ms=20, domain=OPERATIONS),  # another domain, same customer
        span(4, 3, offset_ms=30),  # kept span whose parent was withheld
    )
    response = api.trace(ALICE, FINANCE)
    body = response.json()
    assert sid(3) not in [s["span_id"] for s in body["spans"]]
    assert body["completeness"]["withheld_span_count"] == 1
    reasons = {(g["reason"], g["span_id"]) for g in body["gaps"]}
    assert ("missing_parent", sid(4)) in reasons
    assert any(g["reason"] == "unknown" and g["count"] == 1 for g in body["gaps"])
    assert body["completeness"]["state"] == "partial"


def test_caller_supplied_scope_params_do_not_widen_scope() -> None:
    api = make_api(span(1, None, domain=OPERATIONS))
    response = api.trace(ALICE, FINANCE, domain_id=OPERATIONS, customer_id="fabrikam")
    assert response.status_code == 404
    assert api.trace(BOB, OPERATIONS).status_code == 200


def test_unconfigured_reader_fails_closed_503() -> None:
    api = make_api()
    api.h.app.dependency_overrides.pop(get_trace_reader)
    response = api.trace(ALICE, FINANCE)
    assert response.status_code == 503
    assert response.json()["reason"] == "trace_reader_unconfigured"


def test_policy_store_outage_is_503() -> None:
    api = make_api(span(1, None))
    api.h.repo.fail_with(ConnectionError("policy store down"))
    assert api.trace(ALICE, FINANCE).status_code == 503


def test_reader_failure_is_503_not_empty() -> None:
    api = make_api()

    class Broken:
        async def get_trace(self, *args: object) -> None:
            raise ConnectionError("blob down")

        async def list_traces(self, *args: object) -> None:
            raise ConnectionError("blob down")

        async def read_payload(self, *args: object) -> None:
            return None

    api.h.app.dependency_overrides[get_trace_reader] = lambda: Broken()
    assert api.trace(ALICE, FINANCE).status_code == 503
    assert api.get(ALICE, f"/domains/{FINANCE}/traces").status_code == 503


def test_trace_list_is_paginated() -> None:
    records = [
        span(i, None, trace=f"{i:032x}", offset_ms=i * 1000, domain=FINANCE) for i in range(1, 6)
    ]
    api = make_api(*records)
    first = api.get(ALICE, f"/domains/{FINANCE}/traces", page_size=2).json()
    assert len(first["items"]) == 2
    assert first["next_cursor"]
    second = api.get(
        ALICE, f"/domains/{FINANCE}/traces", page_size=2, cursor=first["next_cursor"]
    ).json()
    last = api.get(
        ALICE, f"/domains/{FINANCE}/traces", page_size=2, cursor=second["next_cursor"]
    ).json()
    ids = [t["trace_id"] for page in (first, second, last) for t in page["items"]]
    assert len(ids) == len(set(ids)) == 5
    assert last["next_cursor"] is None
    assert api.get(ALICE, f"/domains/{FINANCE}/traces", page_size=9999).status_code == 422
    assert api.get(ALICE, f"/domains/{FINANCE}/traces", cursor="!!").status_code == 422


def test_payload_bodies_are_off_by_default_even_when_requested() -> None:
    record = span(1, None, pointer="p/1", redaction="redacted")
    api = make_api(record)
    api.reader.payloads[("contoso", "p/1")] = {"note": "stored redacted content"}
    body = api.trace(ALICE, FINANCE, include_payload="true").json()
    assert body["spans"][0]["payload_state"] == "redacted"
    assert body["spans"][0]["payload"] is None


def test_payload_body_requires_policy_and_opt_in_and_redacted_state() -> None:
    redacted = span(1, None, pointer="p/1", redaction="redacted")
    pending = span(2, 1, offset_ms=5, pointer="p/2", redaction="pending")
    api = make_api(redacted, pending, policy=PayloadPolicy(allow_bodies=True))
    api.reader.payloads[("contoso", "p/1")] = {"note": "stored redacted content"}
    api.reader.payloads[("contoso", "p/2")] = {"note": "must not appear"}

    no_opt_in = api.trace(ALICE, FINANCE).json()
    assert all(s["payload"] is None for s in no_opt_in["spans"])

    opted = {
        s["span_id"]: s for s in api.trace(ALICE, FINANCE, include_payload="true").json()["spans"]
    }
    assert opted[sid(1)]["payload"] == {"note": "stored redacted content"}
    assert opted[sid(2)]["payload"] is None
    assert opted[sid(2)]["payload_state"] == "pending"
    assert TRACE  # fixture trace id in use
