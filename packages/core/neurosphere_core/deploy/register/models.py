"""Ownership register documents (PRP-08 item 5).

The register is the ONLY authority for what NeuroSphere may remove. Azure tags are planning
hints and are never read here. ``owner`` is a pseudonymous principal reference, never an email or
display name.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CREATED_BY_NEUROSPHERE: Final = "neurosphere"
_ARM_ID = re.compile(r"^/subscriptions/[^/\s]+(/[^/\s]+)*$", re.IGNORECASE)
_PSEUDONYM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,127}$")
_ID_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class Ownership(StrEnum):
    CREATED = "created"
    REUSED = "reused"
    SHARED = "shared"


def normalize_id(resource_id: str) -> str:
    """ARM ids are case-insensitive; compare on the lower-cased form."""
    return resource_id.rstrip("/").lower()


def _check_arm_id(value: str) -> str:
    if not _ARM_ID.fullmatch(value):
        raise ValueError("not an ARM resource id (expected /subscriptions/...)")
    return value


def _check_token(value: str) -> str:
    if not _ID_TOKEN.fullmatch(value):
        raise ValueError("invalid identifier")
    return value


def _check_owner(value: str) -> str:
    if not _PSEUDONYM.fullmatch(value):
        raise ValueError("owner must be a pseudonymous reference (no email or display name)")
    return value


def _check_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(None):
        raise ValueError("timestamp must be timezone-aware UTC")
    return value


class ResourceRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    deployment_id: str
    resource_id: str
    service: str = Field(min_length=1, max_length=64)
    ownership: Ownership
    created_by: str | None = None
    owner: str
    consent_reference: str | None = None
    dependents: tuple[str, ...] = ()
    creating_plan_id: str
    recorded_at: datetime

    @field_validator("deployment_id", "creating_plan_id")
    @classmethod
    def _v_tokens(cls, v: str) -> str:
        return _check_token(v)

    @field_validator("resource_id")
    @classmethod
    def _v_resource(cls, v: str) -> str:
        return _check_arm_id(v)

    @field_validator("dependents")
    @classmethod
    def _v_dependents(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for item in v:
            _check_arm_id(item)
        return v

    @field_validator("owner")
    @classmethod
    def _v_owner(cls, v: str) -> str:
        return _check_owner(v)

    @field_validator("recorded_at")
    @classmethod
    def _v_time(cls, v: datetime) -> datetime:
        return _check_utc(v)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.ownership is Ownership.CREATED:
            if self.created_by != CREATED_BY_NEUROSPHERE:
                raise ValueError("ownership=created requires created_by=neurosphere")
            if self.consent_reference is not None:
                raise ValueError("created rows carry no consent_reference")
        else:
            if self.created_by == CREATED_BY_NEUROSPHERE:
                raise ValueError("reused/shared rows cannot claim created_by=neurosphere")
            if not self.consent_reference:
                raise ValueError("reused/shared rows require a consent_reference")
        if normalize_id(self.resource_id) in {normalize_id(d) for d in self.dependents}:
            raise ValueError("a resource cannot depend on itself")
        return self


class ConsentRecord(BaseModel):
    """Consent to reuse/share existing resources (PRP-08 clarification 10)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    deployment_id: str
    consent_id: str
    owner: str
    resource_ids: tuple[str, ...] = Field(min_length=1)
    granted_at: datetime
    plan_id: str

    @field_validator("deployment_id", "consent_id", "plan_id")
    @classmethod
    def _v_ids(cls, v: str) -> str:
        return _check_token(v)

    @field_validator("owner")
    @classmethod
    def _v_owner(cls, v: str) -> str:
        return _check_owner(v)

    @field_validator("resource_ids")
    @classmethod
    def _v_resources(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for item in v:
            _check_arm_id(item)
        return v

    @field_validator("granted_at")
    @classmethod
    def _v_time(cls, v: datetime) -> datetime:
        return _check_utc(v)


class RegisterExport(BaseModel):
    """JSON export of one deployment's register (what the uninstall script reads)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    deployment_id: str
    rows: tuple[ResourceRow, ...] = ()
    consents: tuple[ConsentRecord, ...] = ()

    @model_validator(mode="after")
    def _same_deployment(self) -> Self:
        for item in (*self.rows, *self.consents):
            if item.deployment_id != self.deployment_id:
                raise ValueError("export mixes deployment ids")
        return self
