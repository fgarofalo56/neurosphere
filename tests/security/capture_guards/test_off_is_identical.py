"""PRP-103: capture attached but OFF publishes exactly what a service without capture publishes.

For the OTLP traces, OTLP metrics and CloudEvents routes, the published hub message bytes and
the 202 body of a golden run (no capture attached) equal those of a run with the capture
adapter attached and off. Every body field carries a canary, so "identical" also proves the
OFF path publishes no content.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from neurosphere_api.ingest import InMemoryPublisher, ProducerRegistration
from neurosphere_api.ingest.capture import EdgeCapture
from neurosphere_api.ingest.service import IngestService
from neurosphere_core.payload import find_body_fields

from . import guard_helpers as g

Route = Callable[[IngestService, ProducerRegistration, g.Issued], Awaitable[Any]]


def _traces(issued: g.Issued) -> bytes:
    spans = [
        g.span("d7ad6b7169203331", {"gen_ai.prompt": issued.canary(), "gen_ai.request.model": "m"}),
        g.span("d7ad6b7169203332", {"gen_ai.completion": issued.canary()}),
    ]
    return json.dumps(g.traces_doc(spans)).encode()


def _events(issued: g.Issued, *, batch: bool) -> bytes:
    credential = issued.credential()
    items = [g.body_item(issued, "evt-off-1", credential)]
    if batch:
        items.append(g.body_item(issued, "evt-off-2", credential))
        return json.dumps(items).encode()
    return json.dumps(items[0]).encode()


ROUTES: dict[str, Route] = {
    "traces": lambda svc, p, i: svc.ingest_otlp_traces(p, _traces(i), correlation_id=g.CORRELATION),
    "metrics": lambda svc, p, i: svc.ingest_otlp_metrics(
        p, json.dumps(g.metrics_doc(i.canary())).encode()
    ),
    "events_structured": lambda svc, p, i: svc.ingest_events(
        p, _events(i, batch=False), g.STRUCTURED, correlation_id=g.CORRELATION
    ),
    "events_batch": lambda svc, p, i: svc.ingest_events(
        p, _events(i, batch=True), g.BATCH, correlation_id=g.CORRELATION
    ),
}


async def _run(
    route: Route, registration: ProducerRegistration, capture: EdgeCapture | None, seed: g.Issued
) -> tuple[list[bytes], str, dict[str, int]]:
    publisher = InMemoryPublisher()
    service = g.ingest_service(publisher, registration)
    if capture is not None:
        service.attach_capture(capture)
    result = await route(service, registration, seed)
    counters = {"cost_center_mismatches": service.cost_center_mismatches}
    return [m.to_bytes() for m in publisher.messages], result.model_dump_json(), counters


class _Replay(g.Issued):
    """Replays the values of a first run so both runs send byte-identical requests."""

    def __init__(self, values: list[str]) -> None:
        super().__init__()
        self._queue = list(values)

    def _keep(self, value: str) -> str:
        del value
        return super()._keep(self._queue.pop(0))


@pytest.mark.parametrize("route_name", sorted(ROUTES))
async def test_capture_off_is_byte_identical_to_no_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, route_name: str
) -> None:
    route = ROUTES[route_name]
    registration = g.producer()

    golden_seed = g.Issued()
    golden = await _run(route, registration, None, golden_seed)

    capture, store, audit, _wrapper = await g.edge_capture(tmp_path, monkeypatch, capture_on=False)
    assert not capture.active
    stats_before = capture.stats.snapshot()
    replay = _Replay(golden_seed.values)
    attached = await _run(route, registration, capture, replay)

    assert replay.values == golden_seed.values
    assert attached == golden
    messages, _body, _counters = golden
    assert messages, "the route must publish something for the comparison to mean anything"
    for raw in messages:
        fields = find_body_fields(json.loads(raw))
        assert fields == []
        g.assert_no_leak(raw.decode(), golden_seed.probes(), "an OFF hub message")
    # Criterion 1: every counter is as without capture. The service counters are compared in
    # ``attached == golden``; the capture stats are untouched by the OFF run and equal a fresh,
    # never-used OFF adapter's.
    pristine, _s, _a, _w = await g.edge_capture(tmp_path, monkeypatch, capture_on=False)
    stats_after = capture.stats.snapshot()
    assert stats_after == stats_before
    assert stats_after == pristine.stats.snapshot()
    assert stats_after["captured"] == 0
    assert store.index_backend.documents == {}
    assert audit.drafts == []
