"""Judge availability (capability matrix) and judge approval (classification and boundary).

Both are pure and fail closed. Availability is read from the matrix; a Government config never
resolves to a Commercial row. Approval is checked before any judge call, not after.
"""

from __future__ import annotations

from neurosphere_core.capabilities import CapabilityMatrix
from neurosphere_core.evaluation.registry.models import (
    Cloud,
    JudgeConfig,
    normalize_classification,
)

__all__ = ["judge_approval", "judge_availability"]


def judge_availability(config: JudgeConfig, matrix: CapabilityMatrix) -> tuple[bool, str]:
    """``(enabled, reason)``; an unavailable judge is disabled with a reason, never rerouted."""
    if config.judge_kind == "programmatic":
        return True, "programmatic scorer runs in-process; no model endpoint required"
    row_id = config.capability_row_id
    if row_id is None:
        return False, "no capability_row_id: judge availability cannot be established"
    row = matrix.by_id(row_id)
    if row is None:
        return False, f"capability row {row_id!r} not found in the capability matrix"
    if row.cloud != config.cloud:
        return (
            False,
            f"capability row {row_id!r} is a {row.cloud} row; judge config is {config.cloud} "
            "(never bridged across clouds)",
        )
    if row.availability != "available":
        return False, f"capability row {row_id!r} availability is {row.availability}, not available"
    return True, f"capability row {row_id!r} is available in {config.cloud}"


def judge_approval(
    config: JudgeConfig, classification: str | None, cloud: Cloud
) -> tuple[bool, str]:
    """``(approved, reason)`` for sending data of ``classification`` in ``cloud`` to ``config``.

    Null or unrecognised classifications are treated as ``restricted`` (fail closed).
    """
    if config.cloud != cloud:
        return False, f"judge config cloud {config.cloud} does not match data cloud {cloud}"
    effective = normalize_classification(classification)
    if effective not in config.approved_classifications:
        return False, f"judge config is not approved for classification {effective}"
    return True, f"judge config is approved for classification {effective} in {cloud}"
