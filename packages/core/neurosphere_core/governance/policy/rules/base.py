"""Shared types of the governance rule evaluators (PRP-105 item 2).

An evaluator answers one closed, typed rule kind (PRP-99 ``PolicyRuleKind``) for one rule of one
policy. It reads only through its ports (catalog repository, subject metrics reader, PRP-73
``AccessEngine``, ``InteractionFindingReader``), never an interaction body, and never turns rule
text into a query or code: parameters come from the typed PRP-99 parameter models only.

Every evaluation runs under a :class:`RunBudget` (a subject budget plus a deadline). When the
budget stops the scan, the outcome says ``truncated`` with a reason, so the run never resolves a
violation it did not get to look at (PRP-105 gotcha "resolve only after a complete run").
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Final, Literal, Protocol, runtime_checkable

from neurosphere_contracts.policy.v1.policy_definition import (
    PolicyDefinition,
    PolicyRule,
)
from neurosphere_contracts.policy.v1.policy_violation import PolicyViolationEvidence
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError

from neurosphere_core.aggregates.subject import SubjectMetricsReader
from neurosphere_core.catalog.graph.access import AccessEngine
from neurosphere_core.catalog.protocol import CatalogRepository
from neurosphere_core.scope import IdentityScope

__all__ = [
    "MAX_FINDING_EVIDENCE",
    "EvidenceKind",
    "FindingEvidence",
    "RuleBuildContext",
    "RuleContext",
    "RuleEvaluationError",
    "RuleEvaluator",
    "RuleFinding",
    "RuleOutcome",
    "RunBudget",
    "ScopeProvider",
    "TruncationReason",
    "params_as",
]

MAX_FINDING_EVIDENCE: Final = 50
"""Evidence references per finding (the PRP-99 ``PolicyViolation.evidence`` ceiling)."""

TruncationReason = Literal["subject_budget", "time_budget", "source_truncated"]
"""Why a scan stopped early: the subject budget, the deadline, or a bounded source said so."""

EvidenceKind = Literal[
    "catalog_entity",
    "relation",
    "interaction_record",
    "aggregate_window",
    "audit_record",
    "telemetry_event",
    "budget_status",
]
"""The PRP-99 ``PolicyViolationEvidence.evidence_kind`` values."""

_REF = r"^[A-Za-z0-9._:/=-]{1,512}$"
_NAME = r"^[a-z0-9][a-z0-9_.:/-]{0,127}$"


class RuleEvaluationError(Exception):
    """An evaluator could not run a rule (wrong kind or parameters). Never a partial answer."""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason = reason


# --------------------------------------------------------------------------- findings


class FindingEvidence(BaseModel):
    """A reference to what showed the breach: an id, never content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: EvidenceKind
    ref: Annotated[StrictStr, Field(pattern=_REF)]

    def to_violation_evidence(self, observed_at: str) -> PolicyViolationEvidence:
        """The PRP-99 evidence entry, stamped with the run's observation time."""
        return PolicyViolationEvidence.model_validate(
            {"evidence_kind": self.kind, "ref": self.ref, "observed_at": observed_at}
        )


class RuleFinding(BaseModel):
    """One subject breaking one rule: ids, counts and category names only (no content).

    ``evidence_class`` is the last part of the violation ``dedup_key`` (policy id, rule id,
    subject canonical id, evidence class), so one breach is one violation however often it is
    seen. Evaluators merge everything they find for one (subject, evidence class) into one
    finding.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: Annotated[StrictStr, Field(max_length=512, pattern=_REF)]
    """Canonical id of the subject in violation."""
    subject_type: Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    """Entity type of the subject (``agent``, ``agent_version``, ``grounding_source``...)."""
    domain_id: StrictStr | None
    """Domain the subject lives in; ``None`` when no domain is known (never guessed)."""
    evidence_class: Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
    evidence: Annotated[tuple[FindingEvidence, ...], Field(min_length=1, max_length=50)]
    counts: dict[str, int] = Field(default_factory=dict)
    """Named counts (for example ``owners`` or a detected category); numbers only."""
    categories: tuple[Annotated[StrictStr, Field(pattern=_NAME)], ...] = ()
    """Category names (sensitivity or detected categories, approval states); never values."""


class RuleOutcome(BaseModel):
    """What one evaluation of one rule found, and whether it looked at everything."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: StrictStr
    findings: tuple[RuleFinding, ...] = ()
    truncated: bool = False
    reason: TruncationReason | None = None
    """Why the scan stopped early; ``None`` when ``truncated`` is False."""
    subjects_examined: int = 0


# --------------------------------------------------------------------------- budget


