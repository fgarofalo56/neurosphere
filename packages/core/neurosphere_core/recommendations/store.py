"""Recommendation store protocol and the in-memory implementation (PRP-15 item 4).

Every read takes the server-derived ``IdentityScope`` plus the addressed domain. Customer, cloud
and the domain (which must be in the scope's allowed domains) are mandatory predicates: a
recommendation of another customer, cloud or domain is simply absent (``get`` returns ``None``,
``list`` omits it). ``q`` is a bounded plain-text, case-insensitive substring match over the kind
and the subject ids; it is not a query language. A Cosmos implementation is OPEN (not built here).
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Sequence
from typing import Final, Protocol, runtime_checkable

from neurosphere_contracts.recommendations.v1.recommendation import Recommendation

from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.paging import Page
from neurosphere_core.paging.models import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from neurosphere_core.scope import IdentityScope

__all__ = ["MAX_QUERY_LENGTH", "InMemoryRecommendationStore", "RecommendationStore"]

MAX_QUERY_LENGTH: Final = 128


@runtime_checkable
class RecommendationStore(Protocol):
    async def put(self, recommendation: Recommendation) -> None:
        """Idempotent upsert keyed by ``recommendation_id`` (a re-put replaces the document)."""
        ...

    async def list(
        self,
        scope: IdentityScope,
        domain: str,
        kind: str | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page[Recommendation]:
        """One page of the scope's recommendations in ``domain``, ordered by id.

        ``q`` longer than ``MAX_QUERY_LENGTH`` or an invalid cursor is ``InvalidSchemaError``;
        ``limit`` is 1..``MAX_PAGE_SIZE``. A domain outside the scope yields an empty page.
        """
        ...

    async def get(
        self, scope: IdentityScope, domain: str, recommendation_id: str
    ) -> Recommendation | None:
        """The recommendation, or ``None`` when absent or outside the scope."""
        ...


def _visible(scope: IdentityScope, domain: str, rec: Recommendation) -> bool:
    return (
        rec.customer_id == scope.customer_id
        and rec.cloud == scope.cloud
        and domain in scope.allowed_domains
        and rec.domain_id.root == domain
    )


def _encode_cursor(last_id: str) -> str:
    return base64.urlsafe_b64encode(last_id.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> str:
    try:
        return base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeError, ValueError):
        raise InvalidSchemaError("invalid cursor", reason="invalid_cursor") from None


def _matches(rec: Recommendation, needle: str) -> bool:
    haystack = [rec.kind, *(s.root for s in rec.subject_ids)]
    return any(needle in part.lower() for part in haystack)


class InMemoryRecommendationStore:
    def __init__(self, recommendations: Sequence[Recommendation] = ()) -> None:
        self._items: dict[str, Recommendation] = {}
        for rec in recommendations:
            self._items[rec.recommendation_id.root] = rec.model_copy(deep=True)

    async def put(self, recommendation: Recommendation) -> None:
        self._items[recommendation.recommendation_id.root] = recommendation.model_copy(deep=True)

    async def list(
        self,
        scope: IdentityScope,
        domain: str,
        kind: str | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> Page[Recommendation]:
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise InvalidSchemaError(f"limit must be 1..{MAX_PAGE_SIZE}", reason="invalid_limit")
        needle = None
        if q is not None:
            if len(q) > MAX_QUERY_LENGTH:
                raise InvalidSchemaError(
                    f"q is limited to {MAX_QUERY_LENGTH} characters", reason="query_too_long"
                )
            needle = q.strip().lower() or None
        after = _decode_cursor(cursor) if cursor else None
        rows = [
            rec
            for rid, rec in sorted(self._items.items())
            if (after is None or rid > after)
            and _visible(scope, domain, rec)
            and (kind is None or rec.kind == kind)
            and (needle is None or _matches(rec, needle))
        ]
        page = rows[:limit]
        next_cursor = _encode_cursor(page[-1].recommendation_id.root) if len(rows) > limit else None
        return Page[Recommendation](
            items=tuple(r.model_copy(deep=True) for r in page), next_cursor=next_cursor
        )

    async def get(
        self, scope: IdentityScope, domain: str, recommendation_id: str
    ) -> Recommendation | None:
        rec = self._items.get(recommendation_id)
        if rec is None or not _visible(scope, domain, rec):
            return None
        return rec.model_copy(deep=True)
