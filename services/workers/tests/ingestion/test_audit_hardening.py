"""PRP-07 audit close-out: doc id collisions (#28), watermark on duplicates (#29),
cloud fail-closed (#30), duplicates metric (#33)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from neurosphere_core.cloud import CloudName, Settings
from neurosphere_core.errors import DependencyTransientError, InvalidSchemaError
from neurosphere_core.observability import METRIC_INGEST_DUPLICATES
from neurosphere_workers.archive.factory import require_sink_cloud
from neurosphere_workers.ingestion import wiring
from neurosphere_workers.ingestion.models import compute_doc_id
from neurosphere_workers.ingestion.pipeline import process_batch
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from .support import T0, Doc, Harness, raw_event, settings, telemetry_at

# -- #28 ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (("c|x", "s", "e"), ("c", "x|s", "e")),
        (("c", "s|x", "e"), ("c", "s", "x|e")),
        (("c", "s", "e|x"), ("c|s", "e", "x")),
        (("a|b", "c", "d"), ("a", "b|c", "d")),
        (("c", "s", "e"), ("c", "s", "e|")),
        (("c|", "s", "e"), ("c", "|s", "e")),
    ],
)
def test_doc_id_does_not_collide_on_pipes(a: tuple[str, str, str], b: tuple[str, str, str]) -> None:
    assert compute_doc_id(*a) != compute_doc_id(*b)


def test_doc_id_is_stable_64_hex_and_differs_from_legacy_join() -> None:
    import hashlib

    first = compute_doc_id("c", "s", "e")
    assert first == compute_doc_id("c", "s", "e")
    assert len(first) == 64
    assert first != hashlib.sha256(b"c|s|e").hexdigest()


# -- #29 ------------------------------------------------------------------------------------


async def test_watermark_failure_after_marker_is_repaired_on_redelivery(
    harness: Harness, template: Doc
) -> None:
    newest = telemetry_at(template, "evt-new", T0 + timedelta(minutes=10))
    stale = telemetry_at(template, "evt-stale", T0)
    harness.watermarks.fail_transient(1)

    with pytest.raises(DependencyTransientError):
        await process_batch([raw_event(newest, 0)], harness.deps(), settings())
    key = (template["customer_id"], template["source_id"])
    assert key not in harness.watermarks.values  # marker written, watermark not

    redelivered = await process_batch([raw_event(newest, 0)], harness.deps(), settings())
    assert (redelivered.accepted, redelivered.duplicates) == (0, 1)
    assert harness.watermarks.values[key] == T0 + timedelta(minutes=10)

    later = await process_batch([raw_event(stale, 1)], harness.deps(), settings())
    assert later.late == 1  # no late-flag skew


# -- #30 ------------------------------------------------------------------------------------


def test_sink_cloud_government_and_commercial() -> None:
    assert require_sink_cloud(Settings(env="prod", cloud=CloudName.GOVERNMENT)) == "government"
    assert require_sink_cloud(Settings(env="prod", cloud=CloudName.COMMERCIAL)) == "commercial"


def test_sink_cloud_local_unset_follows_settings_default() -> None:
    assert require_sink_cloud(Settings(env="local")) == "commercial"


def test_sink_cloud_unset_outside_local_fails_closed() -> None:
    unset: Any = Settings.model_construct(env="prod", cloud=None)
    with pytest.raises(InvalidSchemaError) as info:
        require_sink_cloud(unset)
    assert "NS_CLOUD" in str(info.value)


async def test_build_pipeline_deps_fails_closed_before_touching_resources() -> None:
    from neurosphere_core.clients import ClientLifetime

    unset: Any = Settings.model_construct(env="prod", cloud=None)
    async with ClientLifetime() as lifetime:
        with pytest.raises(InvalidSchemaError):
            await wiring.build_pipeline_deps(unset, lifetime=lifetime)


# -- #33 ------------------------------------------------------------------------------------


async def test_duplicates_increment_the_metric(harness: Harness, template: Doc) -> None:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    doc = telemetry_at(template, "evt-metric", T0)
    deps = harness.deps()
    deps.meter = provider.get_meter("test")

    result = await process_batch([raw_event(doc, 0), raw_event(doc, 1)], deps, settings())

    assert result.duplicates == 1
    data = reader.get_metrics_data()
    assert data is not None
    metrics: list[Any] = [
        m for rm in data.resource_metrics for sm in rm.scope_metrics for m in sm.metrics
    ]
    dup = next(m for m in metrics if m.name == METRIC_INGEST_DUPLICATES)
    assert sum(p.value for p in dup.data.data_points) == 1
    provider.shutdown()