class RunBudget:
    """A subject budget and a deadline for ONE rule evaluation.

    ``take`` charges one examined subject (a catalog document, an edge or a subject point);
    ``expired`` checks the deadline. Either one, once hit, sets ``reason`` and stays hit, so an
    evaluator that stops reports ``truncated``. Create a fresh budget per (policy, rule).
    """

    def __init__(
        self,
        max_subjects: int,
        deadline: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_subjects < 1:
            raise ValueError("max_subjects must be at least 1")
        self.max_subjects = max_subjects
        self.deadline = deadline
        self._clock = clock
        self.used = 0
        self.reason: TruncationReason | None = None

    @classmethod
    def start(
        cls,
        max_subjects: int,
        seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> RunBudget:
        """A budget whose deadline is ``seconds`` from now on ``clock``."""
        return cls(max_subjects, clock() + seconds, clock=clock)

    @property
    def truncated(self) -> bool:
        return self.reason is not None

    @property
    def remaining_subjects(self) -> int:
        return max(0, self.max_subjects - self.used)

    @property
    def remaining_ms(self) -> int:
        return max(0, int((self.deadline - self._clock()) * 1000))

    def mark(self, reason: TruncationReason) -> None:
        """Record a truncation (the first reason wins)."""
        if self.reason is None:
            self.reason = reason

    def expired(self) -> bool:
        """True (and truncated) once the deadline has passed or a bound was already hit."""
        if self.reason is not None:
            return True
        if self._clock() >= self.deadline:
            self.mark("time_budget")
            return True
        return False

    def take(self, count: int = 1) -> bool:
        """Charge ``count`` subjects; False (and truncated) when that exceeds the budget."""
        if self.expired():
            return False
        if self.used + count > self.max_subjects:
            self.mark("subject_budget")
            return False
        self.used += count
        return True


# --------------------------------------------------------------------------- context


@dataclass(frozen=True)
class RuleContext:
    """Per-evaluation input: the caller's derived scope, the domains to look at, time, budget.

    ``domain_ids`` must already be inside ``scope`` (the run computes them from its own derived
    scope; evaluators never widen it, and the repository drops anything outside it anyway).
    """

    scope: IdentityScope
    domain_ids: tuple[str, ...]
    now: datetime
    budget: RunBudget


@runtime_checkable
class ScopeProvider(Protocol):
    """The worker's or API's derived scope (same shape as the publication recorder's)."""

    async def get(self) -> IdentityScope: ...


@dataclass(frozen=True)
class RuleBuildContext:
    """What a rule plugin's ``build(ctx)`` may use to assemble its evaluator.

    A plugin builds its own store from ``cosmos_client`` (``None`` on the memory backend) and
    edits nothing in this package.
    """

    catalog: CatalogRepository
    metrics: SubjectMetricsReader
    access: AccessEngine
    cosmos_client: object | None
    cloud: str
    scope_provider: ScopeProvider
    clock: Callable[[], datetime]


@runtime_checkable
class RuleEvaluator(Protocol):
    """Evaluates one rule kind. ``kind`` is a PRP-99 ``PolicyRuleKind`` value (open-ended)."""

    @property
    def kind(self) -> str: ...

    async def evaluate(
        self, ctx: RuleContext, policy: PolicyDefinition, rule: PolicyRule
    ) -> RuleOutcome: ...


# --------------------------------------------------------------------------- params


def params_as[ParamsT: BaseModel](rule: PolicyRule, model: type[ParamsT], kind: str) -> ParamsT:
    """The rule's parameters as the typed PRP-99 model of ``kind``.

    The generated ``PolicyRule.params`` is a union that Pydantic may resolve to another member
    when every field has a default, so the set fields are validated again against the model the
    kind pins. Raises ``RuleEvaluationError`` on a kind or parameter mismatch.
    """
    if rule.kind.root != kind:
        raise RuleEvaluationError("rule_kind_mismatch", f"evaluator {kind} got {rule.kind.root}")
    params = rule.params
    if isinstance(params, model):
        return params
    try:
        return model.model_validate(params.model_dump(mode="json", exclude_unset=True))
    except ValidationError as exc:
        raise RuleEvaluationError("invalid_rule_params", f"params do not fit {kind}") from exc


def unwrap(value: object) -> object:
    """Strip contract ``RootModel`` wrappers (some wrap twice) down to the plain value."""
    while hasattr(value, "root"):
        value = getattr(value, "root")  # noqa: B009 - ``value`` is typed ``object``
    return value


def text_of(value: object) -> str | None:
    """A plain string field value, or ``None``."""
    raw = unwrap(value)
    return None if raw is None else str(raw)


def strings_of(values: Sequence[object] | object | None) -> list[str]:
    """A list field (possibly wrapped) as plain strings."""
    raw = unwrap(values)
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(unwrap(v)) for v in raw]
    return []
