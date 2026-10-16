"""NormalizedEvent -> ledger input.

What is a cost observation:

* TELEMETRY: only ``span_kind == "model_call"`` events that carry a ``request_id``. Other span
  kinds (agent_run, delegation, tool_call, retry, ...) are NOT cost observations: an agent_run span
  and its child model_call spans describe the same spend, so counting both would double count.
  The amount is estimated from the versioned price table (see ``ledger.prices``).
* COST events (billing / gateway / application cost records): always an observation. With a
  ``request_id`` they attach to the per-request entry; without one they become a separate
  ``AllocationRecord`` (``vendor_period`` for billing, ``unattributed`` otherwise) and are never
  merged into a per-request entry.

``observation_kind`` is the value the edge stamped from the producer registration; telemetry with
no stamp is treated as ``application`` (instrumented by the app), cost records fall back to
their ``observation_source``. Telemetry stamped ``billing`` is not a cost observation.

Retries: a ``model_call`` with ``retry_attempt`` set is a retry (count 1, retry_amount = its
amount); one without it is an original attempt (count 0, amount 0 when the span amount is known).
Retry fields describe the amount; they are not added to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from neurosphere_contracts.cost.v1.cost_record import CostRecord
from neurosphere_contracts.telemetry.v1.telemetry_event import TelemetryEvent
from neurosphere_core.ledger import (
    DEFAULT_COST_CATEGORY,
    AllocationParts,
    AllocationRecord,
    Observation,
    PriceTable,
    TokenCounts,
    allocation_id,
)

from neurosphere_workers.ingestion.models import NormalizedEvent


@dataclass(frozen=True, slots=True)
class RequestObservation:
    customer_id: str
    request_id: str
    cost_category: str
    observation: Observation


def _tokens(contract: TelemetryEvent | CostRecord) -> TokenCounts | None:
    tb = contract.token_breakdown
    if tb is None:
        return None
    return TokenCounts(input=tb.input, output=tb.output, cached=tb.cached, reasoning=tb.reasoning)


def _label(value: object) -> str | None:
    return None if value is None else str(getattr(value, "root", value))


def _map_telemetry(
    event: NormalizedEvent, contract: TelemetryEvent, prices: PriceTable
) -> RequestObservation | None:
    request_id = event.message.request_id or _label(contract.request_id)
    if contract.span_kind != "model_call" or request_id is None:
        return None
    kind = event.message.observation_kind or "application"
    if kind == "billing":
        return None
    provider, model = _label(contract.provider), _label(contract.model)
    version = _label(contract.model_version)
    tokens = _tokens(contract)
    estimate = prices.estimate_cost(provider, model, version, tokens, event.event_time.date())
    amount = estimate.amount
    is_retry = contract.retry_attempt is not None
    retry_amount: Decimal | None = (
        amount if is_retry else (Decimal(0) if amount is not None else None)
    )
    obs = Observation(
        observation_kind=kind,
        doc_id=event.doc_id,
        kind="estimated",
        amount=amount,
        currency=estimate.currency if amount is not None else None,
        price_version_id=estimate.price_version_id,
        price_unresolved=not estimate.resolved,
        observed_at=event.event_time,
        cloud=contract.cloud,
        source_id=event.message.source_id,
        domain_id=_label(contract.domain_id),
        provider=provider,
        model=model,
        model_version=version,
        token_breakdown=tokens,
        retry_count=1 if is_retry else 0,
        retry_amount=retry_amount,
    )
    return RequestObservation(event.message.customer_id, request_id, DEFAULT_COST_CATEGORY, obs)


def _parts(contract: CostRecord) -> AllocationParts | None:
    alloc = contract.allocation
    if alloc is None:
        return None

    def one(value: object) -> Decimal | None:
        return None if value is None else Decimal(str(getattr(value, "root", value)))

    return AllocationParts(
        compute=one(alloc.compute),
        ptu=one(alloc.ptu),
        reservation=one(alloc.reservation),
        license_seat=one(alloc.license_seat),
    )


def _map_cost(
    event: NormalizedEvent, contract: CostRecord
) -> RequestObservation | AllocationRecord:
    kind = event.message.observation_kind or contract.observation_source
    amount = Decimal(contract.amount.root)
    period = contract.billing_period
    period_start = date.fromisoformat(period.start_date.root) if period else None
    period_end = date.fromisoformat(period.end_date.root) if period else None
    # An estimated cost with no price version cannot cite one: flag it, never invent one.
    unresolved = contract.kind == "estimated" and contract.price_version is None
    common = {
        "observation_kind": kind,
        "kind": contract.kind,
        "amount": None if unresolved else amount,
        "currency": None if unresolved else contract.currency,
        "price_version_id": contract.price_version,
        "observed_at": event.event_time,
        "cloud": contract.cloud,
        "source_id": event.message.source_id,
        "domain_id": _label(contract.domain_id),
        "retry_count": contract.retry_count,
        "retry_amount": None
        if contract.retry_amount is None
        else Decimal(contract.retry_amount.root),
        "allocation": _parts(contract),
    }
    request_id = event.message.request_id
    if request_id is not None:
        obs = Observation(
            doc_id=event.doc_id,
            price_unresolved=unresolved,
            period_end=period_end,
            provider=_label(contract.provider),
            model=_label(contract.model),
            model_version=_label(contract.model_version),
            token_breakdown=_tokens(contract),
            **common,  # type: ignore[arg-type]
        )
        return RequestObservation(event.message.customer_id, request_id, DEFAULT_COST_CATEGORY, obs)
    return AllocationRecord(
        id=allocation_id(event.message.customer_id, event.doc_id),
        customer_id=event.message.customer_id,
        granularity="vendor_period" if kind == "billing" else "unattributed",
        observation_doc_id=event.doc_id,
        provider=_label(contract.provider),
        billing_period_start=period_start,
        billing_period_end=period_end,
        period_end=period_end,
        **common,  # type: ignore[arg-type]
    ).with_hash()


def map_event(
    event: NormalizedEvent, prices: PriceTable
) -> RequestObservation | AllocationRecord | None:
    contract = event.contract
    if isinstance(contract, TelemetryEvent):
        return _map_telemetry(event, contract, prices)
    return _map_cost(event, contract)
