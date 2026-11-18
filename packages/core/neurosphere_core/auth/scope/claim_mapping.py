"""Entra claim to NeuroSphere role mapping: model, strict parser and matcher (PRP-138).

One deployment-configured object (``NS_AUTH_ROLE_MAPPINGS``) maps Entra app role values (the
``roles`` claim) and, optionally, Entra group object ids (the ``groups`` claim) to existing
NeuroSphere roles. This module only parses that object and decides which entries a verified
token matches; scope derivation turns matches into time-bound role assignments.

Rules enforced here:

* Empty or unset configuration means the mapping is off (``None``); nothing reads any claim.
* The parser is strict and refuses with ``ClaimRoleMappingError`` carrying a short reason code
  and never the offending input value (the configuration may name group object ids).
* A token matches only when its issuer kind is in ``MAPPED_ISSUER_KINDS`` (``entra``; the dev
  issuer only when the caller allows it), its tenant and audience equal the mapping's, and it is
  a delegated user token (``identity_type != "app"`` and an ``scp`` claim is present).
* ``roles`` values match by exact string equality; ``groups`` values by lowercase GUID, and never
  when the token signals a group overage.

The module logs nothing and does no I/O.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Annotated, Any, Final, Literal, Protocol, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.jwt.config import normalize_tenant_id
from neurosphere_core.auth.scope.permissions import Role
from neurosphere_core.auth.scope.policy import CANONICAL_ID_PATTERN, CanonicalId
from neurosphere_core.scope import IdentityScope

__all__ = [
    "MAPPABLE_ROLES",
    "MAPPED_ISSUER_KINDS",
    "MAX_MAPPING_ENTRIES",
    "ClaimGrant",
    "ClaimGrantObserver",
    "ClaimKind",
    "ClaimRoleEntry",
    "ClaimRoleMapping",
    "ClaimRoleMappingError",
    "DomainDirectory",
    "matching_entries",
    "parse_claim_role_mapping",
]

#: Roles a claim may map to. Written out on purpose: a role added to ``Role`` later is not
#: mappable until someone adds it here deliberately (PRP-138 clarification 5).
MAPPABLE_ROLES: Final[frozenset[Role]] = frozenset(
    {
        Role.VIEWER,
        Role.ANALYST,
        Role.DOMAIN_STEWARD,
        Role.ADMIN,
        Role.SECURITY_AUDITOR,
    }
)
#: Issuer kinds whose claims may be mapped. Entra only (PRP-138 clarification 12); the local dev
#: issuer is accepted only when the caller passes ``allow_dev_issuer=True``.
MAPPED_ISSUER_KINDS: Final[frozenset[str]] = frozenset({"entra"})
MAX_MAPPING_ENTRIES: Final = 32
MAX_ENTRY_DOMAINS: Final = 1024
_DEV_ISSUER_KIND: Final = "dev"

ENTRY_ID_PATTERN: Final = r"^[a-z][a-z0-9-]{0,62}$"
ROLE_VALUE_PATTERN: Final = r"^[A-Za-z0-9._-]{1,120}$"
_ENTRY_ID = re.compile(ENTRY_ID_PATTERN)
_ROLE_VALUE = re.compile(ROLE_VALUE_PATTERN)
_CANONICAL = re.compile(CANONICAL_ID_PATTERN)
_DOMAIN_KIND_SEGMENT: Final = 3
_DOMAIN_KIND: Final = "domain"
_MAX_CANONICAL_LENGTH: Final = 512
_MAX_AUDIENCE_LENGTH: Final = 512

_TOP_KEYS: Final = frozenset({"tenant_id", "audience", "entries"})
_ENTRY_KEYS: Final = frozenset({"id", "claim", "value", "role", "domains", "customer_control"})

ClaimKind = Literal["roles", "groups"]
EntryId = Annotated[str, StringConstraints(pattern=ENTRY_ID_PATTERN)]


class ClaimRoleMappingError(ValueError):
    """The mapping configuration is refused. ``reason`` is a short code; no input is echoed."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"claim role mapping is invalid: {reason}")
        self.reason = reason


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClaimRoleEntry(_Frozen):
    """One mapping row. ``groups`` values are stored as lowercase canonical GUIDs."""

    id: EntryId
    claim: ClaimKind
    value: str = Field(min_length=1, max_length=120)
    role: Role
    domains: Literal["all"] | tuple[CanonicalId, ...]
    customer_control: bool


