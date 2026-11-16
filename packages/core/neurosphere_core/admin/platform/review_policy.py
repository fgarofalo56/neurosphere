"""Stored human-review policy (PRP-44 item 1): conversion, safety rules, diff, loadable registry.

A :class:`ReviewPolicyDocument` (``admin_config`` kind ``review_policy``, id ``review-policy``)
converts to the inputs of :class:`~neurosphere_core.hitl.policy.ReviewPolicyRegistry`. Rules
beyond the contract (positive durations, expiry at most 90 days, ``max_escalations`` 0 to 10,
known approver permission):

* ``sla`` is at least 60 seconds;
* a ``maker_checker`` policy (default or per-action override) keeps ``self_approval_forbidden``
  true and its approver permission ``action.approve``: this API can never loosen maker-checker.

``LoadableReviewPolicyRegistry`` is an immutable registry that replaces its tables exactly once at
startup (no hot reload, A1); with nothing stored it equals ``ReviewPolicyRegistry()``.

Nothing here logs: a policy body is never a log field.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final

from neurosphere_contracts.admin.v1.review_policy_document import (
    ReviewPolicyDocument,
    ReviewPolicySettings,
)

from neurosphere_core.admin.store import AdminConfigRepository
from neurosphere_core.auth.scope.permissions import Permission
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from neurosphere_core.hitl.policy import (
    DEFAULT_POLICY_VERSION,
    ReviewPolicy,
    ReviewPolicyRegistry,
    default_policies,
)

__all__ = [
    "MIN_SLA_SECONDS",
    "REVIEW_POLICY_ID",
    "REVIEW_POLICY_KIND",
    "LoadableReviewPolicyRegistry",
    "PolicyAlreadyLoadedError",
    "PolicyChange",
    "StoredPolicies",
    "defaults_document",
    "diff_documents",
    "policies_from_document",
    "validate_review_policy",
]

REVIEW_POLICY_KIND: Final = "review_policy"
REVIEW_POLICY_ID: Final = "review-policy"
MIN_SLA_SECONDS: Final = 60
_MAKER_CHECKER: Final = "maker_checker"
_FIELDS: Final = (
    "self_approval_forbidden",
    "approver_permission",
    "assignment_timeout_seconds",
    "sla_seconds",
    "escalation_step_seconds",
    "max_escalations",
    "expiry_seconds",
)


class PolicyAlreadyLoadedError(RuntimeError):
    """``load`` was called a second time: the registry is applied once at startup."""


def _issue(pointer: str, detail: str, reason: str) -> InvalidSchemaError:
    return InvalidSchemaError(
        "review policy is invalid", errors=[ValidationIssue(pointer, detail)], reason=reason
    )


def _check_settings(pointer: str, kind: str, settings: ReviewPolicySettings) -> None:
    if settings.sla_seconds.root < MIN_SLA_SECONDS:
        raise _issue(f"{pointer}/sla_seconds", "sla must be at least 60 seconds", "sla_too_short")
    if kind == _MAKER_CHECKER:
        if not settings.self_approval_forbidden:
            raise _issue(
                f"{pointer}/self_approval_forbidden",
                "maker-checker never allows self approval",
                "maker_checker_loosened",
            )
        if settings.approver_permission != Permission.ACTION_APPROVE.value:
            raise _issue(
                f"{pointer}/approver_permission",
                "maker-checker needs action.approve",
                "maker_checker_loosened",
            )


def validate_review_policy(document: ReviewPolicyDocument) -> None:
    """Refuse a document that violates a rule the contract cannot express."""
    for index, default in enumerate(document.kind_defaults):
        _check_settings(f"/kind_defaults/{index}/policy", default.review_kind.root, default.policy)
    for index, override in enumerate(document.action_overrides):
        _check_settings(
            f"/action_overrides/{index}/policy", override.review_kind.root, override.policy
        )


def _policy(settings: ReviewPolicySettings, version: str) -> ReviewPolicy:
    return ReviewPolicy(
        self_approval_forbidden=settings.self_approval_forbidden,
        approver_permission=Permission(settings.approver_permission),
        assignment_timeout=timedelta(seconds=settings.assignment_timeout_seconds.root),
        sla=timedelta(seconds=settings.sla_seconds.root),
        escalation_step=timedelta(seconds=settings.escalation_step_seconds.root),
        max_escalations=settings.max_escalations,
        expiry=timedelta(seconds=settings.expiry_seconds.root),
        policy_version=version,
    )


@dataclass(frozen=True, slots=True)
class StoredPolicies:
    kind_defaults: dict[str, ReviewPolicy]
    action_overrides: dict[tuple[str, str], ReviewPolicy]


def policies_from_document(document: ReviewPolicyDocument) -> StoredPolicies:
    """The registry inputs for ``document`` (validated first)."""
    validate_review_policy(document)
    version = document.policy_version
    return StoredPolicies(
        kind_defaults={
            d.review_kind.root: _policy(d.policy, version) for d in document.kind_defaults
        },
        action_overrides={
            (o.review_kind.root, o.action_kind): _policy(o.policy, version)
            for o in document.action_overrides
        },
    )


def _settings(policy: ReviewPolicy) -> dict[str, Any]:
    return {
        "self_approval_forbidden": policy.self_approval_forbidden,
        "approver_permission": policy.approver_permission.value,
        "assignment_timeout_seconds": int(policy.assignment_timeout.total_seconds()),
        "sla_seconds": int(policy.sla.total_seconds()),
        "escalation_step_seconds": int(policy.escalation_step.total_seconds()),
        "max_escalations": policy.max_escalations,
        "expiry_seconds": int(policy.expiry.total_seconds()),
    }


def defaults_document(schema_version: str = "1.0.0") -> ReviewPolicyDocument:
    """The built-in defaults in document form (what applies when nothing is stored)."""
    return ReviewPolicyDocument.model_validate(
        {
            "schema_version": schema_version,
            "policy_version": DEFAULT_POLICY_VERSION,
            "kind_defaults": [
                {"review_kind": kind, "policy": _settings(policy)}
                for kind, policy in default_policies().items()
            ],
            "action_overrides": [],
        }
    )


@dataclass(frozen=True, slots=True)
class PolicyChange:
    """One changed value: a path under ``kind_defaults`` or ``action_overrides``."""

    path: str
    before: Any
    after: Any


def _flatten(document: ReviewPolicyDocument) -> dict[str, Any]:
    out: dict[str, Any] = {}
    entries: list[tuple[str, ReviewPolicySettings]] = [
        (f"kind_defaults/{d.review_kind.root}", d.policy) for d in document.kind_defaults
    ]
    entries += [
        (f"action_overrides/{o.review_kind.root}/{o.action_kind}", o.policy)
        for o in document.action_overrides
    ]
    for prefix, settings in entries:
        values = settings.model_dump(mode="json")
        for name in _FIELDS:
            value = values[name]
            out[f"{prefix}/{name}"] = value.get("root", value) if isinstance(value, dict) else value
    return out


def diff_documents(before: ReviewPolicyDocument, after: ReviewPolicyDocument) -> list[PolicyChange]:
    """Value-level changes between two documents (whole entries added or removed included)."""
    left, right = _flatten(before), _flatten(after)
    changes: list[PolicyChange] = []
    for path in sorted(left.keys() | right.keys()):
        if left.get(path) != right.get(path):
            changes.append(PolicyChange(path, left.get(path), right.get(path)))
    return changes


class LoadableReviewPolicyRegistry(ReviewPolicyRegistry):
    """A registry that holds the defaults until :meth:`load` replaces its tables exactly once."""

    def __init__(self) -> None:
        super().__init__()
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self, stored: StoredPolicies | None) -> None:
        """Apply ``stored`` (``None`` keeps the defaults); a second call raises."""
        if self._loaded:
            raise PolicyAlreadyLoadedError("review policy registry is already loaded")
        self._loaded = True
        if stored is not None:
            self._defaults = dict(stored.kind_defaults)
            self._overrides = dict(stored.action_overrides)

    async def load_from(self, repository: AdminConfigRepository, customer_id: str) -> bool:
        """Read the stored document and :meth:`load` it; True when a stored policy applied.

        A read failure propagates and leaves the registry unloaded (defaults stay in force).
        """
        if self._loaded:
            raise PolicyAlreadyLoadedError("review policy registry is already loaded")
        document = await repository.get(customer_id, REVIEW_POLICY_KIND, REVIEW_POLICY_ID)
        body = document.body if document is not None and document.status == "active" else None
        if not isinstance(body, ReviewPolicyDocument):
            self.load(None)
            return False
        self.load(policies_from_document(body))
        return True
