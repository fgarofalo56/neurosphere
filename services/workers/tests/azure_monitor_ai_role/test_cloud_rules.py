"""azure_monitor_ai: Government is refused unless opted in; no query ever crosses clouds."""

from __future__ import annotations

from .support import Rig


async def test_government_is_refused_without_the_opt_in() -> None:
    rig = Rig(cloud="government")
    await rig.poller.tick()
    assert rig.factory_calls == []  # no connector, so no query and no commercial host
    assert rig.connector.calls == []
    assert rig.api.urls == []
    status = rig.poller.last_status
    assert (status.state, status.reason) == ("failed", "refused_government_unverified")
    assert status.counts == {"queries": 0, "rows": 0, "events_posted": 0, "rows_skipped": 0}


async def test_government_with_the_opt_in_polls_as_government() -> None:
    rig = Rig(cloud="government", allow_unverified_government=True)
    await rig.poller.tick()
    assert {cloud for cloud, _ in rig.factory_calls} == {"government"}
    assert rig.poller.last_status.state == "ok"


async def test_commercial_never_polls_as_government() -> None:
    rig = Rig(cloud="commercial", allow_unverified_government=True)
    await rig.poller.tick()
    assert {cloud for cloud, _ in rig.factory_calls} == {"commercial"}
