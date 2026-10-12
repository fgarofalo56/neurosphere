"""RFC 8785 (JCS) canonical JSON and the audit record hash.

The AuditRecord contract defines ``record_hash`` as sha256 over the JCS form of the record
without ``record_hash``. This module is the production twin of the test-only helper in
``tests/contracts/contract_support.py``; ``packages/core/tests/audit/test_chain.py`` proves the
two agree by re-hashing the contract's own example chain.

Digests are always compared with :func:`digests_equal` (``hmac.compare_digest``), never ``==``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from collections.abc import Mapping
from typing import Any, Final

SHA256_PREFIX: Final = "sha256:"
RECORD_HASH_FIELD: Final = "record_hash"


def _number(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        raise ValueError("RFC 8785 forbids NaN and Infinity")
    if value == int(value) and abs(value) < 1e21:
        return str(int(value))
    text = repr(value)
    if "e" in text:  # ECMAScript exponent form: e+N / e-N, no leading zeros
        mantissa, exponent = text.split("e")
        sign = "-" if exponent.startswith("-") else "+"
        text = f"{mantissa}e{sign}{exponent.lstrip('+-').lstrip('0') or '0'}"
    return text


def canonical_json(value: Any) -> str:
    """Return the RFC 8785 canonical form of a JSON value (dict keys sorted by UTF-16 units)."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int | float):
        return _number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list | tuple):
        return "[" + ",".join(canonical_json(v) for v in value) + "]"  # pyright: ignore[reportUnknownVariableType]
    if isinstance(value, Mapping):
        items: dict[str, Any] = {}
        for key, item in value.items():  # pyright: ignore[reportUnknownVariableType]
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            items[key] = item
        keys = sorted(items, key=lambda k: k.encode("utf-16-be"))
        members = (f"{json.dumps(k, ensure_ascii=False)}:{canonical_json(items[k])}" for k in keys)
        return "{" + ",".join(members) + "}"
    raise TypeError(f"not a JSON value: {type(value).__name__}")


def sha256_digest(value: Any) -> str:
    """``sha256:<hex>`` over the canonical JSON of ``value``."""
    return SHA256_PREFIX + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def compute_record_hash(document: Mapping[str, Any]) -> str:
    """Hash of an audit record document, excluding its own ``record_hash`` field."""
    return sha256_digest({k: v for k, v in document.items() if k != RECORD_HASH_FIELD})


def digests_equal(left: str | None, right: str | None) -> bool:
    """Constant-time digest comparison. ``None`` equals only ``None`` (chain head)."""
    if left is None or right is None:
        return left is None and right is None
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
