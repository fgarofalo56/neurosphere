"""PRP-103 criterion 1: with capture attached but OFF, every ingest route is byte-identical.

For each route the published message bytes, the 202 body and the service counters are compared
between a service with no capture attached and one with capture attached but off (stored setting
off, retention not opted in, no policy). While off, nothing is extracted: extraction is replaced
by a function that fails the test if it is ever called.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from neurosphere_api.ingest import InMemoryPublisher
from neurosphere_api.ingest import capture as edge_module
from neurosphere_api.ingest.service import IngestService

from . import edge_helpers as h
from .edge_helpers import BATCH, DOMAIN, STRUCTURED, TELEMETRY_TYPE, ce, telemetry_data

Route = Callable[[IngestService, Any], Awaitable[Any]]


def _traces_body() -> bytes:
    doc = h.traces_doc(
        [
            h.span(
                "b7ad6b7169203331",
                {"gen_ai.prompt": "synthetic prompt text", "gen_ai.request.model": "m-x"},
            ),
            h.span("b7ad6b7169203332", {"gen_ai.completion": "synthetic reply"}),
        ]
    )
    return json.dumps(doc).encode()


def _events(batch: bool) -> bytes:
    telemetry = ce(
        TELEMETRY_TYPE,
        telemetry_data("evt-1", domain_id=DOMAIN, prompt="synthetic prompt text"),
        "ce-1",
        nscostcenter="cc-synthetic",
    )
    if not batch:
        return json.dumps(telemetry).encode()
    cost = ce(h.COST_TYPE, {**h.cost_data("cost-1"), "tags": {"cost_center": "cc-other"}}, "ce-2")
    cost["nscostcenter"] = "cc-synthetic"
    bad = ce(TELEMETRY_TYPE, {"event_id": "evt-bad", "source_id": h.SOURCE}, "ce-3")
    return json.dumps([telemetry, cost, bad]).encode()


ROUTES: dict[str, Route] = {
    "otlp_traces": lambda svc, p: svc.ingest_otlp_traces(p, _traces_body()),
    "otlp_metrics": lambda svc, p: svc.ingest_otlp_metrics(p, json.dumps(h.metrics_doc()).encode()),
    "events_structured": lambda svc, p: svc.ingest_events(p, _events(False), STRUCTURED),
    "events_batch": lambda svc, p: svc.ingest_events(p, _events(True), BATCH),
}

OFF_MODES: dict[str, dict[str, Any]] = {
    "setting_off": {"setting": False},
    "retention_not_enabled": {"opt_in": False},
    "no_policy": {"policies": []},
    "not_approved": {"policies": [h.policy_doc(state="proposed", approved_audit_id=None)]},
}


async def _run(route: Route, capture: Any | None) -> tuple[list[bytes], str, int]:
    publisher = InMemoryPublisher()
    registration = h.producer()
    service = h.service(publisher, registration)
    if capture is not None:
        service.attach_capture(capture)
    result = await route(service, registration)
    return (
        [m.to_bytes() for m in publisher.messages],
        result.model_dump_json(),
        service.cost_center_mismatches,
    )


@pytest.mark.parametrize("route_name", sorted(ROUTES))
@pytest.mark.parametrize("mode", sorted(OFF_MODES))
async def test_capture_off_is_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route_name: str, mode: str
) -> None:
    route = ROUTES[route_name]
    baseline = await _run(route, None)

    capture, store, audit = await h.edge_capture(tmp_path, monkeypatch, **OFF_MODES[mode])
    assert capture.status() == mode
    assert not capture.active

    def never(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("extraction must not run while capture is off")

    monkeypatch.setattr(edge_module, "extract_body_parts", never)
    attached = await _run(route, capture)

    assert attached == baseline
    assert baseline[0], "the route must publish something for the comparison to mean anything"
    assert capture.stats.snapshot()["captured"] == 0
    assert capture.stats.snapshot()["capture_skipped_no_policy"] == 0
    assert store.index_backend.documents == {}
    assert audit.drafts == []


@pytest.mark.parametrize("route_name", ["otlp_metrics"])
async def test_metrics_route_is_identical_even_with_capture_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route_name: str
) -> None:
    """Capture is only on the OTLP traces and CloudEvents telemetry paths."""
    route = ROUTES[route_name]
    baseline = await _run(route, None)
    capture, store, _audit = await h.edge_capture(tmp_path, monkeypatch)
    assert capture.active
    attached = await _run(route, capture)
    assert attached == baseline
    assert store.index_backend.documents == {}


async def test_capture_on_without_a_match_leaves_messages_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Capture on, but the OTLP spans carry no domain: published bytes and 202 are unchanged."""
    route = ROUTES["otlp_traces"]
    baseline = await _run(route, None)
    capture, store, _audit = await h.edge_capture(tmp_path, monkeypatch)
    attached = await _run(route, capture)
    assert attached == baseline
    assert capture.stats.snapshot()["skipped_reasons"] == {"domain_missing": 2}
    assert store.index_backend.documents == {}


async def test_detach_restores_the_plain_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture, _store, _audit = await h.edge_capture(tmp_path, monkeypatch)
    publisher = InMemoryPublisher()
    service = h.service(publisher, h.producer())
    service.attach_capture(capture)
    assert service.capture is capture
    service.attach_capture(None)
    assert service.capture is None
