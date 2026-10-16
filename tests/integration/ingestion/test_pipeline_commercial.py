"""Commercial profile, full path on the compose emulators:

sandbox bundle -> edge (CloudEvents and OTLP) -> Event Hubs -> normalizer -> archive, ledger,
outbox, quarantine -> replay CLI. One expensive run per module (module-scoped fixture); each test
asserts one aspect of it. Expected counts come from the sandbox manifest plus an independent
oracle, never from the pipeline's own numbers.
"""

from __future__ import annotations

import gzip
import json
import re
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from neurosphere_core.cloud import Settings
from neurosphere_core.ledger import LedgerEntry
from neurosphere_core.ledger.cosmos import CosmosLedgerStore
from neurosphere_workers.ingestion.models import parse_timestamp

from .support import (
    Arrival,
    Doc,
    Pipeline,
    Producer,
    assert_no_bodies,
    cloudevent,
    cost_time,
    edge_client,
    expected_outcome,
    load_replay_cli,
    now_utc_z,
    otlp_model_call_spans,
    publish_raw,
    push_cloudevents,
    push_otlp_traces,
    read_hub,
    telemetry_time,
    unique_customer,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

SOURCE_GW, SOURCE_APP, SOURCE_BILL, SOURCE_OTLP = (
    "sandbox-gateway",
    "sandbox-application",
    "sandbox-billing",
    "otlp-src",
)
BYPASS_SOURCE = "it-bypass"
ARCHIVE_NAME = re.compile(
    r"^(?P<customer>[^/]+)/(?P<domain>[^/]+)/(?P<y>\d{4})/(?P<m>\d{2})/(?P<d>\d{2})/"
    r"(?P<doc>[0-9a-f]{64})\.json\.gz$"
)


def read_ndjson(path: Path) -> list[Doc]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def hub_message(
    customer: str, event_id: str, *, cloud: str = "commercial", data: Doc | None = None
) -> Doc:
    """A wire-format message as a holder of hub credentials could publish it (no edge)."""
    body = {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "event_time": "2026-10-01T12:00:00.000Z",
        "cloud": cloud,
        "customer_id": customer,
        "source_id": BYPASS_SOURCE,
        "span_kind": "model_call",
        "request_id": f"req-{event_id}",
        "provider": "azure_openai",
        "model": "synthetic-model",
        "token_breakdown": {"input": 10, "output": 5},
    }
    body.update(data or {})
    return {
        "wire_version": "1",
        "kind": "telemetry",
        "event_id": event_id,
        "cloud": cloud,
        "customer_id": customer,
        "source_id": BYPASS_SOURCE,
        "producer_id": "p-bypass",
        "received_at": now_utc_z(),
        "request_id": f"req-{event_id}",
        "observation_kind": "application",
        "dropped_field_counts": {},
        "data": body,
    }


@dataclass
class Run:
    customer: str
    canary: str
    pipe: Pipeline
    env_names: dict[str, str]
    sandbox_lines: int
    manifest: Doc
    bad_by_line: dict[int, Doc]
    telemetry_push: Any
    cost_pushes: list[Any]
    otlp_dropped: dict[str, int]
    expected_accepted: int
    dup_lines_accepted: int
    expected_duplicates: int
    expected_late: int
    expected_request_ids: set[str]
    edge_accepted: int
    bypass_ids: dict[str, str] = field(default_factory=dict)
    consumer: Any = None


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def run(
    sandbox_dir: Path, tmp_path_factory: pytest.TempPathFactory, fresh_hub: None
) -> AsyncIterator[Run]:
    customer = unique_customer("pc")
    canary = f"CANARY-{uuid.uuid4().hex}"
    settings = Settings(env="local")
    telemetry = read_ndjson(sandbox_dir / "telemetry.ndjson")
    costs = read_ndjson(sandbox_dir / "cost.ndjson")
    manifest = json.loads((sandbox_dir / "bad-event-manifest.json").read_text("utf-8"))
    bad_by_line = {e["line"]: e for e in read_ndjson(sandbox_dir / "bad-event-manifest.ndjson")}

    producers = [
        Producer("p-gw", customer, "commercial", {SOURCE_GW: "gateway"}),
        Producer("p-app", customer, "commercial", {SOURCE_APP: "application"}),
        Producer("p-bill", customer, "commercial", {SOURCE_BILL: "billing"}),
        Producer("p-otlp", customer, "commercial", {SOURCE_OTLP: "application"}),
    ]
    by_id = {p.producer_id: p for p in producers}
    names = Pipeline.names(uuid.uuid4().hex[:8])
    run_id = names["NS_ARCHIVE_CONTAINER"].rsplit("-", 1)[1]

    patch = pytest.MonkeyPatch()
    for key, value in names.items():
        patch.setenv(key, value)  # the replay CLI's default factories read these
    try:
        async with Pipeline.open(settings, run_id) as pipe:
            arrivals: list[Arrival] = []
            request_of_event: dict[str, str] = {}

            # -- sandbox telemetry through the CloudEvents edge (canaries ride along) ------------
            events: list[Doc] = []
            for i, line in enumerate(telemetry):
                doc = {**line, "customer_id": customer}
                if i % 25 == 3:
                    doc["prompt"] = canary
                    doc["response"] = {"text": canary}
                events.append(cloudevent("telemetry", doc))
                if doc.get("span_kind") == "model_call" and doc.get("request_id"):
                    request_of_event[doc["event_id"]] = doc["request_id"]

            expected_requests: set[str] = set()
            edge_dir = tmp_path_factory.mktemp("edge")
            async with edge_client(settings, producers, edge_dir, via_main=True) as edge:
                telemetry_push = await push_cloudevents(edge, by_id["p-gw"], events)
                dup_lines_accepted = 0
                for index in telemetry_push.accepted_indexes:
                    line = telemetry[index]
                    arrivals.append(Arrival(SOURCE_GW, line["event_id"], telemetry_time(line)))
                    if line.get("span_kind") == "model_call" and line.get("request_id"):
                        expected_requests.add(line["request_id"])
                    kind = bad_by_line.get(index + 1, {}).get("kind")
                    dup_lines_accepted += int(kind == "duplicate")

                # -- sandbox cost records: gateway / application / billing producers -------------
                cost_events: dict[str, list[Doc]] = {"p-gw": [], "p-app": [], "p-bill": []}
                cost_docs: dict[str, list[Doc]] = {"p-gw": [], "p-app": [], "p-bill": []}
                owner = {SOURCE_GW: "p-gw", SOURCE_APP: "p-app", SOURCE_BILL: "p-bill"}
                for line in costs:
                    doc = {**line, "customer_id": customer}
                    first = doc["event_ids"][0]
                    request_id = request_of_event.get(first, f"req-{first}")
                    key = owner[doc["source_id"]]
                    cost_events[key].append(cloudevent("cost", doc, request_id=request_id))
                    cost_docs[key].append(doc)
                # Re-deliver three identical gateway cost records: pure duplicates.
                cost_events["p-gw"] += cost_events["p-gw"][:3]
                cost_docs["p-gw"] += cost_docs["p-gw"][:3]

                cost_pushes = []
                for key in ("p-gw", "p-app", "p-bill"):
                    pushed = await push_cloudevents(edge, by_id[key], cost_events[key])
                    cost_pushes.append(pushed)
                    for index in pushed.accepted_indexes:
                        doc = cost_docs[key][index]
                        arrivals.append(Arrival(doc["source_id"], doc["cost_id"], cost_time(doc)))
                        expected_requests.add(cost_events[key][index]["nsrequestid"])

                # -- OTLP traces, delivered twice (the second delivery is all duplicates) --------
                otlp_doc, spans = otlp_model_call_spans(
                    5, request_prefix=f"req-otlp-{run_id}", canary=canary
                )
                otlp_results = [
                    await push_otlp_traces(edge, by_id["p-otlp"], otlp_doc) for _ in range(2)
                ]
                assert [r["accepted"] for r in otlp_results] == [5, 5]
                for delivery in range(2):
                    for i, span in enumerate(spans):
                        stamp = datetime.fromtimestamp(int(span["startTimeUnixNano"]) / 1e9, UTC)
                        event_id = f"{span['traceId']}:{span['spanId']}"
                        arrivals.append(Arrival(SOURCE_OTLP, event_id, stamp))
                        if delivery == 0:
                            expected_requests.add(f"req-otlp-{run_id}-{i}")
                otlp_dropped = Counter()
                for result in otlp_results:
                    otlp_dropped.update(result["dropped_fields"])

            edge_accepted = len(arrivals)

            # -- messages that bypass the edge: one per quarantine reason ----------------------
            replay_id = f"evt-{customer}-replay"
            bypass = {
                "body_field_present": hub_message(
                    customer, replay_id, data={"prompt": canary, "response": canary}
                ),
                "cloud_mismatch": hub_message(
                    customer,
                    f"evt-{customer}-gov",
                    cloud="government",
                    data={"cloud": "government"},
                ),
                "invalid_schema": hub_message(customer, f"evt-{customer}-bad"),
                "unsupported_schema_version": hub_message(
                    customer, f"evt-{customer}-v2", data={"schema_version": "2.0.0"}
                ),
            }
            del bypass["invalid_schema"]["data"]["event_time"]
            raw = [(json.dumps(m).encode(), f"{customer}|{BYPASS_SOURCE}") for m in bypass.values()]
            raw.append((f"not json at all {canary}".encode(), f"{customer}|{BYPASS_SOURCE}"))
            raw.append((b"[" * 200 + b"]" * 200, f"{customer}|{BYPASS_SOURCE}"))
            await publish_raw(raw)

            accepted, duplicates, late = expected_outcome(arrivals)
            consumer = await pipe.consume(expect_processed=edge_accepted + len(raw))

            yield Run(
                customer=customer,
                canary=canary,
                pipe=pipe,
                env_names=names,
                sandbox_lines=len(telemetry),
                manifest=manifest,
                bad_by_line=bad_by_line,
                telemetry_push=telemetry_push,
                cost_pushes=cost_pushes,
                otlp_dropped=dict(otlp_dropped),
                expected_accepted=accepted,
                dup_lines_accepted=dup_lines_accepted,
                expected_duplicates=duplicates,
                expected_late=late,
                expected_request_ids=expected_requests,
                edge_accepted=edge_accepted,
                bypass_ids={"replay": replay_id},
                consumer=consumer,
            )
    finally:
        patch.undo()


# -- the edge ----------------------------------------------------------------------------------


async def test_edge_rejects_exactly_the_malformed_lines(run: Run) -> None:
    push = run.telemetry_push
    malformed = {
        line: entry for line, entry in run.bad_by_line.items() if entry["kind"] == "malformed"
    }
    assert len(malformed) == run.manifest["counts"]["malformed"] > 0
    rejected_lines = {i + 1 for i in push.rejected_indexes}
    # The edge stamps ``cloud`` from the producer registration, so a line whose only defect is a
    # missing cloud is repaired rather than rejected; every other defect is rejected.
    repaired = {line for line, e in malformed.items() if e["mutation"] == "missing_required_field"}
    assert rejected_lines == set(malformed) - repaired
    assert push.sent == run.sandbox_lines
    assert push.statuses[202] > 0


async def test_edge_drops_prompt_and_response_and_reports_counts(run: Run) -> None:
    assert run.telemetry_push.dropped_fields["prompt"] > 0
    assert run.telemetry_push.dropped_fields["response"] > 0
    # OTLP: gen_ai.prompt / gen_ai.completion attribute items on every span, delivered twice.
    assert run.otlp_dropped["gen_ai.prompt"] == 10
    assert run.otlp_dropped["gen_ai.completion"] == 10


# -- the normalizer ----------------------------------------------------------------------------


async def test_counts_stored_duplicated_quarantined_and_late(run: Run) -> None:
    consumer = run.consumer
    # 5 OTLP re-deliveries + 3 re-sent cost records + the sandbox's own duplicate lines.
    assert run.expected_duplicates == 5 + 3 + run.dup_lines_accepted
    assert consumer.accepted == run.expected_accepted
    assert consumer.duplicates == run.expected_duplicates
    assert consumer.late == run.expected_late
    assert run.expected_late > 0, "the fixture must exercise lateness"
    assert dict(consumer.quarantined) == {
        "body_field_present": 1,
        "cloud_mismatch": 1,
        "invalid_schema": 1,
        "unsupported_schema_version": 1,
        "invalid_wire": 1,
        "depth_exceeded": 1,
    }
    markers = await run.pipe.cosmos_docs(run.pipe.ingestion.markers_container, run.customer)
    assert len(markers) == run.expected_accepted


async def test_quarantine_records_carry_reason_and_no_payload_body(run: Run) -> None:
    records = await run.pipe.quarantine_records()
    assert Counter(r["reason"] for r in records) == {
        "body_field_present": 1,
        "cloud_mismatch": 1,
        "invalid_schema": 1,
        "unsupported_schema_version": 1,
        "invalid_wire": 1,
        "depth_exceeded": 1,
    }
    unparseable = [r for r in records if r["reason"] in {"invalid_wire", "depth_exceeded"}]
    assert all(r["payload"] is None and r["payload_sha256"] for r in unparseable)


# -- archive -----------------------------------------------------------------------------------


async def test_archive_blobs_are_partitioned_by_day_and_domain(run: Run) -> None:
    records = await run.pipe.archive_records(run.customer)
    assert len(records) == run.expected_accepted
    domains = set()
    for name, record in records.items():
        match = ARCHIVE_NAME.match(name)
        assert match, name
        assert match["customer"] == run.customer
        day = parse_timestamp(record["event_time"]).date().isoformat()
        assert f"{match['y']}-{match['m']}-{match['d']}" == day
        domain = record["contract"].get("domain_id")
        assert match["domain"] == (domain if domain else "_none")
        domains.add(match["domain"])
    assert len(domains) >= 2, "sandbox spans several domains plus the domain-less OTLP events"
    assert sum(1 for r in records.values() if r["late"]) == run.expected_late


# -- ledger and outbox -------------------------------------------------------------------------


async def test_ledger_and_outbox_entries_exist(run: Run) -> None:
    pipe = run.pipe
    ledger_docs = await pipe.cosmos_docs(pipe.ledger.ledger_container, run.customer)
    entries = [d for d in ledger_docs if d["doc_type"] == "entry"]
    assert {e["request_id"] for e in entries} == run.expected_request_ids
    assert len(entries) == len(run.expected_request_ids)
    outbox = await pipe.cosmos_docs(pipe.ledger.outbox_container, run.customer)
    assert sum(1 for o in outbox if o["kind"] == "event") == run.expected_accepted
    assert sum(1 for o in outbox if o["kind"] == "ledger_change") >= len(entries)
    # Telemetry model calls carry no resolvable price (empty price table): honestly unresolved.
    assert any(e["price_unresolved"] for e in entries)


# -- redaction, everywhere ---------------------------------------------------------------------


async def test_no_prompt_or_response_in_anything_written(run: Run) -> None:
    pipe = run.pipe
    archive_raw = await pipe.blobs(pipe.archive_container)
    archive_text = [
        gzip.decompress(data) for name, data in archive_raw.items() if name.endswith(".gz")
    ]
    archive_docs = [json.loads(t) for t in archive_text]
    quarantine_raw = await pipe.blobs(pipe.quarantine_container)
    quarantine_docs = [json.loads(b) for n, b in quarantine_raw.items() if n.startswith("records/")]
    cosmos = await pipe.all_cosmos_docs()
    cosmos_docs = [doc for docs in cosmos.values() for doc in docs]
    hub = await read_hub(
        lambda body: run.customer.encode() in body and b"p-bypass" not in body, quiet_seconds=8
    )

    scanned = {
        "archive": assert_no_bodies("archive", archive_docs, archive_text, run.canary),
        "quarantine": assert_no_bodies(
            "quarantine", quarantine_docs, list(quarantine_raw.values()), run.canary
        ),
        "cosmos": assert_no_bodies("cosmos", cosmos_docs, [], run.canary),
        "hub": assert_no_bodies("hub", [json.loads(m) for m in hub], hub, run.canary),
    }
    assert all(count > 0 for count in scanned.values()), scanned
    # Everything the edge published reached the hub clean (and was counted, so the scan is real).
    assert len(hub) == run.edge_accepted


# -- replay ------------------------------------------------------------------------------------


async def test_replay_once_then_already_replayed_without_a_second_ledger_effect(run: Run) -> None:
    import asyncio

    pipe = run.pipe
    cli = load_replay_cli()
    records = await pipe.quarantine_records()
    target = next(r for r in records if r["reason"] == "body_field_present")
    assert target["event_id"] == run.bypass_ids["replay"]
    request_id = f"req-{run.bypass_ids['replay']}"

    async def snapshot() -> dict[str, Any]:
        ledger = await pipe.cosmos_docs(pipe.ledger.ledger_container, run.customer)
        outbox = await pipe.cosmos_docs(pipe.ledger.outbox_container, run.customer)
        markers = await pipe.cosmos_docs(pipe.ingestion.markers_container, run.customer)
        archive = await pipe.archive_records(run.customer)
        return {
            "entries": {d["request_id"]: d for d in ledger if d["doc_type"] == "entry"},
            "outbox": len(outbox),
            "markers": len(markers),
            "archive": len(archive),
        }

    before = await snapshot()
    assert request_id not in before["entries"]

    def invoke() -> tuple[int, str, str]:
        out, err = StringIO(), StringIO()
        code = cli.main(["replay", "--id", target["doc_id"]], out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    # The CLI runs its own event loop, so it gets its own thread; its default factories read the
    # same unique container names from the environment (the production wiring path).
    code, out, err = await asyncio.to_thread(invoke)
    assert code == 0, (out, err)
    assert "replayed (accepted)" in out
    after_first = await snapshot()
    assert after_first["markers"] == before["markers"] + 1
    assert after_first["archive"] == before["archive"] + 1
    assert after_first["outbox"] > before["outbox"]
    entry = after_first["entries"][request_id]
    assert len(entry["observations"]) == 1

    code, out, err = await asyncio.to_thread(invoke)
    assert code == 0, (out, err)
    assert "already replayed" in out
    after_second = await snapshot()
    assert after_second["markers"] == after_first["markers"]
    assert after_second["archive"] == after_first["archive"]
    assert after_second["outbox"] == after_first["outbox"]
    assert after_second["entries"][request_id]["_etag"] == entry["_etag"]  # entry never rewritten
    assert len(after_second["entries"]) == len(after_first["entries"])

    store = CosmosLedgerStore(pipe.database.get_container_client(pipe.ledger.ledger_container))
    found = await store.read_entry(run.customer, entry["id"])
    assert found is not None
    assert isinstance(found.entry, LedgerEntry)
    assert len(found.entry.observations) == 1
