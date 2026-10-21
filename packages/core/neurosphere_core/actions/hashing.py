"""Confirmation hash (PRP-01 ``confirmation-hash.json``, PRP-17 delta D1) and the wire form.

``confirmation_hash`` is ``sha256:`` + lowercase hex SHA-256 over the RFC 8785 (JCS) form of
an object holding exactly ``target``, ``target_version``, ``proposed_diff``,
``confirmation_expires_at`` and ``actor``. ``channel``, ``idempotency_key``, ``state``,
``evidence``, ``prerequisite_results`` and every other field are excluded, so button, chat, REST
and MCP produce one value for one confirmed intent. The exact expiry string is hashed.

The JCS serializer is :func:`neurosphere_core.audit.canonical.canonical_json`
(``packages/core/tests/actions/test_intent_hash.py`` proves it reproduces the contract
``test_vector``).

Wire form: the generated ``PatchOperation`` model cannot tell an absent ``value`` from ``null``
and always dumps ``from``. :func:`intent_to_wire` renders the only schema-valid shape instead
(add/replace/test carry ``value``; move/copy carry ``from``; remove carries neither), so a hash
computed from a stored intent, an API response or a client's request body agrees.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from neurosphere_contracts.actions.v1.action_intent import (
    ActionIntent,
    PatchOperation,
    ProposedDiff,
)

from neurosphere_core.actions.errors import ActionValidationError
from neurosphere_core.audit.canonical import digests_equal, sha256_digest
from neurosphere_core.errors import ValidationIssue

__all__ = [
    "HASHED_FIELDS",
    "compute_confirmation_hash",
    "confirmation_hash_input",
    "confirmation_hashes_equal",
    "diff_to_wire",
    "intent_digest",
    "intent_to_wire",
    "validate_proposed_diff",
]

HASHED_FIELDS: Final[tuple[str, ...]] = (
    "target",
    "target_version",
    "proposed_diff",
    "confirmation_expires_at",
    "actor",
)
_VALUE_OPS: Final = frozenset({"add", "replace", "test"})
_FROM_OPS: Final = frozenset({"move", "copy"})


def _op_to_wire(op: PatchOperation) -> dict[str, Any]:
    wire: dict[str, Any] = {"op": op.op, "path": op.path}
    if op.op in _VALUE_OPS:
        wire["value"] = op.value
    elif op.op in _FROM_OPS:
        wire["from"] = op.from_
    return wire


def diff_to_wire(diff: ProposedDiff) -> dict[str, Any]:
    """Schema-valid JSON for ``diff`` (see module docstring)."""
    return {"format": diff.format, "operations": [_op_to_wire(op) for op in diff.operations]}


def intent_to_wire(intent: ActionIntent) -> dict[str, Any]:
    """The intent as schema-valid contract JSON (aliases applied, patch ops normalized)."""
    wire = intent.model_dump(mode="json", by_alias=True)
    wire["proposed_diff"] = diff_to_wire(intent.proposed_diff)
    return wire


def validate_proposed_diff(diff: ProposedDiff) -> None:
    """Enforce the RFC 6902 member rules the generated model does not (schema allOf).

    Raises :class:`ActionValidationError` reason ``invalid_diff``; values are never echoed.
    """
    issues: list[ValidationIssue] = []
    for index, op in enumerate(diff.operations):
        pointer = f"/proposed_diff/operations/{index}"
        has_value = "value" in op.model_fields_set
        has_from = op.from_ is not None
        if op.op in _VALUE_OPS and (not has_value or has_from):
            issues.append(ValidationIssue(pointer, f"{op.op} requires value and forbids from"))
        elif op.op in _FROM_OPS and (not has_from or has_value):
            issues.append(ValidationIssue(pointer, f"{op.op} requires from and forbids value"))
        elif op.op == "remove" and (has_from or has_value):
            issues.append(ValidationIssue(pointer, "remove takes neither value nor from"))
    if issues:
        raise ActionValidationError("invalid_diff", "proposed_diff is not valid", errors=issues)


def confirmation_hash_input(source: ActionIntent | Mapping[str, Any]) -> dict[str, Any]:
    """The object that is hashed: exactly :data:`HASHED_FIELDS`, copied unchanged.

    ``source`` is an ``ActionIntent`` (rendered with :func:`intent_to_wire`) or contract JSON
    (a request body or stored document); a mapping missing a hashed member raises
    ``invalid_schema`` reason ``invalid_hash_input``.
    """
    wire = intent_to_wire(source) if isinstance(source, ActionIntent) else source
    missing = [field for field in HASHED_FIELDS if field not in wire]
    if missing:
        raise ActionValidationError(
            "invalid_hash_input",
            "confirmation hash input is incomplete",
            errors=[ValidationIssue(f"/{field}", "required for the hash") for field in missing],
        )
    return {field: wire[field] for field in HASHED_FIELDS}


def compute_confirmation_hash(source: ActionIntent | Mapping[str, Any]) -> str:
    """``sha256:<64 lowercase hex>`` over the JCS form of :func:`confirmation_hash_input`."""
    return sha256_digest(confirmation_hash_input(source))


def confirmation_hashes_equal(left: str | None, right: str | None) -> bool:
    """Constant-time comparison; ``None`` never equals a hash."""
    if left is None or right is None:
        return False
    return digests_equal(left, right)


def intent_digest(intent: ActionIntent) -> str:
    """Digest of the whole intent document (audit ``state_digest``; never a body in the log)."""
    return sha256_digest(intent_to_wire(intent))
