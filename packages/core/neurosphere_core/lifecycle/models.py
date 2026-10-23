"""Value types for the data lifecycle engine (PRP-23 item 1).

All models are frozen and ``extra="forbid"``. Export requests deliberately carry no domain or
customer id: the scope comes from the server-derived ``IdentityScope`` and a body that tries to
supply one is rejected at validation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import IntEnum, StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

Token = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")]
Container = Annotated[str, StringConstraints(min_length=1, max_length=128)]
RecordId = Annotated[str, StringConstraints(min_length=1, max_length=512)]
SubjectId = Annotated[str, StringConstraints(min_length=1, max_length=256)]
MAX_EXPORT_RECORDS = 500


class Rule(IntEnum):
    """Conflict precedence. A lower number always wins over a higher one."""

    AUDIT_IMMUTABILITY = 1
    LEGAL_HOLD = 2
    MIN_RETENTION = 3
    SUBJECT_REQUEST = 4
    MAX_RETENTION_EXPIRY = 5


class ActionKind(StrEnum):
    EXPIRE = "expire"
    DELETE = "delete"
    PSEUDONYMIZE = "pseudonymize"
    ERASE_SUBJECT = "erase_subject"
    EXPORT = "export"


class JobStatus(StrEnum):
    COMPLETED = "completed"
    QUEUED = "queued"
    REFUSED = "refused"
    FAILED = "failed"
    NOT_DUE = "not_due"


class Effect(StrEnum):
    """What actually happened. Pseudonymization is never reported as deletion."""

    NONE = "none"
    DELETED = "deleted"
    PSEUDONYMIZED = "pseudonymized"
    MAPPING_DESTROYED = "mapping_destroyed"
    EXPORTED = "exported"


class LawfulBasis(StrEnum):
    CONSENT = "consent"
    CONTRACT = "contract"
    LEGAL_OBLIGATION = "legal_obligation"
    VITAL_INTERESTS = "vital_interests"
    PUBLIC_TASK = "public_task"
    LEGITIMATE_INTERESTS = "legitimate_interests"
    LEGAL_PROCESS = "legal_process"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TargetRef(_Frozen):
    """Names a record in a store. The engine re-checks audit identity; labels are not trusted."""

    target_kind: Token
    container: Container
    record_id: RecordId


class TargetRecord(_Frozen):
    """What an adapter reports about one record (metadata only, never a body)."""

    record_id: RecordId
    data_class: Token
    created_at: AwareDatetime
    subject_id: SubjectId | None = None
    doc_type: str | None = None
    customer_id: str | None = None
    domain_id: str | None = None
    pseudonymized: bool = False


class LifecycleRequest(_Frozen):
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action: ActionKind
    target: TargetRef | None = None
    subject_id: SubjectId | None = None

    @model_validator(mode="after")
    def _shape(self) -> LifecycleRequest:
        if self.action is ActionKind.EXPORT:
            raise ValueError("export uses ExportRequest")
        if self.action is ActionKind.ERASE_SUBJECT:
            if self.subject_id is None:
                raise ValueError("erase_subject requires subject_id")
        elif self.target is None:
            raise ValueError(f"{self.action.value} requires a target")
        return self

    @property
    def dedupe_key(self) -> str:
        target = self.target
        where = (
            "" if target is None else f"{target.target_kind}|{target.container}|{target.record_id}"
        )
        return f"{self.action.value}|{where}|{self.subject_id or ''}"


class LifecycleOutcome(_Frozen):
    request_id: str
    action: ActionKind
    status: JobStatus
    reason: str
    governing_rule: Rule | None = None
    blocked_by: Rule | None = None
    effect: Effect = Effect.NONE
    verified: bool = False
    #: True/False when a mapping store is configured; None when it could not be determined.
    reidentifiable: bool | None = None
    policy_status: Literal["set", "unset"] = "unset"
    not_before: datetime | None = None


class LegalHold(_Frozen):
    """A hold selects by any combination of fields; every given selector must match."""

    hold_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    reason_code: Token
    target_kind: Token | None = None
    record_id: RecordId | None = None
    subject_id: SubjectId | None = None
    data_class: Token | None = None
    #: Principal pseudonyms allowed to export held data.
    custodians: tuple[str, ...] = ()
    placed_at: AwareDatetime

    @model_validator(mode="after")
    def _has_selector(self) -> LegalHold:
        if not (self.target_kind or self.record_id or self.subject_id or self.data_class):
            raise ValueError("a legal hold needs at least one selector")
        return self


class ExportRequest(_Frozen):
    lawful_basis: LawfulBasis
    target_kind: Token
    container: Container
    record_ids: tuple[RecordId, ...] = Field(min_length=1, max_length=MAX_EXPORT_RECORDS)


class ExportItem(_Frozen):
    record_id: RecordId
    data_class: Token
    content: dict[str, object]


class ExportResult(_Frozen):
    status: JobStatus
    reason: str
    items: tuple[ExportItem, ...] = ()
    withheld_out_of_scope: int = 0
    withheld_held: int = 0
    effect: Effect = Effect.NONE
