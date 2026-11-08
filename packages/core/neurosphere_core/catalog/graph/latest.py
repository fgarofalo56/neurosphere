"""Presented lineage with the newest observation, only where it matters (PRP-10 item 10).

``rules.present_edge`` takes an optional ``latest_observation``: when no lock is active it
supplies confidence and validity, so an edge whose lock has EXPIRED stops showing the stale
pre-lock value. Reading the newest observation costs one query, so it is done only for an edge
whose governing lock decision has expired -- never per edge by default.

``latest_observation`` is not on the ``CatalogRepository`` protocol (the raw view is Auditor
gated; this read returns only what the edge itself shows). A repository that does not provide
it is simply presented without it.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol, runtime_checkable

from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride

from neurosphere_core.catalog import rules
from neurosphere_core.catalog.protocol import CatalogEdge, EdgeObservation, PresentedEdge
from neurosphere_core.scope import IdentityScope

__all__ = ["LatestObservationReader", "has_expired_lock", "present_with_latest"]

_LOCK_BEARING = ("lock", "override", "unlock")


@runtime_checkable
class LatestObservationReader(Protocol):
    """Optional repository capability: the newest observation of an in-scope edge."""

    async def latest_observation(
        self, scope: IdentityScope, edge_id: str
    ) -> EdgeObservation | None: ...


def has_expired_lock(overrides: Iterable[EdgeOverride], now: datetime) -> bool:
    """True when the governing lock-bearing decision is a lock whose expiry has passed."""
    made = [
        o
        for o in overrides
        if o.decision in _LOCK_BEARING and rules.parse_timestamp(o.decided_at.root) <= now
    ]
    if not made:
        return False
    last = max(made, key=lambda o: (rules.parse_timestamp(o.decided_at.root), o.id))
    if last.decision == "unlock" or last.lock is None or not last.lock.locked:
        return False
    return last.lock.expiry is not None and rules.parse_timestamp(last.lock.expiry.root) <= now


def wants_latest(edge: CatalogEdge, overrides: Iterable[EdgeOverride], now: datetime) -> bool:
    mine = [o for o in overrides if o.edge_id == edge.id]
    return has_expired_lock(mine, now) and rules.active_lock(mine, now) is None


async def present_with_latest(
    repository: object,
    scope: IdentityScope,
    edge: CatalogEdge,
    overrides: Iterable[EdgeOverride],
    now: datetime,
) -> PresentedEdge:
    """``rules.present_edge`` plus a bounded newest-observation fetch for an expired lock."""
    held = tuple(overrides)
    latest: EdgeObservation | None = None
    if isinstance(repository, LatestObservationReader) and wants_latest(edge, held, now):
        latest = await repository.latest_observation(scope, edge.id)
    return rules.present_edge(edge, held, now, latest)
