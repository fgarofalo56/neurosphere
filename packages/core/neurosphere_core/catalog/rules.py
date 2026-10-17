"""Pure curation and merge rules (PRP-10 clarification 8). No I/O, no clock reads.

The clock is always passed in (``now`` must be timezone-aware). Functions here never mutate
their inputs and never remove evidence.

Model:

* The STORED edge is the observed document. ``merge_observation`` is the only thing that
  changes it on inference: evidence and ``last_observed`` always accumulate; ``confidence``
  and ``validity`` follow the new inference unless an active lock holds them.
* STEWARD DECISIONS (``EdgeOverride``) are immutable and kept apart. ``present_edge`` folds
  them over the stored edge to compute presented lineage:

  - ``reject`` hides the edge (until a later ``accept``); the edge and its evidence remain.
  - ``accept`` shows it and marks it curated.
  - ``override`` / ``lock`` pin the presented state while the lock is unexpired; either
    may also set confidence and validity. ``unlock`` releases the pin.
  - An expired lock stops applying: the observed edge is presented again.

* ``evidence_ids`` and ``security_evidence_ids`` of a presented or merged edge are always
  the UNION of everything known. No decision removes evidence (the ``EdgeOverride`` schema
  has no field for it either).
* An inference that contradicts an active lock, or that re-observes a curated reject, never
  changes presented lineage and yields a ``ReviewItem`` for a steward (PRP-17 consumes it).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Literal

from neurosphere_contracts.catalog.v1 import common
from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride
from pydantic import BaseModel, ConfigDict

from neurosphere_core.catalog.protocol import CatalogEdge, EdgeObservation, PresentedEdge
from neurosphere_core.catalog.review_queue import ConflictReason, ReviewItem

CONFIDENCE_CONFLICT_DELTA = 0.25
"""An inference whose confidence differs from the presented value by at least this much
contradicts a lock (a differing ``valid_to`` also contradicts it)."""

_LOCK_DECISIONS = frozenset({"lock", "override", "unlock"})
_FRACTION = re.compile(r"\.(\d+)Z$")


# --------------------------------------------------------------------------- timestamps


def parse_timestamp(value: str) -> datetime:
    """Parse an RFC 3339 UTC timestamp (``...Z``, up to 9 fractional digits) to aware UTC."""

    def _trim(match: re.Match[str]) -> str:
        return "." + match.group(1)[:6].ljust(6, "0") + "Z"

    normalized = _FRACTION.sub(_trim, value)
    return datetime.fromisoformat(normalized.replace("Z", "+00:00")).astimezone(UTC)


def format_timestamp(value: datetime) -> str:
    """Format an aware datetime as an RFC 3339 UTC timestamp with microseconds."""
    return _require_aware(value).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _require_aware(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return now


# --------------------------------------------------------------------------- decisions


def _ordered(overrides: Iterable[EdgeOverride], now: datetime) -> list[EdgeOverride]:
    """Decisions already made at ``now`` in decision order (``decided_at`` then ``id``)."""
    _require_aware(now)
    made = [o for o in overrides if parse_timestamp(o.decided_at.root) <= now]
    return sorted(made, key=lambda o: (parse_timestamp(o.decided_at.root), o.id))


def _lock_chain(ordered: Sequence[EdgeOverride]) -> list[EdgeOverride]:
    """Lock-bearing decisions after the last ``unlock`` (``unlock`` itself included last)."""
    chain = [o for o in ordered if o.decision in _LOCK_DECISIONS]
    for index in range(len(chain) - 1, -1, -1):
        if chain[index].decision == "unlock":
            return chain[index:]
    return chain


def active_lock(overrides: Iterable[EdgeOverride], now: datetime) -> EdgeOverride | None:
    """The decision whose lock applies at ``now``, or None.

    ``overrides`` must belong to one edge (callers filter by ``edge_id``). The most recent
    lock-bearing decision (``lock``, ``override`` or ``unlock``) wins: an ``unlock`` clears
    the lock, a later ``lock`` replaces an earlier one. A lock with no expiry, or whose
    expiry is not strictly after ``now``, does not apply (an expired lock stops applying).
    """
    chain = _lock_chain(_ordered(overrides, now))
    if not chain:
        return None
    last = chain[-1]
    if last.decision == "unlock" or last.lock is None or not last.lock.locked:
        return None
    if last.lock.expiry is None or parse_timestamp(last.lock.expiry.root) <= now:
        return None
    return last


# --------------------------------------------------------------------------- union helpers


def _union(*groups: Iterable[str]) -> list[str]:
    """Order-preserving, de-duplicated union."""
    seen: dict[str, None] = {}
    for group in groups:
        for item in group:
            seen.setdefault(item)
    return list(seen)


def _roots(items: Iterable[common.EvidenceId]) -> list[str]:
    return [i.root for i in items]


def _wrap(items: Iterable[str]) -> list[common.EvidenceId]:
    return [common.EvidenceId(root=i) for i in items]


# --------------------------------------------------------------------------- presentation


def present_edge(
    observed: CatalogEdge, overrides: Iterable[EdgeOverride], now: datetime
) -> PresentedEdge:
    """Presented lineage for one edge at ``now``.

    Only decisions for ``observed.id`` that were made at or before ``now`` are considered.
    Evidence and security evidence are the union of the edge's and every decision's
    ``add_evidence_ids``; nothing removes them.
    """
    mine = [o for o in overrides if o.edge_id == observed.id]
    ordered = _ordered(mine, now)
    lock_decision = active_lock(ordered, now)

    confidence = float(observed.confidence)
    validity = observed.validity
    override_ids: list[str] = []

    if lock_decision is not None:
        for decision in _lock_chain(ordered):
            if decision.decision in ("override", "lock"):
                if decision.set_confidence is not None:
                    confidence = float(decision.set_confidence.root)
                if decision.set_validity is not None:
                    validity = decision.set_validity
            override_ids.append(decision.id)

    visibility = [o for o in ordered if o.decision in ("accept", "reject")]
    latest_visibility = visibility[-1] if visibility else None
    hidden = latest_visibility is not None and latest_visibility.decision == "reject"
    if latest_visibility is not None:
        override_ids.append(latest_visibility.id)

    curation = _curation(latest_visibility, lock_decision, ordered)
    pinned = lock_decision is not None
    status: Literal["asserted", "inferred", "curated"] = (
        "curated" if (curation is not None or pinned) else observed.status.root
    )

    evidence = _union(
        _roots(observed.evidence_ids),
        *(_roots(o.add_evidence_ids or []) for o in ordered),
    )
    security = _union(_roots(observed.security_evidence_ids))

    lock = (
        lock_decision.lock.model_copy(deep=True)
        if lock_decision is not None and lock_decision.lock is not None
        else common.Lock(locked=False)
    )
    return PresentedEdge(
        edge_id=observed.id,
        relation_type=observed.relation_type,
        source_id=observed.source_id,
        target_id=observed.target_id,
        domain_id=observed.domain_id.root,
        hidden=hidden,
        status=status,
        confidence=confidence,
        validity=validity.model_copy(deep=True),
        lock=lock,
        curation=curation,
        evidence_ids=evidence,
        security_evidence_ids=security,
        first_observed=observed.first_observed,
        last_observed=observed.last_observed,
        pinned=pinned,
        override_ids=_union(override_ids),
    )


def _curation(
    latest_visibility: EdgeOverride | None,
    lock_decision: EdgeOverride | None,
    ordered: Sequence[EdgeOverride],
) -> common.Curation | None:
    """Latest accept/reject, or the latest override while its lock is active."""
    candidates = [latest_visibility] if latest_visibility is not None else []
    if lock_decision is not None:
        overrides_in_chain = [o for o in _lock_chain(ordered) if o.decision == "override"]
        candidates.extend(overrides_in_chain[-1:])
    if not candidates:
        return None
    pick = max(candidates, key=lambda o: (parse_timestamp(o.decided_at.root), o.id))
    verdicts: dict[str, Literal["accepted", "rejected", "overridden"]] = {
        "accept": "accepted",
        "reject": "rejected",
        "override": "overridden",
    }
    verdict = verdicts[pick.decision]
    return common.Curation(
        decision=verdict,
        decided_by=pick.actor,
        decided_at=pick.decided_at,
        reason=pick.reason,
        override_id=common.OverrideId(root=pick.id),
        review_item_id=pick.review_item_id,
    )


# --------------------------------------------------------------------------- merge


class MergeOutcome(BaseModel):
    """Result of merging one inferred observation into the stored edge."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    stored: CatalogEdge
    """The edge to persist (evidence unioned, ``last_observed`` advanced). The repository
    assigns ``version``/``etag`` on write."""
    observation: EdgeObservation
    """The raw observation to record. ALWAYS recorded, locked or not."""
    presented_before: PresentedEdge | None
    presented: PresentedEdge
    presented_changed: bool
    """True when presented lineage (visibility, status, confidence, validity, lock) differs
    from before. Evidence and ``last_observed`` accumulation alone is not a change."""
    review_item: ReviewItem | None = None


