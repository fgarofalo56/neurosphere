"""Typed results for the write path (PRP-09 item 6).

Reuses the PRP-01 ``TargetRef`` and ``ProposedDiff`` contract types; the request/result envelopes
are SDK-local because no PRP-01 type models a connector-level dry-run/apply/verify/rollback
exchange (``ActionIntent`` is the executor's durable record, not a connector call).

``VerifyResult`` keeps the REQUESTED diff and the OBSERVED post-state apart and computes
``matched`` from per-operation checks, so a "pretend" change (metadata edited, real state
unchanged) shows up as a mismatch instead of a success.
"""

from __future__ import annotations

import re
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
# RFC 6901 array index: ASCII "0" or a non-zero-led ASCII digit run (no Unicode digits, no "00").
_ARRAY_INDEX = re.compile(r"(?:0|[1-9][0-9]*)", re.ASCII)
_MAX_INDEX_DIGITS = 18


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
    # Additive: False means the check could not be decided (never a silent match). ``matched`` is
    # always False for an unverifiable check; ``reason`` says why.
    verifiable: bool = True
    reason: str | None = None


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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def unverifiable_paths(self) -> tuple[str, ...]:
        """Paths whose check could not be decided (they also count as not matched)."""
        return tuple(c.path for c in self.checks if not c.verifiable)


class RollbackResult(_Model):
    """Outcome of undoing an applied change."""

    target: TargetRef
    status: Literal["rolled_back", "not_needed"]
    version_after: str | None = None


def _unescape(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _strict_equal(a: Any, b: Any) -> bool:
    """Equality without type coercion: ``True != 1`` and ``1 != 1.0`` (documented choice).

    Python's ``==`` treats ``True == 1 == 1.0``; for a write-verify that would let a wrong-typed
    observed value pass. Containers are compared recursively; mappings need identical key sets.
    """
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        return a.keys() == b.keys() and all(_strict_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_strict_equal(x, y) for x, y in zip(a, b, strict=True))
    if type(a) is not type(b):
        return False
    return bool(a == b)


def _lookup(state: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 pointer; returns the module sentinel when absent or malformed."""
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
            if len(token) > _MAX_INDEX_DIGITS or not _ARRAY_INDEX.fullmatch(token):
                return _MISSING
            idx = int(token)
            if idx >= len(cur):
                return _MISSING
            cur = cur[idx]
        else:
            return _MISSING
    return cur


def _unverifiable(op: PatchOperation, reason: str, observed: Any = None) -> OperationCheck:
    return OperationCheck(
        op=op.op, path=op.path, matched=False, observed=observed, verifiable=False, reason=reason
    )


def _check(
    op: PatchOperation, state: Mapping[str, Any], prior_state: Mapping[str, Any] | None
) -> OperationCheck:
    found = _lookup(state, op.path)
    present = found is not _MISSING
    observed = found if present else None
    if op.op in ("add", "replace", "test"):
        ok = present and _strict_equal(found, op.value)
    elif op.op == "remove":
        if not state:
            return _unverifiable(op, "empty_observed_state")
        ok = not present
    else:  # move / copy: the destination must equal the value that was moved or copied
        if op.from_ is None:
            return OperationCheck(op=op.op, path=op.path, matched=False, observed=observed)
        if prior_state is None:
            return _unverifiable(op, "prior_value_unknown", observed)
        prior = _lookup(prior_state, op.from_)
        if prior is _MISSING:
            return _unverifiable(op, "prior_value_absent", observed)
        ok = present and _strict_equal(found, prior)
        if op.op == "move":
            ok = ok and _lookup(state, op.from_) is _MISSING
        else:
            ok = ok and _strict_equal(_lookup(state, op.from_), prior)
    return OperationCheck(op=op.op, path=op.path, matched=ok, observed=observed)


def check_diff_against_state(
    diff: ProposedDiff,
    observed_state: Mapping[str, Any],
    *,
    prior_state: Mapping[str, Any] | None = None,
) -> tuple[OperationCheck, ...]:
    """Compare each requested operation with the state actually read back from the target.

    Comparison is type-strict (``True`` is not ``1``; ``1`` is not ``1.0``). ``prior_state`` is the
    target's state BEFORE the change: ``move``/``copy`` need it to prove the destination holds the
    moved/copied value rather than a stale pre-existing one; without it they are reported
    unverifiable (``verifiable=False``, ``matched=False``). ``remove`` against an empty observed
    state is also unverifiable, since absence is then not evidence of removal.
    """
    return tuple(_check(op, observed_state, prior_state) for op in diff.operations)
