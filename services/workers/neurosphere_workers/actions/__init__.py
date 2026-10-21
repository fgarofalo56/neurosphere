"""Action executor worker (PRP-17 item 2): the single durable path that changes real systems.

Composition (the API's validate step only ever calls ``dry_run``; apply/rollback live here)::

    rechecker = PolicyPermissionRechecker(cloud=..., policy_repository=..., revocation_checker=...)
    service = ActionService(store, auditor=..., rechecker=rechecker, execution_control=control)
    registry = WriteTargetRegistry(); registry.register(foundry_swap_connector)
    executor = ActionExecutor(service, registry, execution_control=control, worker_id="exec-1")
    worker = ActionExecutorWorker(executor, store)
    await WorkerRunner(worker, checkpoint_store).run()
"""

from neurosphere_workers.actions.canary import CANARY_OUTCOMES, CanaryProbe, VerifyOnlyCanary
from neurosphere_workers.actions.completion import (
    FinishedHook,
    ReviewItemCompletion,
    ReviewItemOutcomes,
)
from neurosphere_workers.actions.executor import (
    APPLY_FAILED_RESTORE_FAILED,
    APPLY_FAILED_RESTORED,
    APPLY_NOT_OBSERVED,
    APPLY_WINDOW_OPEN,
    DEFAULT_LEASE,
    DEFAULT_LEASE_RENEWAL,
    DEFAULT_MAX_CONNECTOR_CALL,
    LEASE_LOST,
    ROLLBACK_FAILED,
    ActionExecutor,
    ExecutionReport,
    ReportOutcome,
)
from neurosphere_workers.actions.targets import DEFAULT_ACTION_CONNECTORS, resolve_connector
from neurosphere_workers.actions.worker import DEFAULT_BATCH_LIMIT, ActionExecutorWorker

__all__ = [
    "APPLY_FAILED_RESTORED",
    "APPLY_FAILED_RESTORE_FAILED",
    "APPLY_NOT_OBSERVED",
    "APPLY_WINDOW_OPEN",
    "CANARY_OUTCOMES",
    "DEFAULT_ACTION_CONNECTORS",
    "DEFAULT_BATCH_LIMIT",
    "DEFAULT_LEASE",
    "DEFAULT_LEASE_RENEWAL",
    "DEFAULT_MAX_CONNECTOR_CALL",
    "LEASE_LOST",
    "ROLLBACK_FAILED",
    "ActionExecutor",
    "ActionExecutorWorker",
    "CanaryProbe",
    "ExecutionReport",
    "FinishedHook",
    "ReportOutcome",
    "ReviewItemCompletion",
    "ReviewItemOutcomes",
    "VerifyOnlyCanary",
    "resolve_connector",
]