def review_item_id(edge_id: str, reason: str, governing_override_id: str) -> str:
    """Deterministic ID so a replayed batch yields the same (deduplicated) review item."""
    digest = hashlib.sha256(f"{edge_id}|{reason}|{governing_override_id}".encode()).hexdigest()
    return f"review:{digest[:40]}"


def observation_id(edge_id: str, evidence_ids: Iterable[str], observed_at: str) -> str:
    """Deterministic observation ID (idempotent replay of the same observation)."""
    material = "|".join([edge_id, observed_at, *sorted(set(evidence_ids))])
    return f"obs:{hashlib.sha256(material.encode()).hexdigest()[:40]}"


def _lineage(p: PresentedEdge) -> dict[str, object]:
    return p.model_dump(
        include={"hidden", "status", "confidence", "validity", "lock", "pinned", "curation"}
    )


def merge_observation(
    existing: CatalogEdge | None,
    new_observation: CatalogEdge,
    overrides: Iterable[EdgeOverride],
    now: datetime,
) -> MergeOutcome:
    """Merge an inferred observation into ``existing`` (None for a first observation).

    * The observation is always recorded: ``last_observed`` advances, ``first_observed``
      keeps the earliest, evidence and security evidence are unioned.
    * ``confidence`` and ``validity`` follow the new inference unless an active lock holds
      them, in which case the stored values (and therefore presented lineage) are unchanged.
    * A conflict yields a ``ReviewItem`` and never changes presented lineage: an inference
      contradicting an active lock, or any re-observation of a curated reject.

    Raises ``ValueError`` if ``new_observation`` is not the same edge (id and relation type)
    as ``existing`` or ``now`` is naive.
    """
    _require_aware(now)
    if existing is not None and (
        existing.id != new_observation.id or existing.relation_type != new_observation.relation_type
    ):
        raise ValueError("new_observation must describe the same edge as existing")

    mine = [o for o in overrides if o.edge_id == new_observation.id]
    ordered = _ordered(mine, now)
    lock_decision = active_lock(ordered, now)
    now_text = format_timestamp(now)

    if existing is None:
        stored = new_observation.model_copy(deep=True)
    else:
        first = min(
            existing.first_observed.root, new_observation.first_observed.root, key=parse_timestamp
        )
        last = max(
            existing.last_observed.root, new_observation.last_observed.root, key=parse_timestamp
        )
        update: dict[str, object] = {
            "first_observed": common.Timestamp(root=first),
            "last_observed": common.Timestamp(root=last),
            "evidence_ids": _wrap(
                _union(_roots(existing.evidence_ids), _roots(new_observation.evidence_ids))
            ),
            "security_evidence_ids": _wrap(
                _union(
                    _roots(existing.security_evidence_ids),
                    _roots(new_observation.security_evidence_ids),
                )
            ),
            "updated_at": common.Timestamp(root=now_text),
        }
        if lock_decision is None:
            update["confidence"] = new_observation.confidence
            update["validity"] = new_observation.validity.model_copy(deep=True)
        stored = existing.model_copy(update=update, deep=True)

    observation = EdgeObservation(
        id=observation_id(
            new_observation.id,
            _roots(new_observation.evidence_ids),
            new_observation.last_observed.root,
        ),
        edge_id=new_observation.id,
        relation_type=new_observation.relation_type,
        cloud=new_observation.cloud.root,
        customer_id=new_observation.customer_id.root,
        domain_id=new_observation.domain_id.root,
        observed_at=new_observation.last_observed,
        confidence=new_observation.confidence,
        validity=new_observation.validity,
        provenance=new_observation.provenance,
        evidence_ids=_roots(new_observation.evidence_ids),
        security_evidence_ids=_roots(new_observation.security_evidence_ids),
    )

    before = present_edge(existing, ordered, now) if existing is not None else None
    after = present_edge(stored, ordered, now)
    if before is None:
        changed = not after.hidden
    elif before.hidden and after.hidden:
        changed = False  # a hidden edge is not part of presented lineage
    else:
        changed = _lineage(before) != _lineage(after)

    review: ReviewItem | None = None
    if existing is not None:
        review = _conflict(new_observation, after, ordered, lock_decision, now_text)

    return MergeOutcome(
        stored=stored,
        observation=observation,
        presented_before=before,
        presented=after,
        presented_changed=changed,
        review_item=review,
    )


