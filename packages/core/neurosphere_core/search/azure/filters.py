"""OData ``$filter`` construction for Azure AI Search, from server-derived scope only.

The filter is assembled exclusively from (a) the server-derived ``IdentityScope`` and (b)
allowlisted ``SearchFilters`` that can only narrow it. Every interpolated value must match a
strict canonical pattern (no quote, space, parenthesis, comma, pipe or non-ASCII character can
match), and lists go through ``search.in(field, 'a|b', '|')`` so a value is never parsed as
OData syntax. A value that fails validation is dropped from the scope side (which can only
shrink the result) and never repaired or escaped into the filter. The search term never
reaches the filter; it is tokenized into ``search_text`` separately.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Final

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope

from neurosphere_core.auth.scope.hashing import compute_scope_hash
from neurosphere_core.search.fixture.index import tokenize
from neurosphere_core.search.protocol import SearchRequest

__all__ = [
    "FIELD_CLOUD",
    "FIELD_CUSTOMER",
    "FIELD_DOMAIN",
    "FIELD_ENTITY",
    "FIELD_ID",
    "build_filter",
    "build_search_text",
    "cache_key",
    "scope_hash_of",
]

FIELD_ID: Final = "id"
FIELD_ENTITY: Final = "entity"
FIELD_CLOUD: Final = "cloud"
FIELD_CUSTOMER: Final = "customer_id"
FIELD_DOMAIN: Final = "domain_id"

_DELIM: Final = "|"
_ID_RE: Final = re.compile(
    r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+\Z"
)
_SIMPLE_RE: Final = re.compile(r"^[a-z0-9._-]{1,128}\Z")
_ENTITY_RE: Final = re.compile(r"^[a-z_]{1,32}\Z")
_CLOUDS: Final = frozenset({"commercial", "government"})


def _ascii_match(pattern: re.Pattern[str], value: str) -> bool:
    return value.isascii() and pattern.match(value) is not None


def _in(field: str, values: list[str]) -> str:
    return f"search.in({field}, '{_DELIM.join(values)}', '{_DELIM}')"


def build_filter(scope: IdentityScope, request: SearchRequest) -> str | None:
    """Return the ``$filter`` string, or ``None`` when nothing can be in scope.

    ``None`` means the caller must return an empty result without calling the service. The
    clauses are ``cloud eq`` AND ``customer_id eq`` AND (``domain_id`` in allowed OR ``id`` in
    read grants) AND optional narrowing by entity and by requested domains. Requested domains
    outside the scope never widen anything: they only intersect (zero results, no error).
    """
    if scope.cloud not in _CLOUDS or not _ascii_match(_SIMPLE_RE, scope.customer_id):
        return None
    allowed = sorted({d.root for d in scope.allowed_domains if _ascii_match(_ID_RE, d.root)})
    granted = sorted(
        {
            g.resource_id.root
            for g in scope.allowed_resources
            if "read" in g.permissions and _ascii_match(_ID_RE, g.resource_id.root)
        }
    )
    f = request.filters
    if f.entities is not None:
        entities = sorted({e for e in f.entities if _ascii_match(_ENTITY_RE, e)})
        if not entities:
            return None
    else:
        entities = None
    narrow: list[str] | None = None
    if f.domain_ids is not None:
        narrow = sorted({d for d in f.domain_ids if _ascii_match(_ID_RE, d)})
        if not narrow:
            return None
        allowed = [d for d in allowed if d in set(narrow)]  # intersect, never widen

    access: list[str] = []
    if allowed:
        access.append(_in(FIELD_DOMAIN, allowed))
    if granted:
        access.append(_in(FIELD_ID, granted))
    if not access:
        return None

    clauses = [
        f"{FIELD_CLOUD} eq '{scope.cloud}'",
        f"{FIELD_CUSTOMER} eq '{scope.customer_id}'",
        access[0] if len(access) == 1 else f"({access[0]} or {access[1]})",
    ]
    if entities is not None:
        clauses.append(_in(FIELD_ENTITY, entities))
    if narrow is not None:
        # Grants are still bounded by the requested domains, as in the fixture.
        clauses.append(_in(FIELD_DOMAIN, narrow))
    return " and ".join(clauses)


def build_search_text(term: str) -> str | None:
    """Tokenize to ``[a-z0-9]+`` words so no search operator survives; ``None`` if empty."""
    tokens = sorted(set(tokenize(term)))
    return " ".join(tokens) if tokens else None


def scope_hash_of(scope: IdentityScope) -> str:
    """Recompute the scope hash from the scope members (the declared field is not trusted)."""
    return compute_scope_hash(_drop_none(scope.model_dump(mode="json")))


def _drop_none(value: Any) -> Any:
    """Omit ``None`` members at every depth, as ``compute_scope_hash`` requires."""
    if isinstance(value, dict):
        return {k: _drop_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_none(v) for v in value]
    return value


def cache_key(scope: IdentityScope, request: SearchRequest) -> str:
    """Cache key for a search result: includes the scope hash so scopes never share entries.

    The timeout is excluded (it changes only whether a result is partial); the limit is
    included because it changes the result.
    """
    payload = {
        "scope": scope_hash_of(scope),
        "text": build_search_text(request.term),
        "entities": sorted(request.filters.entities)
        if request.filters.entities is not None
        else None,
        "domains": sorted(request.filters.domain_ids)
        if request.filters.domain_ids is not None
        else None,
        "limit": request.budget.limit,
    }
    digest = hashlib.sha256(
        json.dumps(_drop_none(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"search:v1:{digest}"
