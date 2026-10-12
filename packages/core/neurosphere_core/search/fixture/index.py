"""Deterministic BM25 fixture implementation of ``AuthorizedSearch``.

Guarantees: no randomness, embeddings or network; the scope filter runs before any scoring and
corpus statistics (IDF, average length) are computed over the in-scope candidates only, so
out-of-scope documents cannot influence scores; ties break by canonical ID ascending; the term
is only tokenized, never evaluated.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Literal

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope
from pydantic import BaseModel, ConfigDict

from neurosphere_core.search.protocol import (
    SearchHit,
    SearchRequest,
    SearchResult,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_TEXT_KEYS = ("name", "display_name", "description", "tags", "provider", "model_name", "kind")
_K1 = 1.2
_B = 0.75
_SCORE_DECIMALS = 9


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class SearchDocument(BaseModel):
    """One indexed catalog entity. ``domain_id`` is the authorization unit."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    entity: str
    cloud: str
    customer_id: str
    domain_id: str
    text: str


def documents_from_catalog(entities: Iterable[Mapping[str, Any]]) -> list[SearchDocument]:
    """Build search documents from catalog entity dicts (``id``, optional ``domain_id``).

    A domain document is its own authorization domain. Entities with neither a ``domain_id``
    nor a domain type are skipped: without an authorization unit they must never be searchable.
    """
    docs: list[SearchDocument] = []
    for ent in entities:
        cid = ent.get("id")
        if not isinstance(cid, str):
            continue
        parts = cid.split(":", 4)
        if len(parts) != 5:
            continue
        cloud, customer, _source, etype, _local = parts
        domain_id = cid if etype == "domain" else ent.get("domain_id")
        if not isinstance(domain_id, str):
            continue
        chunks: list[str] = []
        for key in _TEXT_KEYS:
            val = ent.get(key)
            if isinstance(val, str):
                chunks.append(val)
            elif isinstance(val, list):
                chunks.extend(v for v in val if isinstance(v, str))
        docs.append(
            SearchDocument(
                id=cid,
                entity=etype,
                cloud=cloud,
                customer_id=customer,
                domain_id=domain_id,
                text=" ".join(chunks),
            )
        )
    return docs


class FixtureSearchIndex:
    """In-process ``AuthorizedSearch``. The clock is injectable so timeout tests are exact."""

    def __init__(
        self,
        documents: Iterable[SearchDocument],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        by_id = {d.id: d for d in documents}
        self._docs: list[SearchDocument] = [by_id[k] for k in sorted(by_id)]
        self._tokens: dict[str, Counter[str]] = {
            d.id: Counter(tokenize(d.text)) for d in self._docs
        }
        self._clock = clock

    def _in_scope(self, scope: IdentityScope, request: SearchRequest) -> list[SearchDocument]:
        allowed = {d.root for d in scope.allowed_domains}
        granted = {g.resource_id.root for g in scope.allowed_resources if "read" in g.permissions}
        f = request.filters
        entities = set(f.entities) if f.entities is not None else None
        narrow = set(f.domain_ids) if f.domain_ids is not None else None
        out: list[SearchDocument] = []
        for d in self._docs:
            if d.cloud != scope.cloud or d.customer_id != scope.customer_id:
                continue
            if d.domain_id not in allowed and d.id not in granted:
                continue
            if entities is not None and d.entity not in entities:
                continue
            if narrow is not None and d.domain_id not in narrow:
                continue
            out.append(d)
        return out

    async def search(self, scope: IdentityScope, request: SearchRequest) -> SearchResult:
        deadline = self._clock() + request.budget.timeout_ms / 1000.0
        candidates = self._in_scope(scope, request)  # scope BEFORE ranking
        terms = sorted(set(tokenize(request.term)))
        if not terms or not candidates:
            return SearchResult(hits=[], matched=0, partial=False)

        n = len(candidates)
        lengths = {d.id: sum(self._tokens[d.id].values()) for d in candidates}
        avg_len = (sum(lengths.values()) / n) or 1.0
        df = {t: sum(1 for d in candidates if self._tokens[d.id][t] > 0) for t in terms}

        scored: list[tuple[float, str]] = []
        timed_out = False
        for d in candidates:
            if self._clock() > deadline:
                timed_out = True
                break
            tf = self._tokens[d.id]
            score = 0.0
            for t in terms:
                freq = tf[t]
                if freq == 0:
                    continue
                idf = math.log(1.0 + (n - df[t] + 0.5) / (df[t] + 0.5))
                norm = freq + _K1 * (1.0 - _B + _B * lengths[d.id] / avg_len)
                score += idf * freq * (_K1 + 1.0) / norm
            if score > 0.0:
                scored.append((round(score, _SCORE_DECIMALS), d.id))

        scored.sort(key=lambda p: (-p[0], p[1]))
        limit = request.budget.limit
        reason: Literal["limit", "timeout_ms"] | None = None
        if timed_out:
            reason = "timeout_ms"
        elif len(scored) > limit:
            reason = "limit"
        return SearchResult(
            hits=[SearchHit(id=i, score=s) for s, i in scored[:limit]],
            matched=len(scored),
            partial=reason is not None,
            partial_reason=reason,
        )
