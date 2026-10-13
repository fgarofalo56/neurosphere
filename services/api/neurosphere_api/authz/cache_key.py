"""Scope-keyed cache keys (PRP-06 C9).

``scope_cache_key(scope, namespace=...)`` is the only sanctioned way to key a cache entry that
holds scope-filtered data. Layout::

    ns:<cloud>:<customer_id>:<namespace>:pv=<policy_version>:<scope_hash>

* The cloud and customer prefix keeps Commercial/Government and customers in disjoint key
  spaces (prefix-based invalidation per customer is possible).
* ``scope_hash`` is item 2's sha256 over the canonical scope (principal, roles, domains,
  grants, policy version), so two principals with different scopes never share a key.
* The policy version is explicit, so a policy bump moves every caller to new keys.

Only a server-derived ``IdentityScope`` is accepted. The function has no parameter through which
token material could enter, and every component is percent-encoded so no component can forge a
separator. Keys carry no raw object id (the principal is only inside the hash).
"""

from __future__ import annotations

import re
from typing import Final
from urllib.parse import quote

from neurosphere_core.scope import IdentityScope

__all__ = ["CACHE_KEY_PREFIX", "NAMESPACE_PATTERN", "cache_key_prefix", "scope_cache_key"]

CACHE_KEY_PREFIX: Final = "ns"
NAMESPACE_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SCOPE_HASH: Final = re.compile(r"^sha256:[0-9a-f]{64}$")


def _part(value: str) -> str:
    return quote(value, safe="")


def cache_key_prefix(scope: IdentityScope) -> str:
    """``ns:<cloud>:<customer_id>:`` for ``scope`` (per-customer invalidation)."""
    if not isinstance(scope, IdentityScope):
        raise TypeError("cache keys require a server-derived IdentityScope")
    return f"{CACHE_KEY_PREFIX}:{_part(scope.cloud)}:{_part(scope.customer_id)}:"


def scope_cache_key(scope: IdentityScope, *, namespace: str) -> str:
    """Cache key for data computed under ``scope`` in cache ``namespace`` (e.g. ``catalog``)."""
    prefix = cache_key_prefix(scope)
    if not NAMESPACE_PATTERN.fullmatch(namespace):
        raise ValueError("cache namespace must match [a-z0-9][a-z0-9._-]{0,63}")
    scope_hash = scope.scope_hash
    if not _SCOPE_HASH.fullmatch(scope_hash):
        raise ValueError("scope hash is not a sha256 digest")
    return f"{prefix}{namespace}:pv={_part(scope.policy_version)}:{scope_hash}"
