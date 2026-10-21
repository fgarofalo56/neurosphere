"""The single durable action plane core (PRP-17 item 1).

Connector-agnostic: nothing here imports a connector SDK, the API or the workers. Public surface:

* :mod:`~neurosphere_core.actions.state_machine` - the ``transitions.json`` allowlist.
* :func:`compute_confirmation_hash` - the PRP-01 confirmation hash (delta D1).
* :class:`StoredIntent` / :class:`ExecutionRecord` - the server-only envelope (delta D2).
* :class:`IntentStore` / :class:`InMemoryIntentStore` (``CosmosIntentStore`` and
  ``CosmosExecutionControl`` live in ``neurosphere_core.actions.cosmos_store``).
* :class:`ActionService` - the ONLY code that changes intent state.
* Ports implemented elsewhere: :class:`PermissionRechecker`, :class:`ActionAuditor`
  (default :class:`AuditRepositoryActionAuditor`), :class:`ExecutionControl`.
"""

from neurosphere_core.actions.audit import (
    ActionAuditEvent,
    ActionAuditor,
    AuditRepositoryActionAuditor,
    RecordingActionAuditor,
    action_audit_chain_id,
)
from neurosphere_core.actions.control import (
    ExecutionControl,
    ExecutionControlState,
    InMemoryExecutionControl,
    require_execution_enabled,
)
from neurosphere_core.actions.errors import (
    ActionValidationError,
    IntentNotFoundError,
    InvalidTransitionError,
)
from neurosphere_core.actions.hashing import (
    HASHED_FIELDS,
    compute_confirmation_hash,
    confirmation_hash_input,
    confirmation_hashes_equal,
    intent_to_wire,
    validate_proposed_diff,
)
from neurosphere_core.actions.models import (
    PHASE_ORDER,
    ActionCaller,
    CanaryOutcome,
    CreateOutcome,
    DraftRequest,
    ExecutionPhase,
    ExecutionRecord,
    IntentKey,
    StoredIntent,
    compute_payload_digest,
)
from neurosphere_core.actions.permissions import (
    GrantTablePermissionRechecker,
    PermissionRechecker,
)
from neurosphere_core.actions.service import (
    APPROVE_PERMISSION,
    DEFAULT_CONFIRMATION_TTL,
    EXECUTE_PERMISSION,
    ActionService,
)
from neurosphere_core.actions.state_machine import (
    ALLOWED_TRANSITIONS,
    INITIAL_STATE,
    TERMINAL_STATES,
    ActionStateName,
    assert_transition,
    can_transition,
    is_terminal,
)
from neurosphere_core.actions.store import InMemoryIntentStore, IntentStore

__all__ = [
    "ALLOWED_TRANSITIONS",
    "APPROVE_PERMISSION",
    "DEFAULT_CONFIRMATION_TTL",
    "EXECUTE_PERMISSION",
    "HASHED_FIELDS",
    "INITIAL_STATE",
    "PHASE_ORDER",
    "TERMINAL_STATES",
    "ActionAuditEvent",
    "ActionAuditor",
    "ActionCaller",
    "ActionService",
    "ActionStateName",
    "ActionValidationError",
    "AuditRepositoryActionAuditor",
    "CanaryOutcome",
    "CreateOutcome",
    "DraftRequest",
    "ExecutionControl",
    "ExecutionControlState",
    "ExecutionPhase",
    "ExecutionRecord",
    "GrantTablePermissionRechecker",
    "InMemoryExecutionControl",
    "InMemoryIntentStore",
    "IntentKey",
    "IntentNotFoundError",
    "IntentStore",
    "InvalidTransitionError",
    "PermissionRechecker",
    "RecordingActionAuditor",
    "StoredIntent",
    "action_audit_chain_id",
    "assert_transition",
    "can_transition",
    "compute_confirmation_hash",
    "compute_payload_digest",
    "confirmation_hash_input",
    "confirmation_hashes_equal",
    "intent_to_wire",
    "is_terminal",
    "require_execution_enabled",
    "validate_proposed_diff",
]