def _conflict(
    new_observation: CatalogEdge,
    presented: PresentedEdge,
    ordered: Sequence[EdgeOverride],
    lock_decision: EdgeOverride | None,
    now_text: str,
) -> ReviewItem | None:
    reason: ConflictReason
    governing: EdgeOverride
    visibility = [o for o in ordered if o.decision in ("accept", "reject")]
    if visibility and visibility[-1].decision == "reject":
        reason, governing = "conflicts_with_reject", visibility[-1]
    elif lock_decision is not None and _contradicts(new_observation, presented):
        reason, governing = "conflicts_with_lock", lock_decision
    else:
        return None
    return ReviewItem(
        id=review_item_id(new_observation.id, reason, governing.id),
        edge_id=new_observation.id,
        relation_type=new_observation.relation_type,
        cloud=new_observation.cloud.root,
        customer_id=new_observation.customer_id.root,
        domain_id=new_observation.domain_id.root,
        reason=reason,
        governing_override_id=governing.id,
        observed_confidence=float(new_observation.confidence),
        presented_confidence=presented.confidence,
        new_evidence_ids=_roots(new_observation.evidence_ids),
        created_at=now_text,
    )


def _contradicts(new_observation: CatalogEdge, presented: PresentedEdge) -> bool:
    if abs(float(new_observation.confidence) - presented.confidence) >= CONFIDENCE_CONFLICT_DELTA:
        return True
    new_to = new_observation.validity.valid_to
    pinned_to = presented.validity.valid_to
    return (new_to.root if new_to else None) != (pinned_to.root if pinned_to else None)
