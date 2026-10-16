"""A sink serves one cloud; a mismatching event is refused and nothing is written."""

from __future__ import annotations

import pytest
from neurosphere_core.errors import ForbiddenError

from .support import T0, Doc, FakeContainer, make_event, make_sink


async def test_government_event_refused_by_commercial_sink(
    template: Doc, container: FakeContainer
) -> None:
    event = await make_event(template, "evt-c1", T0, cloud="government")
    sink = make_sink(container, cloud="commercial")

    with pytest.raises(ForbiddenError) as info:
        await sink.write(event)

    assert info.value.retryable is False
    assert container.upload_calls == 0
    assert container.blobs == {}


async def test_commercial_event_refused_by_government_sink(
    template: Doc, container: FakeContainer
) -> None:
    event = await make_event(template, "evt-c2", T0, cloud="commercial")
    with pytest.raises(ForbiddenError):
        await make_sink(container, cloud="government").write(event)
    assert container.blobs == {}


async def test_matching_cloud_is_written(template: Doc, container: FakeContainer) -> None:
    event = await make_event(template, "evt-c3", T0, cloud="government")
    await make_sink(container, cloud="government").write(event)
    assert len(container.blobs) == 1


def test_unknown_cloud_is_a_configuration_error(container: FakeContainer) -> None:
    with pytest.raises(ValueError, match="cloud"):
        make_sink(container, cloud="azure-stack")
