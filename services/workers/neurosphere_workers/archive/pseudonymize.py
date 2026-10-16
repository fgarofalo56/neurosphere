"""Person-identifier pseudonymization for the archive (PRP-07 C9).

The set of identifier keys is closed and defined here, once. Matching is case-insensitive on the
full key name. A matched value is replaced with ``pse_`` + HMAC-SHA256(key, value) hex, so the
same person maps to the same pseudonym within one key, and the raw value is unrecoverable
without it. Raw values and the key are never logged or put in errors. The walk is iterative.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Final

PSEUDONYM_PREFIX: Final = "pse_"

PERSON_IDENTIFIER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "user_id",
        "userid",
        "user.id",
        "enduser.id",
        "end_user_id",
        "user.email",
        "user_email",
        "email",
        "upn",
        "user_principal_name",
        "userprincipalname",
        "user.name",
        "username",
    }
)

# OTLP/JSON AnyValue single-key wrappers whose scalar is the real value.
_OTLP_SCALARS: Final = frozenset({"stringValue", "intValue", "doubleValue", "boolValue"})


def is_person_identifier_key(name: str) -> bool:
    return name.strip().lower() in PERSON_IDENTIFIER_KEYS


def _material(value: Any) -> str:
    """Stable text for hashing: a bare scalar as-is, an OTLP wrapper unwrapped, else JSON."""
    if isinstance(value, dict) and len(value) == 1:
        (only,) = value
        if only in _OTLP_SCALARS:
            return _material(value[only])
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def pseudonym(key: bytes, value: Any) -> str:
    digest = hmac.new(key, _material(value).encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{PSEUDONYM_PREFIX}{digest}"


def _replace(key: bytes, value: Any) -> Any:
    # Null stays null (absence is information, and there is no person to hide).
    return None if value is None else pseudonym(key, value)


def pseudonymize(payload: Any, key: bytes) -> Any:
    """Return a copy of ``payload`` with person-identifier values pseudonymized at any depth.

    Handles dict keys and OTLP attribute items (``{"key": name, "value": {...}}``, whose value
    becomes ``{"stringValue": "pse_..."}``). The input is never mutated.
    """
    if not isinstance(payload, (dict, list)):
        return payload
    root: Any = {} if isinstance(payload, dict) else []
    stack: list[tuple[Any, Any]] = [(payload, root)]
    while stack:
        src, dst = stack.pop()
        if isinstance(src, dict):
            for name, value in src.items():
                if isinstance(name, str) and is_person_identifier_key(name):
                    dst[name] = _replace(key, value)
                elif isinstance(value, (dict, list)):
                    child: Any = {} if isinstance(value, dict) else []
                    dst[name] = child
                    stack.append((value, child))
                else:
                    dst[name] = value
        else:
            for item in src:
                if (
                    isinstance(item, dict)
                    and "value" in item
                    and isinstance(item.get("key"), str)
                    and is_person_identifier_key(item["key"])
                ):
                    copied = {k: v for k, v in item.items() if k != "value"}
                    raw = item["value"]
                    copied["value"] = None if raw is None else {"stringValue": pseudonym(key, raw)}
                    dst.append(copied)
                elif isinstance(item, (dict, list)):
                    child = {} if isinstance(item, dict) else []
                    dst.append(child)
                    stack.append((item, child))
                else:
                    dst.append(item)
    return root
