"""gateway_poll: the token-metric cost center rides the posted event, and only when attributed."""

from __future__ import annotations

from neurosphere_connector_azure_monitor import SourceKind
from neurosphere_core.errors import DependencyTransientError
from neurosphere_workers.ingestion.gateway_poll import COST_CENTER_EXTENSION, STATUS_OK

from .support import NOW, FakeConnector, Rig, all_rows, fixture_rows, registration, result

APP = "33333333-3333-3333-3333-333333333333"


def _metrics() -> list[dict[str, object]]:
    return fixture_rows("apim_usage_metrics_response.json", "apim_usage_metrics")


async def test_attributed_cost_center_rides_the_event_and_is_otherwise_omitted() -> None:
    connector = FakeConnector(
        [result(all_rows(), next_watermark=NOW), result(_metrics(), next_watermark=NOW)]
    )
    rig = Rig(connector, metrics_app_id=APP)
    await rig.store.create(registration())

    await rig.poller.tick()

    metric_sources, _ = connector.calls[1]
    assert [(s.kind, s.source_id) for s in metric_sources] == [(SourceKind.APIM_USAGE_METRICS, APP)]
    by_id = {e["id"]: e for e in rig.api.events}
    assert by_id["corr-llm-0001"][COST_CENTER_EXTENSION] == "CC-4410"
    assert COST_CENTER_EXTENSION not in by_id["corr-plain-0002"]  # N/A: never invented
    assert all(COST_CENTER_EXTENSION not in e for e in rig.api.events if e["id"] != "corr-llm-0001")


async def test_no_metrics_app_means_no_second_query_and_no_tag() -> None:
    connector = FakeConnector([result(all_rows(), next_watermark=NOW)])
    rig = Rig(connector)
    await rig.store.create(registration())

    await rig.poller.tick()

    assert len(connector.calls) == 1
    assert all(COST_CENTER_EXTENSION not in e for e in rig.api.events)


async def test_metrics_failure_costs_only_the_tag() -> None:
    connector = FakeConnector(
        [result(all_rows(), next_watermark=NOW), DependencyTransientError("metrics down")]
    )
    rig = Rig(connector, metrics_app_id=APP)
    reg = await rig.store.create(registration())

    await rig.poller.tick()

    assert (await rig.current(reg)).poll_status == STATUS_OK
    assert len(rig.api.events) == len(all_rows())
    assert all(COST_CENTER_EXTENSION not in e for e in rig.api.events)


async def test_replayed_window_yields_the_same_event_ids_and_tag() -> None:
    connector = FakeConnector(
        [
            result(all_rows(), next_watermark=NOW),
            result(_metrics(), next_watermark=NOW),
            result(all_rows(), next_watermark=NOW),
            result(_metrics(), next_watermark=NOW),
        ]
    )
    rig = Rig(connector, metrics_app_id=APP)
    await rig.store.create(registration())

    await rig.poller.tick()
    first = list(rig.api.events)
    rig.api.batches.clear()
    await rig.poller.tick()

    assert [e["id"] for e in rig.api.events] == [e["id"] for e in first]
    assert len({e["id"] for e in first}) == len(first)  # one event per correlation id
    assert rig.api.events == first
