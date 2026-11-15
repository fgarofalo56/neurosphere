"""PRP-46 (#167): the duplicates counter is created once per PipelineDeps."""

from __future__ import annotations

from typing import Any

from neurosphere_workers.ingestion.pipeline import process_batch

from .support import T0, Harness, raw_event, settings, telemetry_at  # type: ignore[attr-defined]


class _CountingMeter:
    def __init__(self) -> None:
        self.created = 0

    def create_counter(self, *_args: Any, **_kwargs: Any) -> Any:
        self.created += 1

        class _Counter:
            def add(self, *_a: Any, **_k: Any) -> None:
                return None

        return _Counter()


async def test_counter_created_once_across_batches(harness: Harness, template: Any) -> None:
    meter = _CountingMeter()
    deps = harness.deps()
    deps.meter = meter  # type: ignore[assignment]
    for n in range(3):
        doc = telemetry_at(template, f"evt-{n}", T0)
        await process_batch([raw_event(doc, n)], deps, settings())
    assert meter.created == 1
