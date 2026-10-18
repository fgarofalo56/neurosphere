"""Shared co-usage candidate job, built on the standard aggregation path (PRP-11 clarification).

Entities (models or providers) that are both used in the same domain are a co-usage
candidate. The job asks the adapter's own ``aggregate`` for events grouped by (domain, entity),
so scope, budget and tolerance rules are the ones every aggregate obeys, then pairs entities
per domain. Output is marked ``status="candidate"``; no rule is applied (PRP-15 owns rules).
The number of candidates is held to ``Budget.limit`` like any returned rows.
"""

from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from neurosphere_core.analytics.base.enforcement import breach_error
from neurosphere_core.analytics.base.models import (
    AggregateRequest,
    AggregateResult,
    Aggregation,
    CoUsageCandidate,
    CoUsageRequest,
    CoUsageResult,
    Dimension,
    Metric,
)

_ENTITY_DIMENSION = {"model": Dimension.MODEL, "provider": Dimension.PROVIDER}


def aggregate_request_for(request: CoUsageRequest) -> AggregateRequest:
    return AggregateRequest(
        metric=Metric.EVENTS,
        aggregation=Aggregation.COUNT,
        group_by=(Dimension.DOMAIN_ID, _ENTITY_DIMENSION[request.entity.value]),
        filters=request.filters,
        time_range=request.time_range,
        budget=request.budget,
    )


def candidates_from_counts(
    counts: AggregateResult, request: CoUsageRequest, *, backend: str
) -> CoUsageResult:
    per_domain: dict[str, dict[str, int]] = defaultdict(dict)
    for row in counts.rows:
        domain, entity = row.keys
        if domain is None or entity is None or row.value is None:
            continue  # unknown domain or entity never forms a candidate
        per_domain[domain][entity] = int(row.value)
    shared: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    for domain, entities in per_domain.items():
        for a, b in combinations(sorted(entities), 2):
            shared[(a, b)].append((domain, min(entities[a], entities[b])))
    candidates = sorted(
        (
            CoUsageCandidate(
                entity_a=a,
                entity_b=b,
                shared_domains=len(hits),
                support_events=sum(n for _, n in hits),
                domains=tuple(sorted(d for d, _ in hits)),
            )
            for (a, b), hits in shared.items()
            if len(hits) >= request.min_shared_domains
        ),
        key=lambda c: (-c.support_events, c.entity_a, c.entity_b),
    )
    if len(candidates) > request.budget.query.limit:
        raise breach_error("row_limit_exceeded")
    return CoUsageResult(
        backend=backend,
        cloud=counts.cloud,
        entity=request.entity,
        candidates=tuple(candidates),
        stats=counts.stats,
    )


__all__ = ["aggregate_request_for", "candidates_from_counts"]
