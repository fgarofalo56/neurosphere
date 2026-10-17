"""Write path for connectors (PRP-09 item 6); imported explicitly, not by the SDK package root.

PRP-17's action executor depends on: ``WriteConnector``, ``WriteRequest`` and the result models,
``WriteTargetRegistry`` / ``register_write_target``, ``AdvisoryWriteMixin``. No Azure SDK import.
"""

from neurosphere_connector.write.advisory import AdvisoryWriteMixin
from neurosphere_connector.write.write_models import (
    ApplyResult,
    DryRunResult,
    OperationCheck,
    RollbackResult,
    VerifyResult,
    WriteRequest,
    check_diff_against_state,
)
from neurosphere_connector.write.write_protocol import WriteConnector, build_verify_result
from neurosphere_connector.write.write_registry import WriteTargetRegistry, register_write_target

__all__ = [
    "AdvisoryWriteMixin",
    "ApplyResult",
    "DryRunResult",
    "OperationCheck",
    "RollbackResult",
    "VerifyResult",
    "WriteConnector",
    "WriteRequest",
    "WriteTargetRegistry",
    "build_verify_result",
    "check_diff_against_state",
    "register_write_target",
]
