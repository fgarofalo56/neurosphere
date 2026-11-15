"""PRP-46 (#179): attribution counts land on the registration after a poll."""

from __future__ import annotations

from neurosphere_core.errors import DependencyTransientError
from neurosphere_workers.ingestion.gateway_poll import STATUS_OK

from .support import NOW, FakeConnector, Rig, all_rows, fixture_rows, registration, result

APP = "33333333-3333-3333-3333-333333333333"


def _metrics() -> list[dict[str, object]]:
    return fixture_rows("apim_usage_metrics_response.json", "apim_usage_metrics")


async def test_poll_records_attribution_counts() -> None:
    connector = FakeConnector(
        [result(all_rows(), next_watermark=NOW), result(_metrics(), next_watermark=NOW)]
    )
    rig = Rig(connector, metrics_app_id=APP)
    reg = await rig.store.create(registration())

    await rig.poller.tick()

    current = await rig.current(reg)
    attribution = current.poll_attribution
    assert attribution is not None
    assert attribution.metrics_query_failed is False
    attributed = (
        attribution.attributed_row
        + attribution.attributed_exact
        + attribution.attributed_subscription_only
    )
    assert attributed >= 1
    assert attributed + attribution.unattributed == sum(
        1 for r in all_rows() if r["source_kind"] == "apim_gateway"
    )


async def test_metrics_failure_is_visible_and_poll_stays_ok() -> None:
    connector = FakeConnector(
        [result(all_rows(), next_watermark=NOW), DependencyTransientError("metrics down")]
    )
    rig = Rig(connector, metrics_app_id=APP)
    reg = await rig.store.create(registration())

    await rig.poller.tick()

    current = await rig.current(reg)
    assert current.poll_status == STATUS_OK
    assert current.poll_attribution is not None
    assert current.poll_attribution.metrics_query_failed is True
    assert current.poll_attribution.attributed_exact == 0


async def test_no_metrics_app_is_not_a_failure() -> None:
    connector = FakeConnector([result(all_rows(), next_watermark=NOW)])
    rig = Rig(connector)
    reg = await rig.store.create(registration())

    await rig.poller.tick()

    current = await rig.current(reg)
    assert current.poll_attribution is not None
    assert current.poll_attribution.metrics_query_failed is False
