"""Typed results for the write path (PRP-09 item 6).

Reuses the PRP-01 ``TargetRef`` and ``ProposedDiff`` contract types; the request/result envelopes
are SDK-local because no PRP-01 type models a connector-level dry-run/apply/verify/rollback
exchange (``ActionIntent`` is the executor's durable record, not a connector call).

``VerifyResult`` keeps the REQUESTED diff and the OBSERVED post-state apart and computes
``matched`` from per-operation checks, so a "pretend" change (metadata edited, real state
unchanged) shows up as a mismatch instead of a success.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from pydantic import BaseModel, ConfigDict, Field, computed_field

__all__ = [
    "ApplyResult",
    "DryRunResult",
    "OperationCheck",
    "RollbackResult",
    "VerifyResult",
    "WriteRequest",
    "check_diff_against_state",
]

_MISSING = object()


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WriteRequest(_Model):
    """What the executor asks a connector to do: exact target, version and diff."""

    target: TargetRef
    target_version: str = Field(min_length=1, max_length=256)
    proposed_diff: ProposedDiff


class DryRunResult(_Model):
    """Planned change, computed against ``target_version`` of ``target``; nothing was written."""

    target: TargetRef
    target_version: str = Field(min_length=1, max_length=256)
    planned_diff: ProposedDiff
    would_change: bool


class ApplyResult(_Model):
    """A real change was made. ``version_after`` is the target's new version/ETag if known."""

    target: TargetRef
    version_before: str = Field(min_length=1, max_length=256)
    version_after: str | None = None
    applied_diff: ProposedDiff
    rollback_token: str | None = Field(default=None, max_length=1024)


class OperationCheck(_Model):
    """One requested operation compared with the observed state."""

    op: str
    path: str
    matched: bool
    observed: Any | None = None


class VerifyResult(_Model):
    """Observed post-state next to the requested diff, with a computed match."""

    target: TargetRef
    requested_diff: ProposedDiff
    observed_state: dict[str, Any]
    observed_version: str | None = None
    checks: tuple[OperationCheck, ...]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def matched(self) -> bool:
        """True only when every requested operation is visible in the observed state."""
        return all(c.matched for c in self.checks)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def mismatched_paths(self) -> tuple[str, ...]:
        return tuple(c.path for c in self.checks if not c.matched)


class RollbackResult(_Model):
    """Outcome of undoing an applied change."""

    target: TargetRef
    status: Literal["rolled_back", "not_needed"]
    version_after: str | None = None


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _lookup(state: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 pointer; returns the module sentinel when absent."""
    cur = state
    if pointer == "":
        return cur
    for raw in pointer.split("/")[1:]:
        token = _unescape(raw)
        if isinstance(cur, Mapping):
            if token not in cur:
                return _MISSING
            cur = cur[token]
        elif isinstance(cur, list):
            if not token.isdigit() or int(token) >= len(cur):
                return _MISSING
            cur = cur[int(token)]
        else:
            return _MISSING
    return cur


def _check(op: PatchOperation, state: Mapping[str, Any]) -> OperationCheck:
    found = _lookup(state, op.path)
    present = found is not _MISSING
    observed = found if present else None
    if op.op in ("add", "replace", "test"):
        ok = present and found == op.value
    elif op.op == "remove":
        ok = not present
    elif op.op == "move":
        ok = present and op.from_ is not None and _lookup(state, op.from_) is _MISSING
    else:  # copy
        ok = present and op.from_ is not None and _lookup(state, op.from_) == found
    return OperationCheck(op=op.op, path=op.path, matched=ok, observed=observed)


def check_diff_against_state(
    diff: ProposedDiff, observed_state: Mapping[str, Any]
) -> tuple[OperationCheck, ...]:
    """Compare each requested operation with the state actually read back from the target."""
    return tuple(_check(op, observed_state) for op in diff.operations)
