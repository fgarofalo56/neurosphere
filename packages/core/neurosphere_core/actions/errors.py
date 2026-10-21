"""Action-plane error helpers and the machine reason codes (PRP-17 delta D3).

The PRP-01 taxonomy has no ``validation_error`` code. Every "validation_error" the PRP names is
rendered as ``invalid_schema`` (422) with a specific ``reason``; :class:`ActionValidationError`
is that error with a mandatory reason so a caller can match on it. The other D3 mappings use the
taxonomy classes directly:

* expired confirmation          -> ``stale_version``          reason ``confirmation_expired``
* target version changed        -> ``stale_version``          reason ``target_version_changed``
* concurrent intent update      -> ``stale_version``          reason ``intent_modified``
* confirmation hash mismatch    -> ``invalid_schema``         reason ``confirmation_hash_mismatch``
* transition not on allowlist   -> ``invalid_schema``         reason ``invalid_transition``
* reused idempotency key        -> ``invalid_schema``         reason ``idempotency_key_reused``
* advisory connector            -> ``capability_unavailable`` reason ``advisory_connector``
* emergency disable             -> ``capability_unavailable`` reason ``emergency_disabled``
* permission recheck denied     -> ``forbidden``              reason ``permission_revoked``
* not the maker                 -> ``forbidden``              reason ``not_maker``
* maker approving own change    -> ``forbidden``              reason ``self_approval_prohibited``

Unknown intents raise :class:`IntentNotFoundError`, which is deliberately NOT a taxonomy error:
the API decides whether an unknown id is a 404 or a scope-hiding 403.
"""

from __future__ import annotations

from typing import Final

from neurosphere_core.errors import InvalidSchemaError, ValidationIssue

__all__ = [
    "ADVISORY_CONNECTOR",
    "CONFIRMATION_EXPIRED",
    "CONFIRMATION_HASH_MISMATCH",
    "EMERGENCY_DISABLED",
    "EXECUTION_CONTROL_UNAVAILABLE",
    "IDEMPOTENCY_KEY_REUSED",
    "INTENT_MODIFIED",
    "INTENT_STORE_UNAVAILABLE",
    "INVALID_TRANSITION",
    "NOT_MAKER",
    "PERMISSION_REVOKED",
    "POLICY_STORE_UNAVAILABLE",
    "SELF_APPROVAL_PROHIBITED",
    "TARGET_VERSION_CHANGED",
    "ActionValidationError",
    "IntentNotFoundError",
    "InvalidTransitionError",
]

ADVISORY_CONNECTOR: Final = "advisory_connector"
CONFIRMATION_EXPIRED: Final = "confirmation_expired"
CONFIRMATION_HASH_MISMATCH: Final = "confirmation_hash_mismatch"
EMERGENCY_DISABLED: Final = "emergency_disabled"
EXECUTION_CONTROL_UNAVAILABLE: Final = "execution_control_unavailable"
IDEMPOTENCY_KEY_REUSED: Final = "idempotency_key_reused"
INTENT_MODIFIED: Final = "intent_modified"
INTENT_STORE_UNAVAILABLE: Final = "intent_store_unavailable"
INVALID_TRANSITION: Final = "invalid_transition"
NOT_MAKER: Final = "not_maker"
PERMISSION_REVOKED: Final = "permission_revoked"
POLICY_STORE_UNAVAILABLE: Final = "policy_store_unavailable"
SELF_APPROVAL_PROHIBITED: Final = "self_approval_prohibited"
TARGET_VERSION_CHANGED: Final = "target_version_changed"


class ActionValidationError(InvalidSchemaError):
    """``invalid_schema`` (422) with a mandatory machine reason (the PRP's "validation_error")."""

    def __init__(
        self,
        reason: str,
        detail: str | None = None,
        *,
        errors: tuple[ValidationIssue, ...] | list[ValidationIssue] | None = None,
    ) -> None:
        super().__init__(detail, errors=errors, reason=reason)


class InvalidTransitionError(ActionValidationError):
    """A ``(from, to)`` pair that is not on the ``transitions.json`` allowlist."""

    def __init__(self, from_state: str, to_state: str) -> None:
        super().__init__(
            INVALID_TRANSITION, f"transition {from_state} -> {to_state} is not allowed"
        )
        self.from_state = from_state
        self.to_state = to_state


class IntentNotFoundError(LookupError):
    """No intent with that id in the caller's ``(customer_id, domain_id)`` partition."""