class ClaimRoleMapping(_Frozen):
    """The deployment's mapping, bound to exactly one tenant and one audience."""

    tenant_id: str = Field(min_length=36, max_length=36)
    audience: str = Field(min_length=1, max_length=_MAX_AUDIENCE_LENGTH)
    entries: tuple[ClaimRoleEntry, ...] = Field(min_length=1, max_length=MAX_MAPPING_ENTRIES)


class ClaimGrant(_Frozen):
    """A role applied to one derived scope because of a matched mapping entry."""

    entry_id: EntryId
    claim: ClaimKind
    role: Role
    domain_ids: tuple[CanonicalId, ...] = Field(min_length=1, max_length=MAX_ENTRY_DOMAINS)
    customer_control: bool
    expires_at: AwareDatetime


@runtime_checkable
class DomainDirectory(Protocol):
    """Active registered domain ids of one customer (resolved per call by the deriver)."""

    async def active_domain_ids(self, customer_id: str) -> tuple[str, ...]: ...


@runtime_checkable
class ClaimGrantObserver(Protocol):
    """Told about applied grants before the derivation is returned (the audit hook)."""

    async def on_claim_grants(
        self,
        scope: IdentityScope,
        grants: tuple[ClaimGrant, ...],
        issued_at: datetime,
        expires_at: datetime,
    ) -> None: ...


# --- parsing -------------------------------------------------------------------------------


def _refuse_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ClaimRoleMappingError("duplicate_key")
        result[key] = value
    return result


def _check_keys(obj: dict[str, Any], allowed: frozenset[str]) -> None:
    if set(obj) - allowed:
        raise ClaimRoleMappingError("unknown_key")
    if allowed - set(obj):
        raise ClaimRoleMappingError("missing_key")


def _guid(value: object, reason: str) -> str:
    if not isinstance(value, str):
        raise ClaimRoleMappingError(reason)
    try:
        return normalize_tenant_id(value)
    except ValueError:
        raise ClaimRoleMappingError(reason) from None


def _is_domain_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= _MAX_CANONICAL_LENGTH
        and _CANONICAL.fullmatch(value) is not None
        and value.split(":")[_DOMAIN_KIND_SEGMENT] == _DOMAIN_KIND
    )


def _domains(value: object) -> Literal["all"] | tuple[str, ...]:
    if value == "all":
        return "all"
    if not isinstance(value, list) or not value or len(value) > MAX_ENTRY_DOMAINS:
        raise ClaimRoleMappingError("invalid_domains")
    if not all(_is_domain_id(item) for item in value):
        raise ClaimRoleMappingError("invalid_domains")
    domains = tuple(str(item) for item in value)
    if len(set(domains)) != len(domains):
        raise ClaimRoleMappingError("invalid_domains")
    return domains


def _claim_value(claim: str, value: object) -> str:
    if claim == "groups":
        return _guid(value, "invalid_group_value")
    if not isinstance(value, str) or _ROLE_VALUE.fullmatch(value) is None:
        raise ClaimRoleMappingError("invalid_role_value")
    return value


