"""PRP-49: subject documents through the full outbox -> aggregate path."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from neurosphere_core.aggregates import InMemoryAggregateStore, SubjectPoint

from neurosphere_workers.aggregates import rollups

from .support import CUST, DOMAIN, NOW, Rig, days_ago, event_doc, wide_window

AGENT_A = "commercial:cust-1:src-1:agent:alpha"
AGENT_B = "commercial:cust-1:src-1:agent:beta"


def _at(minutes: int = 0):  # type: ignore[no-untyped-def]
    return NOW.replace(minute=0) - timedelta(hours=1) + timedelta(minutes=minutes)


async def _subject(rig: Rig, grain: str = "hour") -> dict[str, SubjectPoint]:
    result = await rig.aggregates.query(
        CUST,
        DOMAIN,
        "subject",
        grain,  # type: ignore[arg-type]
        rig_window(rig, grain),
        max_series=50,
        max_points=100,
    )
    return {s.key: s.points[-1] for s in result.series}  # type: ignore[misc]


def rig_window(rig: Rig, grain: str):  # type: ignore[no-untyped-def]
    return wide_window(rig, 13 if grain == "hour" else 90)


async def test_agent_and_model_series_at_hour_and_day_grain() -> None:
    rig = Rig()
    await rig.add_event(
        event_doc(
            "a",
            at=_at(),
            duration_ms=100,
            outcome="success",
            agent=AGENT_A,
            provider="Azure_OpenAI",
            model="GPT-4o",
            input_tokens=10,
            output_tokens=4,
        )
    )
    await rig.add_event(
        event_doc(
            "b",
            at=_at(5),
            duration_ms=300,
            outcome="error",
            agent=AGENT_A,
            provider="azure_openai",
            model="gpt-4o",
            input_tokens=1,
            output_tokens=1,
        )
    )
    await rig.add_event(
        event_doc(
            "c",
            at=_at(6),
            duration_ms=50,
            outcome="success",
            agent=AGENT_B,
            provider="azure_openai",
            model="gpt-4o",
            input_tokens=2,
            output_tokens=2,
        )
    )
    assert (await rig.drain()).ok
    for grain in ("hour", "day"):
        points = await _subject(rig, grain)
        assert sorted(points) == [
            f"agent:{AGENT_A}",
            f"agent:{AGENT_B}",
            "model:azure_openai/gpt-4o",
        ]
        a = points[f"agent:{AGENT_A}"]
        assert (a.event_count, a.error_count, a.error_rate) == (2, 1, 0.5)
        assert (a.input_tokens, a.output_tokens, a.p95_ms) == (11, 5, 300)
        assert a.complete is True
        model = points["model:azure_openai/gpt-4o"]
        assert model.event_count == 3
        assert model.subject_kind == "model"
        assert model.series_key == model.subject_key


async def test_unknowns_stay_unknown_never_zero() -> None:
    rig = Rig()
    # No agent: adds to no agent series. Model known, but duration, outcome and tokens unknown.
    await rig.add_event(
        event_doc("x", at=_at(), duration_ms=None, outcome=None, provider="p", model="m")
    )
    await rig.add_event(event_doc("y", at=_at(1), duration_ms=None, outcome=None, agent=AGENT_A))
    assert (await rig.drain()).ok
    points = await _subject(rig)
    assert sorted(points) == [f"agent:{AGENT_A}", "model:p/m"]
    for point in points.values():
        assert point.event_count == 1
        assert point.missing_duration_count == 1
        assert point.unknown_outcome_count == 1
        assert point.p95_ms is None
        assert point.error_count is None
        assert point.error_rate is None
        assert point.input_tokens is None
        assert point.output_tokens is None
        assert point.tokens_known_count == 0
        assert point.complete is False


async def test_partial_tokens_keep_the_known_sum_and_are_incomplete() -> None:
    rig = Rig()
    await rig.add_event(event_doc("a", at=_at(), duration_ms=1, agent=AGENT_A, input_tokens=7))
    await rig.add_event(event_doc("b", at=_at(1), duration_ms=1, agent=AGENT_A))
    assert (await rig.drain()).ok
    point = (await _subject(rig))[f"agent:{AGENT_A}"]
    assert (point.input_tokens, point.output_tokens, point.tokens_known_count) == (7, None, 1)
    assert point.complete is False


async def test_replay_and_rebuild_are_idempotent_and_write_only_changes() -> None:
    rig = Rig()
    for n in range(3):
        await rig.add_event(
            event_doc(
                f"e{n}", at=_at(n), duration_ms=10 * (n + 1), agent=AGENT_A, provider="p", model="m"
            )
        )
    assert (await rig.drain()).ok
    first = rig.snapshot()
    store = rig.aggregates
    assert isinstance(store, InMemoryAggregateStore)
    writes = store.document_writes
    assert (await rig.replay_all()).ok
    assert rig.snapshot() == first
    assert store.document_writes == writes  # an identical rebuild writes nothing

    # One new event in the bucket changes the bucket's documents only.
    await rig.add_event(event_doc("late", at=_at(9), duration_ms=5, agent=AGENT_B))
    assert (await rig.drain()).ok
    changed = store.document_writes - writes
    # hour + day: latency, errors and the new agent series are new; agent A and model unchanged.
    assert changed == 2 * 3


async def test_bucket_cap_is_deterministic_and_logs_a_count_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(rollups, "MAX_SUBJECT_SERIES_PER_BUCKET", 2)
    rig = Rig()
    for name in ("c", "a", "b"):
        await rig.add_event(
            event_doc(
                name,
                at=_at(),
                duration_ms=1,
                agent=f"commercial:cust-1:src-1:agent:{name}",
            )
        )
    with caplog.at_level(logging.WARNING):
        assert (await rig.drain()).ok
    kept = sorted(await _subject(rig))
    assert kept == [
        "agent:commercial:cust-1:src-1:agent:a",
        "agent:commercial:cust-1:src-1:agent:b",
    ]
    assert all("agent:c" not in r.getMessage() for r in caplog.records)
    assert any(getattr(r, "dropped", None) == 1 for r in caplog.records)


async def test_events_out_of_window_hour_still_use_day_series() -> None:
    rig = Rig()
    await rig.add_event(event_doc("old", at=days_ago(30), duration_ms=1, agent=AGENT_A))
    assert (await rig.drain()).ok
    assert await _subject(rig, "hour") == {}
    assert f"agent:{AGENT_A}" in await _subject(rig, "day")
