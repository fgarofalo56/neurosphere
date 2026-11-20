"""Match feedback store, bounded feedback prior and metrics for the agent/tool recommender (PRP-72).

What is stored, and only this: a ``match`` record (match id, customer, domain, principal
pseudonym, at most 32 normalized task tokens, the ordered candidate ids with rank and score,
created and expiry timestamps) and one ``feedback`` record per (principal pseudonym, match,
candidate): decision, optional reason code, rank and score at decision, the match's task tokens
(so later similar tasks can find it), timestamps. Never task text and never a clear principal
identifier; callers pass the pseudonym. Nothing from these fields is logged here.

The prior (:func:`feedback_signal`) is a transparent, bounded adjustment, not a trained model:
smoothed accept share over similar-task feedback, one vote per principal, at most
``min_principals`` principals' worth of weight per candidate, and exactly 0 below
``min_principals`` distinct principals.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, Protocol

from neurosphere_core.errors import InvalidSchemaError, NotFoundError

__all__ = [
    "DEFAULT_FEEDBACK_BOUND",
    "DEFAULT_MIN_PRINCIPALS",
    "DEFAULT_TTL_DAYS",
    "MAX_DOMAINS",
    "MAX_ENTITY_IDS",
    "MAX_TASK_TOKENS",
    "MIN_TASK_SIMILARITY",
    "CandidateNotInMatchError",
    "Decision",
    "FeedbackMetrics",
    "FeedbackRecord",
    "FeedbackSignal",
    "FeedbackStore",
    "InMemoryFeedbackStore",
    "MatchCandidateRecord",
    "MatchNotFoundError",
    "MatchRecord",
    "feedback_signal",
    "summarize_metrics",
    "token_jaccard",
]

Decision = Literal["accepted", "rejected"]

DEFAULT_FEEDBACK_BOUND: Final = 0.15
DEFAULT_MIN_PRINCIPALS: Final = 3
DEFAULT_TTL_DAYS: Final = 180
MAX_TASK_TOKENS: Final = 32
MAX_ENTITY_IDS: Final = 1000
MAX_DOMAINS: Final = 50
MIN_TASK_SIMILARITY: Final = 0.5
_MAX_FIELD: Final = 256

# Detail codes of :class:`FeedbackSignal`.
DETAIL_INSUFFICIENT: Final = "feedback_insufficient_evidence"
DETAIL_POSITIVE: Final = "feedback_positive"
DETAIL_NEGATIVE: Final = "feedback_negative"
DETAIL_NEUTRAL: Final = "feedback_neutral"


class MatchNotFoundError(NotFoundError):
    """No live match of this id was shown to this principal (unknown, expired or someone else's)."""

    def __init__(self) -> None:
        super().__init__("match not found", reason="match_not_found")


class CandidateNotInMatchError(InvalidSchemaError):
    """The candidate was not part of the match the principal received."""

    def __init__(self) -> None:
        super().__init__("candidate was not in that match", reason="candidate_not_in_match")


@dataclass(frozen=True, slots=True)
class MatchCandidateRecord:
    entity_id: str
    rank: int
    score: float


@dataclass(frozen=True, slots=True)
class MatchRecord:
    """A match shown to one principal. ``task_tokens`` are normalized tokens, never text."""

    match_id: str
    customer_id: str
    domain_id: str
    principal: str
    task_tokens: tuple[str, ...]
    candidates: tuple[MatchCandidateRecord, ...]
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class FeedbackRecord:
    match_id: str
    customer_id: str
    domain_id: str
    principal: str
    entity_id: str
    decision: Decision
    reason_code: str | None
    rank_at_decision: int
    score_at_decision: float
    task_tokens: tuple[str, ...]
    decided_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class FeedbackMetrics:
    matches: int
    matches_with_feedback: int
    accepts: int
    rejects: int
    #: ``accepts / (accepts + rejects)``; ``None`` (never 0) when there is no feedback.
    acceptance_rate: float | None


@dataclass(frozen=True, slots=True)
class FeedbackSignal:
    prior: float
    detail_code: str
    principals: int


class FeedbackStore(Protocol):
    """Durable match and feedback documents. Implementations: in-memory and Cosmos."""

    async def record_match(self, match: MatchRecord) -> None: ...

    async def record_feedback(
        self,
        *,
        customer_id: str,
        domain_id: str,
        match_id: str,
        principal: str,
        entity_id: str,
        decision: Decision,
        reason_code: str | None = None,
    ) -> FeedbackRecord:
        """Store (or replace) the one decision of ``principal`` on ``entity_id`` of the match.

        Raises :class:`MatchNotFoundError` when the match is unknown, expired or was shown to a
        different principal, and :class:`CandidateNotInMatchError` for a candidate not in it.
        """
        ...

    async def list_feedback(
        self, *, customer_id: str, domain_ids: Sequence[str], entity_ids: Sequence[str]
    ) -> tuple[FeedbackRecord, ...]: ...

    async def metrics(
        self,
        *,
        customer_id: str,
        domain_ids: Sequence[str],
        since: datetime,
        until: datetime,
    ) -> FeedbackMetrics: ...


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise InvalidSchemaError("timestamps must be timezone-aware", reason="naive_timestamp")
    return value.astimezone(UTC)


def validate_match(match: MatchRecord) -> None:
    """Refuse a match that would store more than the contract allows."""
    if len(match.task_tokens) > MAX_TASK_TOKENS:
        raise InvalidSchemaError(
            f"at most {MAX_TASK_TOKENS} task tokens may be stored", reason="too_many_tokens"
        )
    for value in (match.match_id, match.customer_id, match.domain_id, match.principal):
        if not value or len(value) > _MAX_FIELD:
            raise InvalidSchemaError("invalid identifier length", reason="invalid_identifier")
    if not match.candidates:
        raise InvalidSchemaError("a match needs at least one candidate", reason="no_candidates")
    to_utc(match.created_at)
    to_utc(match.expires_at)


def validate_query_bounds(domain_ids: Sequence[str], entity_ids: Sequence[str] = ()) -> None:
    if len(domain_ids) > MAX_DOMAINS or len(entity_ids) > MAX_ENTITY_IDS:
        raise InvalidSchemaError("too many domains or entity ids", reason="query_too_large")


def build_feedback(
    match: MatchRecord,
    *,
    principal: str,
    entity_id: str,
    decision: Decision,
    reason_code: str | None,
    decided_at: datetime,
    ttl_days: int,
) -> FeedbackRecord:
    """Authorize a decision against its match and build the record (shared by both stores)."""
    if match.principal != principal:
        raise MatchNotFoundError
    chosen = next((c for c in match.candidates if c.entity_id == entity_id), None)
    if chosen is None:
        raise CandidateNotInMatchError
    return FeedbackRecord(
        match_id=match.match_id,
        customer_id=match.customer_id,
        domain_id=match.domain_id,
        principal=principal,
        entity_id=entity_id,
        decision=decision,
        reason_code=reason_code,
        rank_at_decision=chosen.rank,
        score_at_decision=chosen.score,
        task_tokens=match.task_tokens,
        decided_at=decided_at,
        expires_at=decided_at + timedelta(days=ttl_days),
    )


def token_jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def summarize_metrics(matches: int, decisions: Iterable[tuple[str, Decision]]) -> FeedbackMetrics:
    """Aggregate a window: ``decisions`` are (match id, decision) pairs, one per stored feedback."""
    accepts = rejects = 0
    with_feedback: set[str] = set()
    for match_id, decision in decisions:
        with_feedback.add(match_id)
        if decision == "accepted":
            accepts += 1
        else:
            rejects += 1
    total = accepts + rejects
    return FeedbackMetrics(
        matches=matches,
        matches_with_feedback=len(with_feedback),
        accepts=accepts,
        rejects=rejects,
        acceptance_rate=(accepts / total) if total else None,
    )


def feedback_signal(
    records: Iterable[FeedbackRecord],
    *,
    candidate_id: str,
    task_tokens: Sequence[str],
    bound: float = DEFAULT_FEEDBACK_BOUND,
    min_principals: int = DEFAULT_MIN_PRINCIPALS,
    ttl_days: int = DEFAULT_TTL_DAYS,
    now: datetime | None = None,
) -> FeedbackSignal:
    """Bounded prior for ``candidate_id`` from similar-task feedback.

    Only records for the candidate whose stored tokens have Jaccard >= 0.5 with ``task_tokens``
    and that are not older than ``ttl_days`` count. Each principal votes once (their latest
    decision). Below ``min_principals`` distinct principals the prior is 0. Above it, each
    principal's weight is scaled so the candidate carries ``min_principals`` principals' worth.
    The prior is ``bound`` times a Laplace-smoothed accept share mapped to -1..1, so it never
    leaves ``[-bound, +bound]``.
    """
    if bound < 0 or min_principals < 1 or ttl_days < 1:
        raise ValueError("bound >= 0, min_principals >= 1 and ttl_days >= 1 are required")
    cutoff = (now or utc_now()) - timedelta(days=ttl_days)
    latest: dict[str, FeedbackRecord] = {}
    for record in records:
        if record.entity_id != candidate_id or record.decided_at < cutoff:
            continue
        if token_jaccard(record.task_tokens, task_tokens) < MIN_TASK_SIMILARITY:
            continue
        prior = latest.get(record.principal)
        if prior is None or record.decided_at > prior.decided_at:
            latest[record.principal] = record
    principals = len(latest)
    if principals < min_principals:
        return FeedbackSignal(0.0, DETAIL_INSUFFICIENT, principals)
    weight = min(1.0, min_principals / principals)
    accepted = sum(weight for r in latest.values() if r.decision == "accepted")
    total = weight * principals
    share = (accepted + 1.0) / (total + 2.0)
    prior_value = max(-bound, min(bound, bound * (2.0 * share - 1.0)))
    if prior_value > 0:
        detail = DETAIL_POSITIVE
    elif prior_value < 0:
        detail = DETAIL_NEGATIVE
    else:
        detail = DETAIL_NEUTRAL
    return FeedbackSignal(prior_value, detail, principals)


class InMemoryFeedbackStore:
    """In-process twin of the Cosmos store (same refusals, same expiry, same metrics)."""

    def __init__(
        self, *, ttl_days: int = DEFAULT_TTL_DAYS, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._ttl_days = ttl_days
        self._clock = clock
        self._matches: dict[tuple[str, str, str], MatchRecord] = {}
        self._feedback: dict[tuple[str, str, str, str, str], FeedbackRecord] = {}

    async def record_match(self, match: MatchRecord) -> None:
        validate_match(match)
        self._matches[(match.customer_id, match.domain_id, match.match_id)] = match

    async def record_feedback(
        self,
        *,
        customer_id: str,
        domain_id: str,
        match_id: str,
        principal: str,
        entity_id: str,
        decision: Decision,
        reason_code: str | None = None,
    ) -> FeedbackRecord:
        now = self._clock()
        match = self._matches.get((customer_id, domain_id, match_id))
        if match is None or match.expires_at <= now:
            raise MatchNotFoundError
        record = build_feedback(
            match,
            principal=principal,
            entity_id=entity_id,
            decision=decision,
            reason_code=reason_code,
            decided_at=now,
            ttl_days=self._ttl_days,
        )
        self._feedback[(customer_id, domain_id, match_id, principal, entity_id)] = record
        return record

    async def list_feedback(
        self, *, customer_id: str, domain_ids: Sequence[str], entity_ids: Sequence[str]
    ) -> tuple[FeedbackRecord, ...]:
        validate_query_bounds(domain_ids, entity_ids)
        domains, entities, now = set(domain_ids), set(entity_ids), self._clock()
        found = [
            r
            for r in self._feedback.values()
            if r.customer_id == customer_id
            and r.domain_id in domains
            and r.entity_id in entities
            and r.expires_at > now
        ]
        found.sort(key=lambda r: (r.decided_at, r.match_id, r.principal, r.entity_id))
        return tuple(found)

    async def metrics(
        self,
        *,
        customer_id: str,
        domain_ids: Sequence[str],
        since: datetime,
        until: datetime,
    ) -> FeedbackMetrics:
        validate_query_bounds(domain_ids)
        since, until, now = to_utc(since), to_utc(until), self._clock()
        domains = set(domain_ids)
        matches = sum(
            1
            for m in self._matches.values()
            if m.customer_id == customer_id
            and m.domain_id in domains
            and m.expires_at > now
            and since <= m.created_at < until
        )
        decisions: list[tuple[str, Decision]] = [
            (r.match_id, r.decision)
            for r in self._feedback.values()
            if r.customer_id == customer_id
            and r.domain_id in domains
            and r.expires_at > now
            and since <= r.decided_at < until
        ]
        return summarize_metrics(matches, decisions)