def _entry(raw: object) -> ClaimRoleEntry:
    if not isinstance(raw, dict):
        raise ClaimRoleMappingError("invalid_entry")
    _check_keys(raw, _ENTRY_KEYS)
    entry_id = raw["id"]
    if not isinstance(entry_id, str) or _ENTRY_ID.fullmatch(entry_id) is None:
        raise ClaimRoleMappingError("invalid_entry_id")
    claim = raw["claim"]
    if claim not in ("roles", "groups"):
        raise ClaimRoleMappingError("invalid_claim_kind")
    value = _claim_value(claim, raw["value"])
    role_name = raw["role"]
    if not isinstance(role_name, str) or role_name not in {role.value for role in MAPPABLE_ROLES}:
        raise ClaimRoleMappingError("unmappable_role")
    domains = _domains(raw["domains"])
    customer_control = raw["customer_control"]
    if not isinstance(customer_control, bool):
        raise ClaimRoleMappingError("invalid_customer_control")
    return ClaimRoleEntry(
        id=entry_id,
        claim=claim,
        value=value,
        role=Role(role_name),
        domains=domains,
        customer_control=customer_control,
    )


def _audience(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or "*" in value
        or len(value) > _MAX_AUDIENCE_LENGTH
    ):
        raise ClaimRoleMappingError("invalid_audience")
    return value


def parse_claim_role_mapping(raw_json: str | None) -> ClaimRoleMapping | None:
    """Parse ``NS_AUTH_ROLE_MAPPINGS``. Unset, empty or blank means off (``None``).

    Raises ``ClaimRoleMappingError`` on any other defect; the error carries a reason code only.
    """
    if raw_json is None or not raw_json.strip():
        return None
    try:
        document = json.loads(raw_json, object_pairs_hook=_refuse_duplicate_keys)
    except ClaimRoleMappingError:
        raise
    except (ValueError, RecursionError):
        raise ClaimRoleMappingError("malformed_json") from None
    if not isinstance(document, dict):
        raise ClaimRoleMappingError("not_an_object")
    _check_keys(document, _TOP_KEYS)
    tenant_id = _guid(document["tenant_id"], "invalid_tenant_id")
    audience = _audience(document["audience"])
    raw_entries = document["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ClaimRoleMappingError("invalid_entries")
    if len(raw_entries) > MAX_MAPPING_ENTRIES:
        raise ClaimRoleMappingError("too_many_entries")
    entries = tuple(_entry(raw) for raw in raw_entries)
    seen_ids: set[str] = set()
    roles_by_value: dict[tuple[str, str], Role] = {}
    for entry in entries:
        if entry.id in seen_ids:
            raise ClaimRoleMappingError("duplicate_entry_id")
        seen_ids.add(entry.id)
        key = (entry.claim, entry.value)
        if roles_by_value.setdefault(key, entry.role) != entry.role:
            raise ClaimRoleMappingError("conflicting_value_role")
    return ClaimRoleMapping(tenant_id=tenant_id, audience=audience, entries=entries)


# --- matching ------------------------------------------------------------------------------


def _issuer_allowed(claims: VerifiedClaims, *, allow_dev_issuer: bool) -> bool:
    if claims.issuer_kind in MAPPED_ISSUER_KINDS:
        return True
    return allow_dev_issuer and claims.issuer_kind == _DEV_ISSUER_KIND


def _is_delegated_user(claims: VerifiedClaims) -> bool:
    # ``idtyp`` is optional in Entra tokens, so an app-only token is also recognised by the
    # absence of ``scp`` (PRP-138 clarification 10).
    return claims.identity_type != "app" and len(claims.scopes) > 0


def matching_entries(
    mapping: ClaimRoleMapping, claims: VerifiedClaims, *, allow_dev_issuer: bool
) -> tuple[ClaimRoleEntry, ...]:
    """Entries of ``mapping`` that ``claims`` matches, in mapping order; empty when not bound."""
    if not _issuer_allowed(claims, allow_dev_issuer=allow_dev_issuer):
        return ()
    if claims.tenant_id.lower() != mapping.tenant_id or claims.audience != mapping.audience:
        return ()
    if not _is_delegated_user(claims):
        return ()
    token_roles = frozenset(claims.roles)
    overage = bool(getattr(claims, "groups_overage", False))
    token_groups = frozenset() if overage else frozenset(g.lower() for g in claims.groups)
    matched: list[ClaimRoleEntry] = []
    for entry in mapping.entries:
        values = token_roles if entry.claim == "roles" else token_groups
        if entry.value in values:
            matched.append(entry)
    return tuple(matched)
