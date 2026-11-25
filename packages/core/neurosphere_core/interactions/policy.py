"""Capture policy model, matcher and per-policy rate limit (PRP-103 item 1).

Capture is OFF unless every gate below passes, checked in this order; the first gate that fails
is the off reason (:data:`CaptureOffReason`), so status can say why capture is off:

1. ``setting_off``: the PRP-99 ``interaction_capture`` stored setting is absent or disabled;
2. ``retention_not_enabled``: the customer retention policy does not opt in to bodies or has no
   ``interaction_content`` rule (PRP-102 :func:`content_writes_enabled`, reused, not re-derived);
3. ``policy_limit_exceeded``: more than :data:`MAX_MATCHER_POLICIES` policies are stored, so
   the snapshot would be truncated; capture fails closed instead of matching a partial set;
4. ``no_policy``: no capture policy is stored;
5. ``not_approved``: no policy is ``active`` with an approving ``approved_audit_id``;
6. ``source_mismatch``: no active, approved policy names the producer's registered source;
7. ``domain_missing``: the event carries no ``domain_id`` (GD-46: never captured);
8. ``domain_mismatch``: no matching policy is for the event's domain;
9. ``not_sampled``: deterministic sampling (sha256 of the event id against ``sampling.rate``) left
   this event out, so a retry of the same event gets the same answer.

``sampling.max_per_minute`` is enforced by :class:`CaptureRateLimiter` (one token bucket per
policy, injectable clock), which the capture pipeline calls after a match; a refusal there is
shedding (``capture_shed``), not an off reason.

:class:`CapturePolicy` is the PRP-99 contract model plus the rules the generated model cannot
express (ADR-0004; the JSON Schema is not shipped in images): an ``active`` policy carries
``approved_intent_id`` and ``approved_audit_id``, ``kept_categories`` never holds a credential
category, ``parts`` and ``kept_categories`` are unique, and ``domain_id`` belongs to the
policy's cloud and customer. Error messages name fields and rules, never values.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal, Protocol, get_args

from neurosphere_contracts.admin.v1.system_setting import SystemSetting
from neurosphere_contracts.interactions.v1.capture_policy import (
    CapturePolicy as ContractCapturePolicy,
)
from pydantic import ConfigDict, ValidationError, model_validator

from neurosphere_core.classification.models import CREDENTIAL_CATEGORIES
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from neurosphere_core.interactions.store import content_writes_enabled
from neurosphere_core.lifecycle.policy import PolicyState


class _StoredPolicy(Protocol):
    @property
    def policy(self) -> CapturePolicy: ...


class _PolicyLister(Protocol):
    """What :meth:`CaptureMatcher.from_store` reads (any ``CapturePolicyStore`` satisfies it).

    Structural on purpose: ``policy_store`` imports this module, so importing it back here,
    even for typing only, would be a cyclic import.
    """

    async def list(
        self, *, customer_id: str | None = ..., limit: int = ...
    ) -> Sequence[_StoredPolicy]: ...


__all__ = [
    "CAPTURE_POLICY_ENTITY_TYPE",
    "CAPTURE_POLICY_SCHEMA_VERSION",
    "CAPTURE_SETTING_KEY",
    "MAX_MATCHER_POLICIES",
    "OFF_REASONS",
    "CaptureDecision",
    "CaptureMatch",
    "CaptureMatcher",
    "CaptureOffReason",
    "CapturePolicy",
    "CapturePolicyState",
    "CaptureRateLimiter",
    "capture_policy_canonical_id",
    "capture_setting_enabled",
    "is_sampled",
    "parse_capture_policy",
]

#: Contract version written on every stored policy (PRP-99 ``capture-policy`` 1.2.0).
CAPTURE_POLICY_SCHEMA_VERSION: Final = "1.2.0"
#: ``TargetRef.entity_type`` of a capture policy (PRP-99).
CAPTURE_POLICY_ENTITY_TYPE: Final = "capture_policy"
#: The PRP-99 stored setting that is the deployment-wide switch (clarification 8).
CAPTURE_SETTING_KEY: Final = "interaction_capture"
#: Upper bound on the policies one matcher snapshot holds.
MAX_MATCHER_POLICIES: Final = 500

CapturePolicyState = Literal["proposed", "active", "suspended", "retired"]
CaptureOffReason = Literal[
    "setting_off",
    "retention_not_enabled",
    "policy_limit_exceeded",
    "no_policy",
    "not_approved",
    "source_mismatch",
    "domain_missing",
    "domain_mismatch",
    "not_sampled",
]
#: Every off reason, in gate order.
OFF_REASONS: Final[tuple[CaptureOffReason, ...]] = get_args(CaptureOffReason)

_SAMPLE_SPACE: Final = float(1 << 64)


class CapturePolicy(ContractCapturePolicy):
    """PRP-99 ``CapturePolicy`` with the JSON Schema rules Pydantic ignores, frozen."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    @model_validator(mode="after")
    def _runtime_rules(self) -> CapturePolicy:
        if self.state == "active" and (
            self.approved_intent_id is None or self.approved_audit_id is None
        ):
            raise ValueError("an active policy requires approved_intent_id and approved_audit_id")
        kept = [c.root for c in self.kept_categories or []]
        if any(c in CREDENTIAL_CATEGORIES for c in kept):
            raise ValueError("kept_categories cannot hold a credential category")
        if len(set(kept)) != len(kept):
            raise ValueError("kept_categories must be unique")
        parts = [p.root for p in self.parts]
        if len(set(parts)) != len(parts):
            raise ValueError("parts must be unique")
        prefix = f"{self.cloud.root}:{self.customer_id.root}:"
        if not self.domain_id.root.startswith(prefix):
            raise ValueError("domain_id must belong to the policy cloud and customer")
        return self

    # -- convenience accessors (plain values, never content) --------------------------------

    @property
    def policy_id(self) -> str:
        return self.capture_policy_id.root

    @property
    def customer(self) -> str:
        return self.customer_id.root

    @property
    def domain(self) -> str:
        return self.domain_id.root

    @property
    def source_id_set(self) -> frozenset[str]:
        return frozenset(s.root for s in self.source_ids)

    @property
    def is_approved_active(self) -> bool:
        return self.state == "active" and self.approved_audit_id is not None


