"""gateway_poll: window, watermark, coverage, Government refusal, replay dedupe, secret hygiene."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from neurosphere_connector_azure_monitor import SourceKind
from neurosphere_core.errors import DependencyTransientError, RateLimitedError, StaleVersionError
from neurosphere_core.gateway import GatewayRegistration, InMemoryGatewayStore
from neurosphere_core.payload import HubMessage, HubMessageKind
from neurosphere_workers.ingestion.fakes import (
    FakeArchiveSink,
    FakeLedgerSink,
    FakeMarkerStore,
    FakeQuarantineSink,
    FakeWatermarkStore,
)
from neurosphere_workers.ingestion.gateway_poll import (
    STATUS_INGEST_FAILED,
    STATUS_OK,
    STATUS_PARTIAL,
    STATUS_REFUSED_GOVERNMENT,
    GatewayPollSettings,
)
from neurosphere_workers.ingestion.models import RawMessage
from neurosphere_workers.ingestion.pipeline import PipelineDeps, process_batch
from neurosphere_workers.ingestion.settings import IngestionSettings
from neurosphere_workers.runtime import ROLE_NAMES, parse_roles
from neurosphere_workers.runtime.factories import BUILDERS

from .support import (
    CUSTOMER,
    DOMAIN,
    FAKE_SECRET,
    NOW,
    WORKSPACE,
    FakeConnector,
    Rig,
    all_rows,
    registration,
    result,
)

LOOKBACK = timedelta(seconds=86400)
SLICE = timedelta(minutes=15)


async def _seed(rig: Rig, **kwargs: Any) -> GatewayRegistration:
    return await rig.store.create(registration(**kwargs))


async def test_first_poll_uses_lookback_and_both_sources() -> None:
    rig = Rig(FakeConnector([result(all_rows(), next_watermark=NOW - LOOKBACK + SLICE)]))
    reg = await _seed(rig)

    await rig.poller.tick()

    sources, watermark = rig.connector.calls[0]
    assert watermark == NOW - LOOKBACK
    assert [(s.kind, s.source_id) for s in sources] == [
        (SourceKind.APIM_GATEWAY, WORKSPACE),
        (SourceKind.APIM_MCP, WORKSPACE),
    ]
    assert rig.connector.closed == 1
    _cloud, bounds = rig.factory_calls[0]
    assert bounds.max_window == timedelta(seconds=3600)
    assert (await rig.current(reg)).poll_watermark == NOW - LOOKBACK + SLICE


async def test_events_are_telemetry_only_and_scoped() -> None:
    rig = Rig(FakeConnector([result(all_rows(), next_watermark=NOW)]))
    await _seed(rig)

    await rig.poller.tick()

    events = rig.api.events
    assert len(events) == len(all_rows()) > 0
    assert {e["type"] for e in events} == {"com.neurosphere.telemetry.v1"}  # no CostRecord
    for event in events:
        assert event["data"]["customer_id"] == CUSTOMER
        assert event["data"]["domain_id"] == DOMAIN
        assert event["data"]["source_id"] == "apim-gateway-poll"
        assert event["id"] == event["data"]["event_id"]


async def test_watermark_advances_on_full_coverage_and_feeds_next_tick() -> None:
    w1 = NOW - timedelta(minutes=20)
    w2 = NOW - timedelta(minutes=5)
    rig = Rig(
        FakeConnector(
            [result(all_rows(), next_watermark=w1), result([], next_watermark=w2, lag_ms=None)]
        )
    )
    reg = await _seed(rig)

    await rig.poller.tick()
    first = await rig.current(reg)
    assert (first.poll_watermark, first.poll_status, first.coverage) == (w1, STATUS_OK, 1.0)
    assert first.freshness_seconds == 60

    await rig.poller.tick()
    assert rig.connector.calls[1][1] == w1
    second = await rig.current(reg)
    assert second.poll_watermark == w2
    assert second.freshness_seconds == 60  # no records this tick: previous value kept, not 0


async def test_partial_slice_stops_the_watermark_and_is_repolled() -> None:
    w_ok = NOW - LOOKBACK + SLICE  # one slice answered, the next one was not
    rig = Rig(
        FakeConnector(
            [
                result(all_rows(), next_watermark=w_ok, answered=1, partial=True),
                result(all_rows(), next_watermark=w_ok + SLICE),
            ]
        )
    )
    reg = await _seed(rig)

    await rig.poller.tick()
    partial = await rig.current(reg)
    assert (partial.poll_watermark, partial.poll_status, partial.coverage) == (
        w_ok,
        STATUS_PARTIAL,
        0.5,
    )

    await rig.poller.tick()
    assert rig.connector.calls[1][1] == w_ok  # the unanswered slice starts exactly here
    healed = await rig.current(reg)
    assert (healed.poll_watermark, healed.poll_status, healed.coverage) == (
        w_ok + SLICE,
        STATUS_OK,
        1.0,
    )


async def test_watermark_never_moves_backwards() -> None:
    later = NOW - timedelta(minutes=10)
    rig = Rig(FakeConnector([result([], next_watermark=NOW - timedelta(hours=2))]))
    reg = await _seed(rig, poll_watermark=later)

    await rig.poller.tick()

    assert (await rig.current(reg)).poll_watermark == later


async def test_government_refused_without_opt_in_and_allowed_with_it() -> None:
    refused = Rig(FakeConnector([result(all_rows(), next_watermark=NOW)]), cloud="government")
    reg = await _seed(refused, cloud="government")
    await refused.poller.tick()
    assert refused.factory_calls == []
    assert refused.api.batches == []
    assert (await refused.current(reg)).poll_status == STATUS_REFUSED_GOVERNMENT

    allowed = Rig(
        FakeConnector([result(all_rows(), next_watermark=NOW)]),
        cloud="government",
        settings=GatewayPollSettings(domain_ids=DOMAIN, allow_unverified_government=True),
    )
    reg2 = await _seed(allowed, cloud="government")
    await allowed.poller.tick()
    assert [cloud for cloud, _ in allowed.factory_calls] == ["government"]
    assert allowed.api.events
    assert (await allowed.current(reg2)).poll_status == STATUS_OK


async def test_gateway_of_another_cloud_is_never_polled() -> None:
    rig = Rig(
        FakeConnector([result(all_rows(), next_watermark=NOW)]),
        cloud="commercial",
        settings=GatewayPollSettings(domain_ids=DOMAIN, allow_unverified_government=True),
    )
    reg = await _seed(rig, cloud="government")

    await rig.poller.tick()

    assert rig.factory_calls == []
    assert (await rig.current(reg)).poll_status == "cloud_mismatch"


async def test_gateway_without_workspace_is_skipped() -> None:
    rig = Rig(FakeConnector([result(all_rows(), next_watermark=NOW)]))
    reg = await _seed(rig, workspace_id=None)

    await rig.poller.tick()

    assert rig.factory_calls == []
    assert (await rig.current(reg)).poll_status is None


async def test_ingest_failure_keeps_the_watermark_and_never_raises() -> None:
    rig = Rig(FakeConnector([result(all_rows(), next_watermark=NOW)]))
    reg = await _seed(rig)
    rig.api.status = 503

    await rig.poller.tick()  # does not raise

    stored = await rig.current(reg)
    assert (stored.poll_watermark, stored.poll_status) == (None, STATUS_INGEST_FAILED)


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (RateLimitedError(30, "throttled"), "rate_limited"),
        (DependencyTransientError("down"), "poll_failed:dependency_transient"),
        (RuntimeError("boom"), "poll_failed:RuntimeError"),
    ],
)
async def test_connector_failures_become_a_status(error: Exception, status: str) -> None:
    rig = Rig(FakeConnector([error]))
    reg = await _seed(rig)

    await rig.poller.tick()

    stored = await rig.current(reg)
    assert (stored.poll_watermark, stored.poll_status) == (None, status)
    assert rig.connector.closed == 1


async def test_stale_etag_is_reread_and_retried_once() -> None:
    class RacingStore(InMemoryGatewayStore):
        raced = False

        async def replace(
            self, registration: GatewayRegistration, *, if_match: str
        ) -> GatewayRegistration:
            if not self.raced:
                self.raced = True
                # Someone else (a sync) updates the registration after the poller read it.
                other = registration.model_copy(update={"name": "renamed-by-sync"})
                await super().replace(other, if_match=if_match)
            return await super().replace(registration, if_match=if_match)

    store = RacingStore()
    rig = Rig(FakeConnector([result(all_rows(), next_watermark=NOW)]), store=store)
    reg = await _seed(rig)

    await rig.poller.tick()

    stored = await rig.current(reg)
    assert stored.poll_watermark == NOW
    assert stored.name == "renamed-by-sync"  # the concurrent change was kept, not clobbered
    assert store.raced


async def test_stale_etag_twice_drops_the_result_without_raising() -> None:
    class AlwaysStale(InMemoryGatewayStore):
        async def replace(
            self, registration: GatewayRegistration, *, if_match: str
        ) -> GatewayRegistration:
            raise StaleVersionError("stale", reason="gateway_modified")

    rig = Rig(FakeConnector([result(all_rows(), next_watermark=NOW)]), store=AlwaysStale())
    await _seed(rig)

    await rig.poller.tick()  # logged, not raised


# -- replay and dedupe through the real ingestion pipeline ---------------------------------------


def _raw(events: list[dict[str, Any]]) -> list[RawMessage]:
    """What the ingest edge would publish for each posted CloudEvent."""
    out: list[RawMessage] = []
    for i, event in enumerate(events):
        data = {**event["data"], "ingestion_time": "2026-10-29T10:31:00Z"}
        message = HubMessage(
            kind=HubMessageKind.TELEMETRY,
            event_id=data["event_id"],
            cloud=data["cloud"],
            customer_id=data["customer_id"],
            source_id=data["source_id"],
            producer_id="apim-gateway-poll",
            received_at="2026-10-29T10:31:00Z",
            request_id=data.get("request_id"),
            observation_kind="gateway",
            data=data,
        )
        out.append(
            RawMessage(
                body=message.to_bytes(),
                partition_id="0",
                offset=str(i),
                sequence_number=i,
                enqueued_time=NOW,
            )
        )
    return out


async def test_replayed_window_posts_duplicates_but_the_ledger_has_none() -> None:
    rows = all_rows()
    rig = Rig(
        FakeConnector(
            [
                result(rows, next_watermark=NOW - timedelta(minutes=10)),
                result(rows, next_watermark=NOW),  # the same rows come back (overlap / replay)
            ]
        )
    )
    reg = await _seed(rig)

    await rig.poller.tick()
    await rig.poller.tick()
    # Second tick re-reads the same window because a store write was lost in the interim.
    posted = rig.api.events
    assert len(posted) == 2 * len(rows)
    assert len({e["id"] for e in posted}) == len(rows)

    ledger, archive = FakeLedgerSink(), FakeArchiveSink()
    deps = PipelineDeps(
        quarantine=FakeQuarantineSink(),
        archive=archive,
        ledger=ledger,
        markers=FakeMarkerStore(),
        watermarks=FakeWatermarkStore(),
        cloud="commercial",
        clock=lambda: NOW,
    )
    outcome = await process_batch(_raw(posted), deps, IngestionSettings())

    assert outcome.accepted == len(rows)
    assert outcome.duplicates == len(rows)
    assert len(ledger.effects) == len(rows)
    assert len(archive.effects) == len(rows)
    assert (await rig.current(reg)).poll_watermark == NOW


# -- secrets ------------------------------------------------------------------------------------


async def test_secret_is_sent_but_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    rig = Rig(FakeConnector([result(all_rows(), next_watermark=NOW)]))
    await _seed(rig)

    await rig.poller.tick()
    rig.api.status = 500
    rig.connector = FakeConnector([result(all_rows(), next_watermark=NOW)])
    await rig.poller.tick()

    assert rig.api.headers[0]["authorization"] == f"Bearer apim-gateway-poll.{FAKE_SECRET}"
    assert rig.api.headers[0]["content-type"] == "application/cloudevents-batch+json"
    rendered = caplog.text + "".join(json.dumps(r.__dict__, default=str) for r in caplog.records)
    assert FAKE_SECRET not in rendered


def test_settings_never_print_the_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NS_GATEWAY_POLL_PRODUCER_SECRET", FAKE_SECRET)
    monkeypatch.setenv("NS_API_BASE_URL", "http://127.0.0.1:8000")
    settings = GatewayPollSettings()
    assert settings.producer_secret is not None
    assert settings.producer_secret.get_secret_value() == FAKE_SECRET
    assert FAKE_SECRET not in repr(settings)
    assert FAKE_SECRET not in str(settings.model_dump())
    assert settings.api_base_url == "http://127.0.0.1:8000"


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "NS_GATEWAY_POLL_INTERVAL_SECONDS",
        "NS_GATEWAY_POLL_WINDOW_SECONDS",
        "NS_GATEWAY_POLL_LOOKBACK_SECONDS",
        "NS_GATEWAY_POLL_ALLOW_UNVERIFIED_GOVERNMENT",
        "NS_GATEWAY_POLL_DOMAIN_IDS",
        "NS_GATEWAY_POLL_PRODUCER_SECRET",
        "NS_API_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    s = GatewayPollSettings()
    assert (s.interval_seconds, s.window_seconds, s.lookback_seconds) == (900, 3600, 86400)
    assert s.allow_unverified_government is False
    assert (s.producer_id, s.producer_secret, s.api_base_url, s.domains) == (
        "apim-gateway-poll",
        None,
        None,
        (),
    )


def test_producers_example_matches_the_fake_secret() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "neurosphere_workers"
        / "ingestion"
        / "gateway_poll"
        / "producers.example.json"
    )
    producer = json.loads(path.read_text(encoding="utf-8"))["producers"][0]
    assert producer["producer_id"] == "apim-gateway-poll"
    assert producer["sources"] == {"apim-gateway-poll": "gateway"}
    assert producer["secret_sha256"] == hashlib.sha256(FAKE_SECRET.encode()).hexdigest()


# -- role registration --------------------------------------------------------------------------


def test_role_is_registered_and_opt_in() -> None:
    assert "gateway_poll" in ROLE_NAMES
    assert parse_roles("gateway_poll") == ("gateway_poll",)
    assert "gateway_poll" not in parse_roles("all")
    assert "gateway_poll" in parse_roles("all,gateway_poll")
    assert "gateway_poll" in BUILDERS
