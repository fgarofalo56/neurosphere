"""Gateway, application and billing observations of ONE request become ONE ledger entry (C11, C12).

Three producer registrations (one observation_kind each) push through the real edge to the hub;
the real consumer folds them into Cosmos. The same run also carries an unpriced request so the
totals prove they report coverage instead of pretending to be complete.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from neurosphere_core.cloud import Settings
from neurosphere_core.ledger import LedgerEntry, TimeWindow
from neurosphere_core.ledger.cosmos import CosmosLedgerStore
from neurosphere_core.ledger.service import StoreLedgerReader

from .support import (
    Pipeline,
    Producer,
    cloudevent,
    edge_client,
    push_cloudevents,
    unique_customer,
)

pytestmark = pytest.mark.integration

EVENT_TIME = "2026-10-01T12:00:00.000Z"


def cost_doc(
    customer: str, source: str, observation: str, suffix: str, **fields: object
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema_version": "1.0.0",
        "cost_id": f"cost-{observation}-{suffix}",
        "customer_id": customer,
        "source_id": source,
        "cloud": "commercial",
        "currency": "USD",
        "dedupe_key": f"{customer}/{suffix}",
        "observation_source": observation,
        "recorded_at": "2026-10-01T12:00:05.000Z",
        "usage_start": EVENT_TIME,
        "usage_end": "2026-10-01T12:00:03.000Z",
        "provider": "azure_openai",
        "model": "synthetic-model",
    }
    doc.update(fields)
    return doc


async def test_three_observations_of_one_request_make_one_entry(tmp_path: Path) -> None:
    customer = unique_customer("dc")
    request_id = f"req-{customer}-a"
    unpriced_id = f"req-{customer}-b"
    gw = Producer("p-gw", customer, "commercial", {"dc-gw": "gateway"})
    app = Producer("p-app", customer, "commercial", {"dc-app": "application"})
    bill = Producer("p-bill", customer, "commercial", {"dc-bill": "billing"})
    settings = Settings(env="local")

    estimated = {
        "kind": "estimated",
        "price_version": "synthetic-prices-v1",
        "price_effective_date": "2026-10-01",
    }
    invoiced = {
        "kind": "invoiced",
        "invoice_id": f"inv-{customer}",
        "billing_period": {"start_date": "2026-10-01", "end_date": "2026-10-31"},
    }
    unpriced_call = {
        "schema_version": "1.0.0",
        "event_id": f"evt-{customer}-b",
        "event_time": EVENT_TIME,
        "cloud": "commercial",
        "customer_id": customer,
        "source_id": "dc-app",
        "span_kind": "model_call",
        "outcome": "success",
        "request_id": unpriced_id,
        "provider": "azure_openai",
        "model": "synthetic-model",
        "token_breakdown": {"input": 100, "output": 20},
    }

    async with Pipeline.open(settings) as pipe:
        async with edge_client(settings, [gw, app, bill], tmp_path) as client:
            sent = [
                await push_cloudevents(
                    client,
                    gw,
                    [
                        cloudevent(
                            "cost",
                            cost_doc(
                                customer, "dc-gw", "gateway", "a", amount="0.000700", **estimated
                            ),
                            request_id=request_id,
                        )
                    ],
                ),
                await push_cloudevents(
                    client,
                    app,
                    [
                        cloudevent(
                            "cost",
                            cost_doc(
                                customer,
                                "dc-app",
                                "application",
                                "a",
                                amount="0.000604",
                                **estimated,
                            ),
                            request_id=request_id,
                        )
                    ],
                ),
                await push_cloudevents(
                    client,
                    bill,
                    [
                        cloudevent(
                            "cost",
                            cost_doc(
                                customer, "dc-bill", "billing", "a", amount="0.000840", **invoiced
                            ),
                            request_id=request_id,
                        )
                    ],
                ),
                await push_cloudevents(client, app, [cloudevent("telemetry", unpriced_call)]),
            ]
        assert [s.accepted for s in sent] == [1, 1, 1, 1]

        consumer = await pipe.consume(expect_processed=4)
        assert (consumer.accepted, consumer.duplicates, sum(consumer.quarantined.values())) == (
            4,
            0,
            0,
        )

        store = CosmosLedgerStore(pipe.database.get_container_client(pipe.ledger.ledger_container))
        entry_docs = [
            d
            for d in await pipe.cosmos_docs(pipe.ledger.ledger_container, customer)
            if d["doc_type"] == "entry"
        ]
        # Two requests, two entries: the three observations of request A did not make three.
        assert len(entry_docs) == 2

        found = await store.read_entry(
            customer, next(d["id"] for d in entry_docs if d["request_id"] == request_id)
        )
        assert found is not None
        entry: LedgerEntry = found.entry
        assert sorted(o.observation_kind for o in entry.observations) == [
            "application",
            "billing",
            "gateway",
        ]
        assert len({o.doc_id for o in entry.observations}) == 3  # three distinct refs
        # Invoiced is authoritative; estimated and invoiced stay distinct and never substitute.
        assert entry.authoritative_kind == "invoiced"
        assert entry.authoritative_source == "billing"
        assert entry.authoritative_amount == Decimal("0.000840")
        assert entry.invoiced_amount == Decimal("0.000840")
        assert entry.estimated_amount == Decimal("0.000700")  # gateway-metered beats application
        assert entry.estimated_amount != entry.invoiced_amount

        # The unpriced request: the price table is empty, so honestly price_unresolved, no amount.
        other = next(d for d in entry_docs if d["request_id"] == unpriced_id)
        assert other["price_unresolved"] is True
        assert other["authoritative_amount"] is None
        assert other["estimated_amount"] is None

        reader = StoreLedgerReader(store)
        window = TimeWindow(
            datetime.now(UTC) - timedelta(days=3650), datetime.now(UTC) + timedelta(days=1)
        )
        totals = await reader.totals(customer, window)
        usd = totals["USD"]
        assert usd.amount == Decimal("0.000840")  # only the known entry is summed
        assert usd.entry_count == 2
        assert usd.known_count == 1
        assert usd.unresolved_count == 1
        assert usd.coverage == pytest.approx(0.5)
        assert usd.complete is False

        # Outbox: event entries for all four observations, ledger changes for the entries.
        outbox = await pipe.cosmos_docs(pipe.ledger.outbox_container, customer)
        assert sum(1 for o in outbox if o["kind"] == "event") == 4
        assert sum(1 for o in outbox if o["kind"] == "ledger_change") >= 2