def _issues(exc: ValidationError) -> list[ValidationIssue]:
    """Pointers and error types only: Pydantic messages can echo input values."""
    issues: list[ValidationIssue] = []
    for err in exc.errors(include_url=False, include_input=False):
        loc = [str(p) for p in err.get("loc", ())]
        pointer = "/" + "/".join(loc) if loc else ""
        issues.append(ValidationIssue(pointer, str(err.get("type", "invalid"))))
    return issues


def parse_capture_policy(doc: object) -> CapturePolicy:
    """Validate a stored or proposed policy document; ``invalid_schema`` without values."""
    if isinstance(doc, CapturePolicy):
        return doc
    if isinstance(doc, ContractCapturePolicy):
        doc = doc.model_dump(mode="json")
    if not isinstance(doc, Mapping):
        raise InvalidSchemaError(
            "capture policy must be an object", reason="capture_policy_invalid"
        )
    try:
        return CapturePolicy.model_validate(dict(doc))
    except ValidationError as exc:
        raise InvalidSchemaError(
            "capture policy failed validation",
            errors=_issues(exc),
            reason="capture_policy_invalid",
        ) from None


def capture_policy_canonical_id(cloud: str, customer_id: str, policy_id: str) -> str:
    """``<cloud>:<customer>:neurosphere:capture_policy:<id>`` (PRP-99 target-id convention)."""
    return f"{cloud}:{customer_id}:neurosphere:{CAPTURE_POLICY_ENTITY_TYPE}:{policy_id}"


def capture_setting_enabled(setting: SystemSetting | None) -> bool:
    """True only for a present, enabled ``interaction_capture`` stored setting with its body."""
    return (
        setting is not None
        and setting.setting_key == CAPTURE_SETTING_KEY
        and setting.enabled is True
        and setting.interaction_capture is not None
    )


