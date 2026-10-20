"""Evaluator token and cost budgets, enforced BEFORE each judge call (PRP-16 item 2).

``BudgetLedger`` holds a per-run limit and a per-domain limit (each: tokens and money, ``Decimal``).
Before a call the caller RESERVES the worst case (input estimate plus ``max_output_tokens``, priced
from the judge config). A reservation that does not fit either budget is denied and the run
stops; nothing is silently truncated. After the call the actual usage is settled and the unused
part of the reservation is released.

Invariant: ``consumed + open reservations`` never exceeds a limit at the moment a reservation is
granted, so a call whose worst case would exceed a budget is never made. The input estimate is one
token per UTF-8 byte of the serialized request (no tokenizer emits fewer bytes per token) plus a
configurable fixed prompt overhead, so the estimate is an upper bound in practice. Should a
provider still report more than was reserved, ``settle`` records it (``overruns``) rather than
hiding it.

Domain consumption persists for the ledger's lifetime (across runs); run consumption restarts at
``begin_run``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_UP, Decimal
from typing import Annotated, Final

from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.evaluation.judge import JudgeRequest
from neurosphere_core.evaluation.registry import JudgeConfig
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "DEFAULT_PROMPT_OVERHEAD_TOKENS",
    "BudgetDenial",
    "BudgetLedger",
    "BudgetLimits",
    "Reservation",
    "estimate_input_tokens",
    "price_call",
    "price_known",
]

DEFAULT_PROMPT_OVERHEAD_TOKENS: Final = 512
_QUANT: Final = Decimal("0.000000000001")  # 12 places, the contract's money precision
_ZERO: Final = Decimal(0)


class BudgetLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tokens: Annotated[int, Field(ge=0)]
    cost: Annotated[Decimal, Field(ge=0)]


@dataclass(frozen=True, slots=True)
class Reservation:
    token_id: int
    domain: str
    tokens: int
    cost: Decimal


@dataclass(frozen=True, slots=True)
class BudgetDenial:
    """A reservation that did not fit; ``code`` is e.g. ``run_tokens`` or ``domain_cost``."""

    scope: str
    resource: str
    domain: str

    @property
    def code(self) -> str:
        return f"{self.scope}_{self.resource}"


def estimate_input_tokens(
    request: JudgeRequest, overhead: int = DEFAULT_PROMPT_OVERHEAD_TOKENS
) -> int:
    """Upper-bound input tokens: one per UTF-8 byte of the serialized request, plus overhead."""
    body = json.dumps(
        request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return len(body.encode("utf-8")) + max(0, overhead)


def price_known(config: JudgeConfig) -> bool:
    """Whether the config's cost can be bounded. Programmatic scorers cost no tokens."""
    if config.judge_kind == "programmatic":
        return True
    return (
        config.input_price_per_1k_tokens is not None
        and config.output_price_per_1k_tokens is not None
        and config.price_version is not None
    )


def price_call(config: JudgeConfig, input_tokens: int, output_tokens: int) -> Decimal:
    """Money for a call; raises if the price is unknown (callers skip with ``price_unknown``)."""
    if config.judge_kind == "programmatic":
        return _ZERO
    if not price_known(config):
        raise InvalidSchemaError("judge config has no price", reason="price_unknown")
    in_price = Decimal(str(config.input_price_per_1k_tokens))
    out_price = Decimal(str(config.output_price_per_1k_tokens))
    total = (Decimal(input_tokens) * in_price + Decimal(output_tokens) * out_price) / Decimal(1000)
    return total.quantize(_QUANT, rounding=ROUND_UP)


class BudgetLedger:
    def __init__(
        self,
        *,
        run_limits: BudgetLimits,
        domain_limits: BudgetLimits,
        domain_overrides: Mapping[str, BudgetLimits] | None = None,
    ) -> None:
        self._run_limits = run_limits
        self._domain_limits = domain_limits
        self._overrides = dict(domain_overrides or {})
        self._run_tokens = 0
        self._run_cost = _ZERO
        self._domain_tokens: dict[str, int] = {}
        self._domain_cost: dict[str, Decimal] = {}
        self._open: dict[int, Reservation] = {}
        self._next_id = 1
        self.overruns = 0

    # --- configuration / state ----------------------------------------------------------------

    @property
    def run_limits(self) -> BudgetLimits:
        return self._run_limits

    def domain_limits(self, domain: str) -> BudgetLimits:
        return self._overrides.get(domain, self._domain_limits)

    @property
    def run_consumed(self) -> tuple[int, Decimal]:
        return self._run_tokens, self._run_cost

    def domain_consumed(self, domain: str) -> tuple[int, Decimal]:
        return self._domain_tokens.get(domain, 0), self._domain_cost.get(domain, _ZERO)

    @property
    def open_reservations(self) -> int:
        return len(self._open)

    def begin_run(self) -> None:
        """Restart the per-run counters; per-domain consumption carries over."""
        if self._open:
            raise InvalidSchemaError("reservations still open", reason="open_reservations")
        self._run_tokens = 0
        self._run_cost = _ZERO

    # --- reserve / settle / release -----------------------------------------------------------

    def _reserved(self, domain: str | None = None) -> tuple[int, Decimal]:
        held = [r for r in self._open.values() if domain is None or r.domain == domain]
        return sum(r.tokens for r in held), sum((r.cost for r in held), _ZERO)

    def reserve(self, domain: str, tokens: int, cost: Decimal) -> Reservation | BudgetDenial:
        """Grant the worst case or deny it; checks run tokens, run cost, domain tokens, cost."""
        run_res_t, run_res_c = self._reserved()
        if self._run_tokens + run_res_t + tokens > self._run_limits.tokens:
            return BudgetDenial("run", "tokens", domain)
        if self._run_cost + run_res_c + cost > self._run_limits.cost:
            return BudgetDenial("run", "cost", domain)
        limits = self.domain_limits(domain)
        dom_t, dom_c = self.domain_consumed(domain)
        dom_res_t, dom_res_c = self._reserved(domain)
        if dom_t + dom_res_t + tokens > limits.tokens:
            return BudgetDenial("domain", "tokens", domain)
        if dom_c + dom_res_c + cost > limits.cost:
            return BudgetDenial("domain", "cost", domain)
        reservation = Reservation(self._next_id, domain, tokens, cost)
        self._next_id += 1
        self._open[reservation.token_id] = reservation
        return reservation

    def _close(self, reservation: Reservation) -> None:
        if self._open.pop(reservation.token_id, None) is None:
            raise InvalidSchemaError("unknown or closed reservation", reason="bad_reservation")

    def settle(self, reservation: Reservation, tokens: int, cost: Decimal) -> None:
        """Record actual usage and release the rest of the reservation."""
        self._close(reservation)
        self._run_tokens += tokens
        self._run_cost += cost
        self._domain_tokens[reservation.domain] = (
            self._domain_tokens.get(reservation.domain, 0) + tokens
        )
        self._domain_cost[reservation.domain] = (
            self._domain_cost.get(reservation.domain, _ZERO) + cost
        )
        limits = self.domain_limits(reservation.domain)
        if (
            self._run_tokens > self._run_limits.tokens
            or self._run_cost > self._run_limits.cost
            or self._domain_tokens[reservation.domain] > limits.tokens
            or self._domain_cost[reservation.domain] > limits.cost
        ):
            self.overruns += 1

    def release(self, reservation: Reservation) -> None:
        """Drop a reservation without consuming (the call was never made)."""
        self._close(reservation)
