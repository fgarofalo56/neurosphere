"""Human-in-the-loop review workflow (PRP-17 item 3).

Review items with an allowlisted state table, per-kind review policies, an ETag-conditional
store, an append-only audit-backed decision log, maker-checker separation on real principal ids,
stub notifiers that only record, and pure timer evaluation over stored deadlines. This package
records review state and decisions; it never executes or transitions an action.
"""

from neurosphere_core.hitl.auditing import SYSTEM_ACTOR, SYSTEM_SCOPE_HASH, audit_chain_for
from neurosphere_core.hitl.authz import ReviewerAuthorizer
from neurosphere_core.hitl.decisions import (
    DecisionLog,
    DecisionStore,
    ImmutableDecision,
    InMemoryDecisionStore,
    decision_digest,
)
from neurosphere_core.hitl.models import (
    DECIDABLE_STATES,
    FINAL_STATES,
    INSIGHT_KINDS,
    REVIEW_TRANSITIONS,
    ReviewItem,
    ReviewKind,
    ReviewStateName,
    is_allowed_transition,
    review_kind_for,
    transition,
)
from neurosphere_core.hitl.notify import (
    EmailNotifierStub,
    Notification,
    NotificationEvent,
    NotificationReceipt,
    Notifier,
    TeamsNotifierStub,
)
from neurosphere_core.hitl.policy import (
    DEFAULT_POLICY_VERSION,
    ReviewPolicy,
    ReviewPolicyRegistry,
    default_policies,
)
from neurosphere_core.hitl.service import HitlService, TimerOutcome
from neurosphere_core.hitl.store import HitlStore, InMemoryHitlStore
from neurosphere_core.hitl.timers import (
    TimerAction,
    TimerKind,
    apply_timer_action,
    evaluate_timers,
)

__all__ = [
    "DECIDABLE_STATES",
    "DEFAULT_POLICY_VERSION",
    "FINAL_STATES",
    "INSIGHT_KINDS",
    "REVIEW_TRANSITIONS",
    "SYSTEM_ACTOR",
    "SYSTEM_SCOPE_HASH",
    "DecisionLog",
    "DecisionStore",
    "EmailNotifierStub",
    "HitlService",
    "HitlStore",
    "ImmutableDecision",
    "InMemoryDecisionStore",
    "InMemoryHitlStore",
    "Notification",
    "NotificationEvent",
    "NotificationReceipt",
    "Notifier",
    "ReviewItem",
    "ReviewKind",
    "ReviewPolicy",
    "ReviewPolicyRegistry",
    "ReviewStateName",
    "ReviewerAuthorizer",
    "TeamsNotifierStub",
    "TimerAction",
    "TimerKind",
    "TimerOutcome",
    "apply_timer_action",
    "audit_chain_for",
    "decision_digest",
    "default_policies",
    "evaluate_timers",
    "is_allowed_transition",
    "review_kind_for",
    "transition",
]
