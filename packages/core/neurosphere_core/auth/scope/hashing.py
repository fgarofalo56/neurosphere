"""``scope_hash``: sha256 over the RFC 8785 (JCS) form of the scope-defining members.

The hashed projection is fixed by the contract schema: ``cloud``, ``customer_id``,
``principal.principal_id`` (kept at its path), ``roles``, ``allowed_domains``,
``allowed_resources`` and ``policy_version``. ``derived_at``/``expires_at`` are excluded so a
re-derivation of the same policy yields the same hash (stable cache keys, C9).

The scope documents hashed here hold only ASCII strings, lists and objects, for which
``json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`` is exactly JCS (key
order by UTF-16 code unit equals code point order for BMP keys; string escaping matches). Other
JSON types are refused rather than approximated.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Final

__all__ = ["SCOPE_HASH_MEMBERS", "canonical_json", "compute_scope_hash"]

SCOPE_HASH_MEMBERS: Final = (
    "cloud",
    "customer_id",
    "roles",
    "allowed_domains",
    "allowed_resources",
    "policy_version",
)


def _check(value: Any) -> None:
    if isinstance(value, str):
        if not value.isascii():
            raise ValueError("scope members must be ASCII")
        return
    if isinstance(value, list):
        for item in value:
            _check(item)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _check(key)
            _check(item)
        return
    raise TypeError(f"unsupported JSON value in scope: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    _check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_scope_hash(scope: Mapping[str, Any]) -> str:
    """Hash of a contract-shaped scope document (``None`` members must already be omitted)."""
    projection: dict[str, Any] = {k: scope[k] for k in SCOPE_HASH_MEMBERS}
    projection["principal"] = {"principal_id": scope["principal"]["principal_id"]}
    digest = hashlib.sha256(canonical_json(projection).encode("utf-8")).hexdigest()
    return "sha256:" + digest
