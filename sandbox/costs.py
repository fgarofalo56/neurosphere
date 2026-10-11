"""CostRecord observations: gateway, application and billing views of the same spend.

All views of one model call share a ``dedupe_key`` so PRP-07 can exercise de-duplication.
Gateway and application views are ``estimated`` (cite the synthetic price version); the
billing view is ``invoiced`` (cites a billing period) and exists for a configured fraction of
calls. Money is a decimal string, never a float.
"""

from __future__ import annotations

import random
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from neurosphere_contracts.cost.v1 import cost_record

from sandbox.config import (
    CACHED_INPUT_FACTOR,
    PRICE_EFFECTIVE_DATE,
    PRICE_VERSION,
    SCHEMA_VERSION,
    ModelSpec,
)
from sandbox.ids import fmt_ts, fmt_ts_s, month_bounds
from sandbox.world import DAY_MS, World

Doc = dict[str, Any]
_QUANT = Decimal("0.000001")


def price(spec: ModelSpec, tin: int, tout: int, cached: int) -> Decimal:
    fresh = Decimal(max(tin - cached, 0))
    amount = (
        fresh * spec.price_in
        + Decimal(cached) * spec.price_in * CACHED_INPUT_FACTOR
        + Decimal(tout) * spec.price_out
    ) / Decimal(1000)
    return amount.quantize(_QUANT, rounding=ROUND_HALF_EVEN)


def _money(value: Decimal) -> str:
    return format(value.quantize(_QUANT, rounding=ROUND_HALF_EVEN), "f")


def _dump(doc: Doc) -> Doc:
    result: Doc = cost_record.CostRecord.model_validate(doc).model_dump(
        mode="json", exclude_none=True
    )
    return result


def cost_views(
    world: World,
    rng: random.Random,
    *,
    agent_idx: int,
    spec: ModelSpec,
    tokens: tuple[int, int, int],
    event_id: str,
    start_ms: int,
    end_ms: int,
    retry_count: int,
    retry_input_tokens: int,
) -> list[Doc]:
    tin, tout, cached = tokens
    agent = world.agents[agent_idx]
    retry_cost = price(spec, retry_input_tokens, 0, 0)
    amount = price(spec, tin, tout, cached) + retry_cost
    dedupe = f"{world.customer}/{event_id}"
    base: Doc = {
        "schema_version": SCHEMA_VERSION,
        "currency": "USD",
        "cloud": world.cloud,
        "customer_id": world.customer,
        "domain_id": world.domain_id(agent.domain),
        "canonical_agent_id": world.agent_id(agent_idx),
        "provider": spec.provider,
        "model": spec.model_name,
        "model_version": spec.model_version,
        "retry_count": retry_count,
        "retry_amount": _money(retry_cost),
        "event_ids": [event_id],
        "dedupe_key": dedupe,
        "usage_start": fmt_ts(start_ms),
        "usage_end": fmt_ts(end_ms),
    }
    gateway: Doc = {
        **base,
        "cost_id": f"cost-gw-{event_id}",
        "kind": "estimated",
        "amount": _money(amount),
        "allocation": {"compute": _money(amount)},
        "price_version": PRICE_VERSION,
        "price_effective_date": PRICE_EFFECTIVE_DATE,
        "source_id": "sandbox-gateway",
        "observation_source": "gateway",
        "token_breakdown": {"input": tin, "output": tout, "cached": cached},
        "recorded_at": fmt_ts(end_ms + 1000),
    }
    application: Doc = {
        **base,
        "cost_id": f"cost-app-{event_id}",
        "kind": "estimated",
        "amount": _money(amount),
        "allocation": {"compute": _money(amount)},
        "price_version": PRICE_VERSION,
        "price_effective_date": PRICE_EFFECTIVE_DATE,
        "source_id": "sandbox-application",
        "observation_source": "application",
        "token_breakdown": {"input": tin, "output": tout},  # app SDK does not report cache hits
        "recorded_at": fmt_ts(end_ms + 2000),
    }
    out = [_dump(gateway), _dump(application)]
    if rng.random() < world.cfg.profile.invoiced_fraction:
        first, last, yyyymm = month_bounds(end_ms)
        delta = Decimal(rng.randint(-100, 200)) / Decimal(10_000)  # -1.00% .. +2.00%
        billed = max(amount * (Decimal(1) + delta), Decimal(0))
        invoiced: Doc = {
            **base,
            "cost_id": f"cost-bill-{event_id}",
            "kind": "invoiced",
            "amount": _money(billed),
            "allocation": {"compute": _money(billed)},
            "billing_period": {"start_date": first, "end_date": last},
            "invoice_id": f"inv-{world.customer}-{yyyymm}",
            "source_id": "sandbox-billing",
            "observation_source": "billing",
            "recorded_at": fmt_ts_s(world.end_ms() + DAY_MS),
        }
        # An invoice reports spend, not tokens; keep the retry share within the billed amount.
        invoiced["retry_amount"] = _money(min(retry_cost, billed))
        out.append(_dump(invoiced))
    return out
