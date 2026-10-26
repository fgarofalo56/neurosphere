"""Worker runtime: lifecycle, graceful drain, checkpoints, backoff, health and role supervision.

The role builders live in ``runtime.factories`` (not imported here: they import the worker
classes, which import this package).
"""

from neurosphere_workers.runtime.backoff import BackoffPolicy, retry_with_backoff
from neurosphere_workers.runtime.checkpoint import CheckpointStore, InMemoryCheckpointStore
from neurosphere_workers.runtime.health import HealthServer
from neurosphere_workers.runtime.roles import (
    ROLE_NAMES,
    RoleConfigError,
    UnknownRoleError,
    parse_roles,
)
from neurosphere_workers.runtime.signals import install_signal_handlers
from neurosphere_workers.runtime.supervisor import RoleSupervisor
from neurosphere_workers.runtime.worker import (
    Batch,
    BatchOutcome,
    IdleWorker,
    Worker,
    WorkerRunner,
)

__all__ = [
    "ROLE_NAMES",
    "BackoffPolicy",
    "Batch",
    "BatchOutcome",
    "CheckpointStore",
    "HealthServer",
    "IdleWorker",
    "InMemoryCheckpointStore",
    "RoleConfigError",
    "RoleSupervisor",
    "UnknownRoleError",
    "Worker",
    "WorkerRunner",
    "install_signal_handlers",
    "parse_roles",
    "retry_with_backoff",
]
