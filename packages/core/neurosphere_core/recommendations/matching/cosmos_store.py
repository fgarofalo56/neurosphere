"""Cosmos NoSQL feedback store for the agent/tool recommender (PRP-72 item 2).

Container ``recommendation_feedback``: hierarchical partition key ``/customer_id``,
``/domain_id`` and per-item ``ttl`` (the container has TTL on with no default). Two document
kinds share it: ``match`` and ``feedback``. Documents hold normalized task tokens, the principal
pseudonym, ids, decision, rank/score, timestamps and ``ttl``; never task text. Ids are SHA-256
digests of the logical key, so no caller-supplied string is used as a Cosmos id.

Every read is single-partition (``partition_key=[customer, domain]``) and repeats the customer
and domain predicates. Outages map to ``dependency_transient``
(``recommendation_feedback_store_unavailable``) and 429 to ``rate_limited``; error details never
carry stored values.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final, NoReturn

from azure.cosmos import PartitionKey
from azure.cosmos.aio import ContainerProxy, CosmosClient, DatabaseProxy
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError

from neurosphere_core.errors import (
    DependencyTransientError,
    NeuroSphereError,
    RateLimitedError,
)
from neurosphere_core.recommendations.matching.feedback import (
    DEFAULT_TTL_DAYS,
    Decision,
    FeedbackMetrics,
    FeedbackRecord,
    MatchCandidateRecord,
    MatchNotFoundError,
    MatchRecord,
    build_feedback,
    summarize_metrics,
    to_utc,
    utc_now,
    validate_match,
    validate_query_bounds,
)

__all__ = [
    "DEFAULT_FEEDBACK_CONTAINER",
    "FEEDBACK_PARTITION_KEY_PATHS",
    "CosmosFeedbackStore",
    "create_feedback_container",
]

DEFAULT_FEEDBACK_CONTAINER: Final = "recommendation_feedback"
FEEDBACK_PARTITION_KEY_PATHS: Final = ("/customer_id", "/domain_id")
KIND_MATCH: Final = "match"
KIND_FEEDBACK: Final = "feedback"
FEEDBACK_STORE_UNAVAILABLE: Final = "recommendation_feedback_store_unavailable"
_TIME_FORMAT: Final = "%Y-%m-%dT%H:%M:%S.%fZ"
_MAX_ROWS: Final = 10_000


async def create_feedback_container(
    database: DatabaseProxy, container_id: str = DEFAULT_FEEDBACK_CONTAINER
) -> ContainerProxy:
    """Create (or open) the container: hierarchical key, TTL on with per-item expiry."""
    return await database.create_container_if_not_exists(
        id=container_id,
        partition_key=PartitionKey(path=list(FEEDBACK_PARTITION_KEY_PATHS), kind="MultiHash"),
        default_ttl=-1,
    )


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _match_doc_id(match_id: str) -> str:
    return "match-" + _digest(match_id)


def _feedback_doc_id(match_id: str, principal: str, entity_id: str) -> str:
    return "feedback-" + _digest(match_id, principal, entity_id)


def _fmt(value: datetime) -> str:
    return to_utc(value).strftime(_TIME_FORMAT)


def _parse(value: str) -> datetime:
    return datetime.strptime(value, _TIME_FORMAT).replace(tzinfo=UTC)


def _ttl_seconds(expires_at: datetime, now: datetime) -> int:
    return max(1, int((expires_at - now).total_seconds()))


def _unavailable() -> DependencyTransientError:
    return DependencyTransientError(
        "recommendation feedback store unavailable", reason=FEEDBACK_STORE_UNAVAILABLE
    )


def _invalid() -> DependencyTransientError:
    return DependencyTransientError(
        "stored feedback document failed validation",
        reason="recommendation_feedback_record_invalid",
        upstream_invalid=True,
    )


def _raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NeuroSphereError):
        raise exc
    if isinstance(exc, CosmosHttpResponseError) and exc.status_code == 429:
        raise RateLimitedError(1, "feedback store throttled the request") from exc
    raise _unavailable() from exc


def _match_from_row(row: Mapping[str, Any]) -> MatchRecord:
    try:
        return MatchRecord(
            match_id=row["match_id"],
            customer_id=row["customer_id"],
            domain_id=row["domain_id"],
            principal=row["principal"],
            task_tokens=tuple(row["task_tokens"]),
            candidates=tuple(
                MatchCandidateRecord(c["entity_id"], int(c["rank"]), float(c["score"]))
                for c in row["candidates"]
            ),
            created_at=_parse(row["created_at"]),
            expires_at=_parse(row["expires_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid() from exc


def _feedback_from_row(row: Mapping[str, Any]) -> FeedbackRecord:
    try:
        decision: Decision = "accepted" if row["decision"] == "accepted" else "rejected"
        return FeedbackRecord(
            match_id=row["match_id"],
            customer_id=row["customer_id"],
            domain_id=row["domain_id"],
            principal=row["principal"],
            entity_id=row["entity_id"],
            decision=decision,
            reason_code=row.get("reason_code"),
            rank_at_decision=int(row["rank_at_decision"]),
            score_at_decision=float(row["score_at_decision"]),
            task_tokens=tuple(row["task_tokens"]),
            decided_at=_parse(row["decided_at"]),
            expires_at=_parse(row["expires_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid() from exc


class CosmosFeedbackStore:
    """:class:`neurosphere_core.recommendations.matching.feedback.FeedbackStore` on Cosmos."""

    def __init__(
        self,
        container: ContainerProxy,
        *,
        ttl_days: int = DEFAULT_TTL_DAYS,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._container = container
        self._ttl_days = ttl_days
        self._clock = clock

    @classmethod
    def from_client(
        cls,
        client: CosmosClient,
        *,
        database: str,
        container: str = DEFAULT_FEEDBACK_CONTAINER,
        ttl_days: int = DEFAULT_TTL_DAYS,
    ) -> CosmosFeedbackStore:
        return cls(
            client.get_database_client(database).get_container_client(container),
            ttl_days=ttl_days,
        )

    async def record_match(self, match: MatchRecord) -> None:
        validate_match(match)
        body: dict[str, Any] = {
            "id": _match_doc_id(match.match_id),
            "kind": KIND_MATCH,
            "match_id": match.match_id,
            "customer_id": match.customer_id,
            "domain_id": match.domain_id,
            "principal": match.principal,
            "task_tokens": list(match.task_tokens),
            "candidates": [
                {"entity_id": c.entity_id, "rank": c.rank, "score": c.score}
                for c in match.candidates
            ],
            "created_at": _fmt(match.created_at),
            "expires_at": _fmt(match.expires_at),
            "ttl": _ttl_seconds(match.expires_at, self._clock()),
        }
        try:
            await self._container.upsert_item(body=body)
        except Exception as exc:
            _raise_mapped(exc)

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
        try:
            row = await self._container.read_item(
                item=_match_doc_id(match_id), partition_key=[customer_id, domain_id]
            )
        except CosmosResourceNotFoundError:
            raise MatchNotFoundError from None
        except Exception as exc:
            _raise_mapped(exc)
        if row.get("kind") != KIND_MATCH:
            raise MatchNotFoundError
        match = _match_from_row(row)
        if (
            match.customer_id != customer_id
            or match.domain_id != domain_id
            or match.match_id != match_id
            or match.expires_at <= now
        ):
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
        body: dict[str, Any] = {
            "id": _feedback_doc_id(match_id, principal, entity_id),
            "kind": KIND_FEEDBACK,
            "match_id": record.match_id,
            "customer_id": record.customer_id,
            "domain_id": record.domain_id,
            "principal": record.principal,
            "entity_id": record.entity_id,
            "decision": record.decision,
            "reason_code": record.reason_code,
            "rank_at_decision": record.rank_at_decision,
            "score_at_decision": record.score_at_decision,
            "task_tokens": list(record.task_tokens),
            "decided_at": _fmt(record.decided_at),
            "expires_at": _fmt(record.expires_at),
            "ttl": _ttl_seconds(record.expires_at, now),
        }
        try:
            await self._container.upsert_item(body=body)
        except Exception as exc:
            _raise_mapped(exc)
        return record

    async def list_feedback(
        self, *, customer_id: str, domain_ids: Sequence[str], entity_ids: Sequence[str]
    ) -> tuple[FeedbackRecord, ...]:
        validate_query_bounds(domain_ids, entity_ids)
        if not entity_ids:
            return ()
        now = self._clock()
        found: list[FeedbackRecord] = []
        for domain in sorted(set(domain_ids)):
            # Only fixed clause text and parameter placeholders are interpolated.
            sql = (
                "SELECT TOP @limit * FROM c WHERE c.kind = @kind AND c.customer_id = @customer "
                "AND c.domain_id = @domain AND ARRAY_CONTAINS(@entities, c.entity_id)"
            )
            params: list[dict[str, Any]] = [
                {"name": "@limit", "value": _MAX_ROWS},
                {"name": "@kind", "value": KIND_FEEDBACK},
                {"name": "@customer", "value": customer_id},
                {"name": "@domain", "value": domain},
                {"name": "@entities", "value": sorted(set(entity_ids))},
            ]
            try:
                rows = [
                    row
                    async for row in self._container.query_items(
                        sql, parameters=params, partition_key=[customer_id, domain]
                    )
                ]
            except Exception as exc:
                _raise_mapped(exc)
            found.extend(r for r in map(_feedback_from_row, rows) if r.expires_at > now)
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
        lower, upper = _fmt(since), _fmt(until)
        matches = 0
        decisions: list[tuple[str, Decision]] = []
        for domain in sorted(set(domain_ids)):
            base: list[dict[str, Any]] = [
                {"name": "@customer", "value": customer_id},
                {"name": "@domain", "value": domain},
                {"name": "@since", "value": lower},
                {"name": "@until", "value": upper},
            ]
            count_sql = (
                "SELECT VALUE COUNT(1) FROM c WHERE c.kind = @kind AND c.customer_id = @customer "
                "AND c.domain_id = @domain AND c.created_at >= @since AND c.created_at < @until"
            )
            rows_sql = (
                "SELECT TOP @limit c.match_id, c.decision FROM c WHERE c.kind = @kind "
                "AND c.customer_id = @customer AND c.domain_id = @domain "
                "AND c.decided_at >= @since AND c.decided_at < @until"
            )
            try:
                counts: list[Any] = [
                    n
                    async for n in self._container.query_items(
                        count_sql,
                        parameters=[{"name": "@kind", "value": KIND_MATCH}, *base],
                        partition_key=[customer_id, domain],
                    )
                ]
                rows = [
                    row
                    async for row in self._container.query_items(
                        rows_sql,
                        parameters=[
                            {"name": "@limit", "value": _MAX_ROWS},
                            {"name": "@kind", "value": KIND_FEEDBACK},
                            *base,
                        ],
                        partition_key=[customer_id, domain],
                    )
                ]
            except Exception as exc:
                _raise_mapped(exc)
            matches += sum(int(n) for n in counts)
            decisions.extend(
                (str(r["match_id"]), "accepted" if r["decision"] == "accepted" else "rejected")
                for r in rows
            )
        return summarize_metrics(matches, decisions)