def is_sampled(event_id: str, rate: float) -> bool:
    """Deterministic: sha256(event id) as a fraction in [0, 1) compared with ``rate``."""
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    digest = hashlib.sha256(event_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / _SAMPLE_SPACE < rate


# --- decisions -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CaptureDecision:
    """Capture this event under ``policy`` (ids and limits only; never content)."""

    policy: CapturePolicy

    @property
    def capture_policy_id(self) -> str:
        return self.policy.policy_id

    @property
    def capture_policy_version(self) -> int:
        return self.policy.version

    @property
    def max_per_minute(self) -> int:
        return self.policy.sampling.max_per_minute


@dataclass(frozen=True, slots=True)
class CaptureMatch:
    """Result of one evaluation: a decision, or the off reason (exactly one is set)."""

    decision: CaptureDecision | None = None
    off_reason: CaptureOffReason | None = None

    def __post_init__(self) -> None:
        if (self.decision is None) == (self.off_reason is None):
            raise ValueError("exactly one of decision and off_reason is set")

    @property
    def captured(self) -> bool:
        return self.decision is not None


class CaptureMatcher:
    """Matches events against an immutable snapshot of stored policies.

    Built once (see :meth:`from_store`) and swapped on refresh; :meth:`match` does no I/O.
    """

    def __init__(
        self,
        policies: Iterable[CapturePolicy],
        *,
        setting_enabled: bool,
        retention: PolicyState | None,
    ) -> None:
        snapshot = sorted(policies, key=lambda p: (p.customer, p.policy_id))
        # Over the limit the snapshot cannot be complete: fail closed (hold nothing) with a
        # distinct reason rather than matching against a silently truncated set.
        self._over_limit = len(snapshot) > MAX_MATCHER_POLICIES
        if self._over_limit:
            snapshot = []
        self._policies: tuple[CapturePolicy, ...] = tuple(snapshot)
        self._approved: tuple[CapturePolicy, ...] = tuple(
            p for p in snapshot if p.is_approved_active
        )
        self._setting_enabled = setting_enabled is True
        self._retention_ok = retention is not None and content_writes_enabled(retention)

    @classmethod
    async def from_store(
        cls,
        store: _PolicyLister,
        *,
        setting_enabled: bool,
        retention: PolicyState | None,
        customer_id: str | None = None,
    ) -> CaptureMatcher:
        """Snapshot the policies in ``store`` (read once; refresh by building a new matcher)."""
        if not setting_enabled:
            # Nothing is read while the switch is off.
            return cls((), setting_enabled=False, retention=retention)
        # One more than the limit, so a truncated read is detected (policy_limit_exceeded).
        stored = await store.list(customer_id=customer_id, limit=MAX_MATCHER_POLICIES + 1)
        return cls((s.policy for s in stored), setting_enabled=setting_enabled, retention=retention)

    @property
    def policies(self) -> tuple[CapturePolicy, ...]:
        return self._policies

    def status(self) -> CaptureOffReason | None:
        """The deployment-wide off reason (gates 1-5), or ``None`` when some policy can match."""
        if not self._setting_enabled:
            return "setting_off"
        if not self._retention_ok:
            return "retention_not_enabled"
        if self._over_limit:
            return "policy_limit_exceeded"
        if not self._policies:
            return "no_policy"
        if not self._approved:
            return "not_approved"
        return None

    def evaluate(self, source_id: str, domain_id: str | None, event_id: str) -> CaptureMatch:
        """Every gate in order; the first that fails is the off reason."""
        off = self.status()
        if off is not None:
            return CaptureMatch(off_reason=off)
        by_source = [p for p in self._approved if source_id in p.source_id_set]
        if not by_source:
            return CaptureMatch(off_reason="source_mismatch")
        if not domain_id:
            return CaptureMatch(off_reason="domain_missing")
        by_domain = [p for p in by_source if p.domain == domain_id]
        if not by_domain:
            return CaptureMatch(off_reason="domain_mismatch")
        policy = by_domain[0]  # snapshot is sorted: deterministic when several match
        if not is_sampled(event_id, policy.sampling.rate):
            return CaptureMatch(off_reason="not_sampled")
        return CaptureMatch(decision=CaptureDecision(policy=policy))

    def match(self, source_id: str, domain_id: str | None, event_id: str) -> CaptureDecision | None:
        """The decision, or ``None`` when capture is off (see :meth:`evaluate` for why)."""
        return self.evaluate(source_id, domain_id, event_id).decision


# --- per-policy rate limit -----------------------------------------------------------------------


@dataclass(slots=True)
class _Bucket:
    capacity: float
    tokens: float
    updated: float


@dataclass
class CaptureRateLimiter:
    """``sampling.max_per_minute`` as one token bucket per policy (capacity = the per-minute cap,
    refilled continuously at cap / 60 per second). ``clock`` returns monotonic seconds.

    At most ``max_buckets`` policies are tracked; the least recently touched bucket is evicted.
    """

    clock: Callable[[], float] = time.monotonic
    # Must stay >= MAX_MATCHER_POLICIES (500): an evicted bucket comes back FULL, so evicting a
    # live policy's bucket would hand it a fresh minute of captures. 1024 leaves room for
    # policy churn across matcher refreshes; buckets are keyed by policy id only.
    max_buckets: int = 1024
    _buckets: dict[str, _Bucket] = field(default_factory=dict[str, _Bucket], init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def try_acquire(self, policy_id: str, max_per_minute: int) -> bool:
        """Take one token for ``policy_id``; ``False`` means shed this capture."""
        if max_per_minute < 1:
            return False
        capacity = float(max_per_minute)
        now = self.clock()
        with self._lock:
            bucket = self._buckets.pop(policy_id, None)
            if bucket is None:
                bucket = _Bucket(capacity=capacity, tokens=capacity, updated=now)
            else:
                elapsed = max(0.0, now - bucket.updated)
                bucket.capacity = capacity
                bucket.tokens = min(capacity, bucket.tokens + elapsed * capacity / 60.0)
                bucket.updated = now
            self._buckets[policy_id] = bucket  # re-insert: most recently used last
            while len(self._buckets) > max(1, self.max_buckets):
                del self._buckets[next(iter(self._buckets))]
            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True
            return False

    def try_acquire_for(self, decision: CaptureDecision) -> bool:
        return self.try_acquire(decision.capture_policy_id, decision.max_per_minute)
