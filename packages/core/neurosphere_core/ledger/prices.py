"""Versioned price table and token-cost estimation (PRP-07 C13).

A ``PriceVersion`` is an immutable price sheet: ``price_version_id``, ``effective_date``, one
``currency`` and a ``source``, with rates per (provider, model[, model_version]) per token type,
in ``Decimal`` per 1M tokens. Resolution is by effective date: the newest version whose
``effective_date <= usage date`` AND that has a rate for the model wins. No such version means the
price is unresolved and the caller flags the observation ``price_unresolved``.

Estimation rules (``estimate_cost``):

* ``input`` is taken to INCLUDE ``cached`` (the common provider convention). Cached tokens are
  priced at the ``cached`` rate; only ``input - cached`` is priced at the input rate. Cached is
  never folded into input cost.
* ``input`` or ``output`` unknown -> amount ``None`` (never 0). ``cached`` unknown means "not
  reported": no tokens are priced at the cached rate.
* Cached tokens reported but the sheet has no cached rate, or ``cached > input`` -> ``None``.
* ``reasoning`` tokens are not added: providers bill them inside ``output``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

from neurosphere_core.ledger.models import Currency, Money, TokenCounts, quantize

_PER = Decimal(1_000_000)
_ZERO: Final = Decimal(0)


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Rate(_Frozen):
    """Decimal per 1M tokens. ``cached`` is None when the sheet has no cached price."""

    input: Money
    output: Money
    cached: Money | None = None


class ModelRate(_Frozen):
    provider: str
    model: str
    model_version: str | None = None  # None = applies to every version of the model
    rate: Rate


class PriceVersion(_Frozen):
    price_version_id: str = Field(min_length=1, max_length=128)
    effective_date: date
    currency: Currency
    source: str = Field(min_length=1)
    rates: list[ModelRate]

    @model_validator(mode="after")
    def _unique_rates(self) -> PriceVersion:
        keys = [(r.provider, r.model, r.model_version) for r in self.rates]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate rate key in price version")
        return self

    def rate_for(self, provider: str, model: str, model_version: str | None) -> Rate | None:
        """Exact (provider, model, version) first, then the version-less rate."""
        wildcard: Rate | None = None
        for item in self.rates:
            if item.provider != provider or item.model != model:
                continue
            if item.model_version is not None and item.model_version == model_version:
                return item.rate
            if item.model_version is None:
                wildcard = item.rate
        return wildcard


@dataclass(frozen=True, slots=True)
class ResolvedPrice:
    version: PriceVersion
    rate: Rate


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """``resolved`` False -> price_unresolved. ``amount`` None with ``resolved`` True -> unknown
    tokens. ``currency``/``price_version_id`` are set whenever ``resolved``."""

    resolved: bool
    amount: Decimal | None = None
    currency: str | None = None
    price_version_id: str | None = None


class PriceTable:
    def __init__(self, versions: list[PriceVersion]) -> None:
        ids = [v.price_version_id for v in versions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate price_version_id")
        # Newest first; id breaks ties deterministically.
        self._versions = sorted(versions, key=lambda v: (v.effective_date, v.price_version_id))
        self._versions.reverse()

    @property
    def versions(self) -> list[PriceVersion]:
        return list(self._versions)

    def resolve(
        self, provider: str | None, model: str | None, model_version: str | None, on: date
    ) -> ResolvedPrice | None:
        if provider is None or model is None:
            return None
        for version in self._versions:
            if version.effective_date > on:
                continue
            rate = version.rate_for(provider, model, model_version)
            if rate is not None:
                return ResolvedPrice(version, rate)
        return None

    def estimate_cost(
        self,
        provider: str | None,
        model: str | None,
        model_version: str | None,
        tokens: TokenCounts | None,
        on: date,
    ) -> CostEstimate:
        resolved = self.resolve(provider, model, model_version, on)
        if resolved is None:
            return CostEstimate(resolved=False)
        version = resolved.version
        amount = _price_tokens(resolved.rate, tokens)
        return CostEstimate(True, amount, version.currency, version.price_version_id)


def _price_tokens(rate: Rate, tokens: TokenCounts | None) -> Decimal | None:
    if tokens is None or tokens.input is None or tokens.output is None:
        return None
    cached = tokens.cached or 0
    if cached > tokens.input:
        return None
    if cached > 0 and rate.cached is None:
        return None
    total = (
        Decimal(tokens.input - cached) * rate.input + Decimal(tokens.output) * rate.output
    ) / _PER
    if cached > 0 and rate.cached is not None:
        total += Decimal(cached) * rate.cached / _PER
    return quantize(total)
