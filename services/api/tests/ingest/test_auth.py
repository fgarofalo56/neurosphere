from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from neurosphere_api.ingest.auth import RegisteredCredentialAuthenticator, StaticProducerRegistry
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.errors import UnauthorizedError

from .conftest import CUSTOMER, PRODUCER, SOURCE, Harness, registration, span, traces_doc

URL = "/v1/ingest/otlp/traces"


def post(h: Harness, doc: dict[str, Any], headers: dict[str, str] | None = None):
    return h.client.post(
        URL,
        content=json.dumps(doc),
        headers={
            "content-type": "application/json",
            **(headers if headers is not None else h.auth),
        },
    )


def test_no_credential_is_401(harness: Harness) -> None:
    resp = post(harness, traces_doc([span()]), headers={})
    assert resp.status_code == 401
    assert harness.publisher.messages == []


def test_wrong_secret_is_401(harness: Harness) -> None:
    resp = post(
        harness,
        traces_doc([span()]),
        headers={"Authorization": f"Bearer {PRODUCER}.not-the-secret"},
    )
    assert resp.status_code == 401
    assert harness.publisher.messages == []


def test_unknown_producer_and_malformed_header_are_401(harness: Harness) -> None:
    for header in ("Bearer nobody.abc", "Bearer nodot", "Basic abc", "Bearer "):
        resp = post(harness, traces_doc([span()]), headers={"Authorization": header})
        assert resp.status_code == 401, header


def test_valid_credential_publishes_with_registration_stamps(harness: Harness) -> None:
    resp = post(harness, traces_doc([span()]))
    assert resp.status_code == 202
    assert resp.json()["accepted"] == 1
    (msg,) = harness.publisher.messages
    assert (msg.customer_id, msg.source_id, msg.producer_id) == (CUSTOMER, SOURCE, PRODUCER)
    assert msg.cloud == "commercial"
    assert msg.observation_kind == "application"
    assert msg.received_at.endswith("Z")


@pytest.mark.parametrize(
    "resource_attrs",
    [
        {"neurosphere.customer_id": "someone-else"},
        {"neurosphere.source_id": "unregistered-source"},
        {"neurosphere.cloud": "government"},
    ],
)
def test_claim_mismatch_is_403_and_nothing_published(
    harness: Harness, resource_attrs: dict[str, Any]
) -> None:
    resp = post(harness, traces_doc([span()], resource_attrs))
    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"
    assert harness.publisher.messages == []


def test_missing_source_with_multiple_allowed_sources_is_403(
    make_harness: Callable[..., Harness],
) -> None:
    h = make_harness(reg={"sources": {"a": "application", "b": "gateway"}})
    resp = post(h, traces_doc([span()]))
    assert resp.status_code == 403
    assert h.publisher.messages == []


def test_mismatch_in_second_resource_publishes_nothing(harness: Harness) -> None:
    good = traces_doc([span()])["resourceSpans"][0]
    bad = traces_doc([span(span_id="c7ad6b7169203331")], {"neurosphere.customer_id": "x"})[
        "resourceSpans"
    ][0]
    resp = post(harness, {"resourceSpans": [good, bad]})
    assert resp.status_code == 403
    assert harness.publisher.messages == []


def test_cloud_mismatch_between_edge_and_registration_is_403(
    make_harness: Callable[..., Harness],
) -> None:
    # Registration says government, but this edge is the (local default) commercial one.
    h = make_harness(reg={"cloud": "government"})
    resp = post(h, traces_doc([span()]))
    assert resp.status_code == 403
    assert resp.json()["reason"] == "cloud_mismatch"
    assert h.publisher.messages == []


def test_government_edge_accepts_government_registration(
    make_harness: Callable[..., Harness],
) -> None:
    h = make_harness(
        reg={"cloud": "government"}, edge_env=Settings(env="local", cloud=CloudName.GOVERNMENT)
    )
    assert post(h, traces_doc([span()])).status_code == 202
    assert h.publisher.messages[0].cloud == "government"


def test_unconfigured_service_fails_closed() -> None:
    from fastapi.testclient import TestClient
    from neurosphere_api.app import create_app

    client = TestClient(create_app(Settings(env="local")))
    assert client.post(URL, content=b"{}").status_code == 503


def test_registry_from_file_and_authenticator(tmp_path) -> None:
    reg = registration("fake-secret-value")
    path = tmp_path / "producers.json"
    path.write_text(json.dumps({"producers": [reg.model_dump(mode="json")]}), encoding="utf-8")
    auth = RegisteredCredentialAuthenticator(StaticProducerRegistry.from_file(path))
    assert auth.authenticate(f"Bearer {PRODUCER}.fake-secret-value").producer_id == PRODUCER
    with pytest.raises(UnauthorizedError):
        auth.authenticate(f"Bearer {PRODUCER}.other")
