"""Gap, sampling, late, timing and tool labelling (pure assembler), plus the archive reader."""

import asyncio
import gzip
import json
from datetime import date

from neurosphere_api.replay import ArchiveTraceReader, TraceRecords
from neurosphere_api.replay.assemble import assemble_trace
from neurosphere_api.replay.reader import record_from_archive
from neurosphere_core.paging import PageRequest
from replay_support import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    FINANCE,
    TRACE,
    sid,
    span,
)


def build(*records):  # type: ignore[no-untyped-def]
    detail = assemble_trace(TraceRecords(spans=tuple(records)), FINANCE, TRACE)
    assert detail is not None
    return detail


def test_tree_timings_errors_and_tools() -> None:
    detail = build(
        span(1, None, duration_ms=500),
        span(2, 1, offset_ms=10, kind="tool_call", outcome="error", duration_ms=40),
        span(3, 1, offset_ms=20, kind="model_call", duration_ms=None),
    )
    by_id = {s.span_id: s for s in detail.spans}
    assert by_id[sid(1)].ended_at == "2027-01-15T08:00:00.500Z"
    assert by_id[sid(2)].kind == "tool" and by_id[sid(2)].status == "error"
    tool = by_id[sid(2)].tool
    assert tool is not None and tool.outcome == "error"
    assert by_id[sid(2)].error == "error"
    assert by_id[sid(3)].duration_ms is None and by_id[sid(3)].ended_at is None  # not 0
    assert detail.gaps == () and detail.completeness.state == "complete"


def test_missing_parent_gap() -> None:
    detail = build(span(1, None), span(2, 9, offset_ms=5))
    assert [(g.reason, g.parent_span_id, g.span_id) for g in detail.gaps] == [
        ("missing_parent", sid(9), sid(2))
    ]
    assert detail.completeness.state == "partial"


def test_sampling_labels_and_sampled_out_gap() -> None:
    detail = build(
        span(1, None, rate=1.0),
        span(2, 7, offset_ms=5, rate=0.25, method="head", reason="head_sampled"),
    )
    assert detail.sampling.rate == 0.25 and detail.sampling.reason == "head_sampled"
    spans = {s.span_id: s for s in detail.spans}
    assert spans[sid(2)].sampled and not spans[sid(1)].sampled
    assert detail.gaps[0].reason == "sampled_out"
    assert detail.completeness.state == "partial"


def test_sampling_unknown_is_none_not_one() -> None:
    assert build(span(1, None)).sampling.rate is None


def test_late_spans_by_flag_parent_order_and_arrival() -> None:
    detail = build(
        span(1, None, duration_ms=1000),
        span(2, 1, offset_ms=100, late=True),
        span(3, 1, offset_ms=-50),  # starts before its parent
        span(4, 1, offset_ms=200, ingested_after_s=900),  # long after completion
        span(5, 1, offset_ms=300),
    )
    spans = {s.span_id: s for s in detail.spans}
    assert spans[sid(2)].late and spans[sid(3)].late and spans[sid(4)].late
    assert not spans[sid(5)].late and not spans[sid(1)].late
    assert detail.completeness.late_count == 3
    assert all(spans[sid(n)].late_reason for n in (2, 3, 4))


def test_late_orphan_is_late_arrival_gap() -> None:
    detail = build(span(1, None), span(2, 8, offset_ms=5, late=True))
    assert detail.gaps[0].reason == "late_arrival"


def test_cycle_is_an_unknown_gap_not_a_hang() -> None:
    detail = build(span(1, 2), span(2, 1, offset_ms=1))
    assert {g.reason for g in detail.gaps} == {"unknown"}


def test_duplicate_span_ids_collapse() -> None:
    detail = build(span(1, None), span(1, None))
    assert len(detail.spans) == 1


def test_no_body_fields_in_default_serialization() -> None:
    from neurosphere_core.payload import find_body_fields

    detail = build(span(1, None, pointer="p", redaction="redacted"))
    assert find_body_fields(detail.model_dump(mode="json")) == []


def _blob(doc: dict[str, object]) -> bytes:
    return gzip.compress(json.dumps(doc).encode("utf-8"), mtime=0)


def _doc(span_n: int, parent: int | None, *, kind: str = "telemetry") -> dict[str, object]:
    return {
        "message": {"kind": kind, "customer_id": CUSTOMER},
        "contract": {
            "trace_id": TRACE,
            "span_id": sid(span_n),
            "parent_span_id": None if parent is None else sid(parent),
            "domain_id": FINANCE,
            "span_kind": "tool_call",
            "outcome": "success",
            "duration_ms": 12,
            "sampling": {"rate": 0.5, "method": "head", "reason": "x"},
        },
        "event_time": "2027-01-15T08:00:00+00:00",
        "ingestion_time": "2027-01-15T08:00:01+00:00",
        "late": False,
    }


class FakeContainer:
    def __init__(self, blobs: dict[str, bytes]) -> None:
        self.blobs = blobs

    async def list_blobs(self, name_starts_with: str | None = None, **kw: object):  # type: ignore[no-untyped-def]
        for name in sorted(self.blobs):
            if name_starts_with is None or name.startswith(name_starts_with):
                yield type("B", (), {"name": name})()

    async def download_blob(self, blob: str, **kw: object):  # type: ignore[no-untyped-def]
        data = self.blobs[blob]

        class Stream:
            async def readall(self) -> bytes:
                return data

        return Stream()


def test_archive_reader_reads_the_worker_layout() -> None:
    prefix = f"{CUSTOMER}/{FINANCE}/2027/01/15/"
    blobs = {
        f"{prefix}{'1' * 64}.json.gz": _blob(_doc(1, None)),
        f"{prefix}{'2' * 64}.json.gz": _blob(_doc(2, 1)),
        f"{prefix}{'3' * 64}.json.gz": _blob(_doc(3, 1, kind="cost")),
        f"{prefix}manifest.json": b"{}",
        f"{prefix}{'4' * 64}.json.gz": b"not gzip",
        f"fabrikam/{FINANCE}/2027/01/15/{'5' * 64}.json.gz": _blob(_doc(5, None)),
    }
    reader = ArchiveTraceReader(
        FakeContainer(blobs), lookback_days=1, today=lambda: date(2027, 1, 15)
    )
    got = asyncio.run(reader.get_trace(CUSTOMER, FINANCE, TRACE))
    assert sorted(r.span_id for r in got.spans) == [sid(1), sid(2)]
    page = asyncio.run(reader.list_traces(CUSTOMER, FINANCE, PageRequest()))
    assert [t.span_count for t in page.items] == [2]
    assert asyncio.run(reader.get_trace(CUSTOMER, "../x", TRACE)).spans == ()


def test_archive_scan_bound_marks_truncated() -> None:
    prefix = f"{CUSTOMER}/{FINANCE}/2027/01/15/"
    blobs = {f"{prefix}{n:064x}.json.gz": _blob(_doc(n, None)) for n in range(1, 4)}
    reader = ArchiveTraceReader(
        FakeContainer(blobs), lookback_days=1, max_blobs=2, today=lambda: date(2027, 1, 15)
    )
    got = asyncio.run(reader.get_trace(CUSTOMER, FINANCE, TRACE))
    assert got.truncated
    detail = assemble_trace(got, FINANCE, TRACE)
    assert detail is not None and detail.completeness.truncated
    assert detail.completeness.state == "partial"


def test_record_from_archive_rejects_malformed() -> None:
    assert record_from_archive({"message": {}}) is None
    assert record_from_archive("x") is None
