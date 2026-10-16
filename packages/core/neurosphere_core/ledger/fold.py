"""Double-count resolver: fold ALL observations of one request into one ``LedgerEntry``.

Documented rules (PRP-07 C11, C12):

* Precedence rank: ``0`` invoiced (any observation whose kind is ``invoiced``, in practice billing)
  > ``1`` gateway-metered estimate > ``2`` application-estimated > ``3`` any other estimate.
* Observations of the SAME rank sum (several ``model_call`` spans of one request are separate
  spend). If any of them is unknown (``amount is None``) or currencies differ, the group is unknown
  (``None``) and reported as such; it is never treated as 0.
* ``authoritative_amount`` is the amount of the best-ranked group whose amount is KNOWN.
  ``authoritative_source`` names that group. If no group is known, ``authoritative_amount`` is
  ``None`` and the source is the best-ranked group present. Lower-ranked groups stay in
  ``sources`` / ``observations`` as evidence and are never added to the authoritative amount.
* ``estimated_amount`` and ``invoiced_amount`` are separate fields: the best known estimated
  group and the invoiced group. They are never summed and neither substitutes for the other.
* Retries, allocation (PTU / reservation / seat / compute) and token counts are reported from the
  authoritative group as SEPARATE fields. They describe the amount; they are not added to it.
* The result depends only on the SET of observations (keyed by ``doc_id``), so any arrival order
  and any redelivery yield the identical entry.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date
from decimal import Decimal

from neurosphere_core.ledger.models import (
    AllocationParts,
    GroupSummary,
    LedgerEntry,
    Observation,
    TokenCounts,
    canonical_json,
    entry_id,
    quantize,
)

_RANK_OTHER_ESTIMATE = 3


def rank_of(obs: Observation) -> int:
    if obs.kind == "invoiced":
        return 0
    if obs.observation_kind == "gateway":
        return 1
    if obs.observation_kind == "application":
        return 2
    return _RANK_OTHER_ESTIMATE


def dedupe_by_doc_id(observations: Iterable[Observation]) -> list[Observation]:
    """Keyed by ``doc_id`` so redelivery never adds twice. A differing duplicate (should not
    happen) resolves deterministically to the smallest canonical form."""
    chosen: dict[str, tuple[str, Observation]] = {}
    for obs in observations:
        form = canonical_json(obs.model_dump(mode="json"))
        current = chosen.get(obs.doc_id)
        if current is None or form < current[0]:
            chosen[obs.doc_id] = (form, obs)
    return [chosen[key][1] for key in sorted(chosen)]


def _sum_all(values: list[Decimal | None]) -> Decimal | None:
    if not values or any(v is None for v in values):
        return None
    return quantize(sum((v for v in values if v is not None), Decimal(0)))


def _sum_int(values: list[int | None]) -> int | None:
    if not values or any(v is None for v in values):
        return None
    return sum(v for v in values if v is not None)


def _summarize(rank: int, group: list[Observation]) -> GroupSummary:
    currencies = {o.currency for o in group if o.amount is not None}
    conflict = len(currencies) > 1
    known = all(o.amount is not None for o in group)
    amount = _sum_all([o.amount for o in group]) if known and not conflict else None
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    source = "billing" if any(o.observation_kind == "billing" for o in group) else None
    return GroupSummary(
        rank=rank,
        source=source or group[0].observation_kind,
        kind=group[0].kind,
        amount=amount,
        currency=currency,
        observation_count=len(group),
        unknown_count=sum(1 for o in group if o.amount is None and not o.price_unresolved),
        unresolved_count=sum(1 for o in group if o.price_unresolved),
        currency_conflict=conflict,
    )


def _sum_parts(
    group: list[Observation], pick: Callable[[AllocationParts], Decimal | None]
) -> Decimal | None:
    values: list[Decimal | None] = []
    for obs in group:
        if obs.allocation is None:
            return None
        values.append(pick(obs.allocation))
    return _sum_all(values)


def _allocation(group: list[Observation]) -> AllocationParts | None:
    if all(o.allocation is None for o in group):
        return None
    return AllocationParts(
        compute=_sum_parts(group, lambda a: a.compute),
        ptu=_sum_parts(group, lambda a: a.ptu),
        reservation=_sum_parts(group, lambda a: a.reservation),
        license_seat=_sum_parts(group, lambda a: a.license_seat),
    )


def _tokens(group: list[Observation]) -> TokenCounts | None:
    if all(o.token_breakdown is None for o in group):
        return None

    def field(name: str) -> int | None:
        values: list[int | None] = []
        for obs in group:
            values.append(
                None if obs.token_breakdown is None else getattr(obs.token_breakdown, name)
            )
        return _sum_int(values)

    return TokenCounts(
        input=field("input"),
        output=field("output"),
        cached=field("cached"),
        reasoning=field("reasoning"),
    )


def _first(values: Iterable[str | None]) -> str | None:
    return next((v for v in values if v is not None), None)


def fold_entry(
    customer_id: str,
    request_id: str,
    cost_category: str,
    observations: Iterable[Observation],
) -> LedgerEntry:
    obs_list = dedupe_by_doc_id(observations)
    if not obs_list:
        raise ValueError("an entry needs at least one observation")
    by_rank: dict[int, list[Observation]] = {}
    for obs in sorted(obs_list, key=lambda o: (rank_of(o), o.doc_id)):
        by_rank.setdefault(rank_of(obs), []).append(obs)
    groups = [_summarize(rank, by_rank[rank]) for rank in sorted(by_rank)]

    estimated = [g for g in groups if g.kind == "estimated"]
    invoiced = [g for g in groups if g.kind == "invoiced"]
    est = next((g for g in estimated if g.amount is not None), None)
    inv = next((g for g in invoiced if g.amount is not None), None)
    auth = next((g for g in groups if g.amount is not None), None)
    auth_group = auth or groups[0]
    members = by_rank[auth_group.rank]
    # Evidence order for descriptive attributes: best rank first, then doc_id.
    ordered = [o for g in groups for o in by_rank[g.rank]]

    periods = [o.period_end for o in obs_list if o.period_end is not None]
    period_end: date | None = max(periods) if periods else None
    versions = sorted({o.price_version_id for o in obs_list if o.price_version_id is not None})
    retry_amount = _sum_all([o.retry_amount for o in members])

    return LedgerEntry(
        id=entry_id(customer_id, request_id, cost_category),
        customer_id=customer_id,
        request_id=request_id,
        cost_category=cost_category,
        cloud=ordered[0].cloud,
        source_id=ordered[0].source_id,
        domain_id=_first(o.domain_id for o in ordered),
        provider=_first(o.provider for o in ordered),
        model=_first(o.model for o in ordered),
        model_version=_first(o.model_version for o in ordered),
        observations=obs_list,
        sources=groups,
        estimated_amount=est.amount if est else None,
        estimated_currency=est.currency if est else None,
        invoiced_amount=inv.amount if inv else None,
        invoiced_currency=inv.currency if inv else None,
        authoritative_amount=auth.amount if auth else None,
        authoritative_currency=auth.currency if auth else None,
        authoritative_source=auth_group.source,
        authoritative_kind=auth_group.kind,
        price_version_ids=versions,
        price_unresolved=any(o.price_unresolved for o in obs_list),
        currency_conflict=any(g.currency_conflict for g in groups),
        occurred_at=min(o.observed_at for o in obs_list),
        observed_at=max(o.observed_at for o in obs_list),
        period_end=period_end,
        retry_count=_sum_int([o.retry_count for o in members]),
        retry_amount=retry_amount,
        allocation=_allocation(members),
        token_breakdown=_tokens(members),
    ).with_hash()
