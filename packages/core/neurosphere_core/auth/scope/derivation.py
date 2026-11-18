"""Server-side ``IdentityScope`` derivation from ``VerifiedClaims`` plus the policy store.

``ScopeDeriver.from_verified_claims(claims)`` is the only public way to obtain an
``IdentityScope`` (PRP-06 C8). Its sole per-request input is a ``VerifiedClaims`` built by the JWT
validator; request headers, query strings, bodies, cookies and model output are not parameters and
cannot reach it. Of the claims it reads only cloud, tenant id, object id, identity type, issued-at
and expiry; Entra role, group and scope claims are never authority (C5), with exactly one
exception (PRP-138): when the deployment configures an explicit ``ClaimRoleMapping``, a token whose
issuer is Entra (the dev issuer only when the deployment allows it, local only), whose tenant and
audience equal the ones the mapping is bound to, and which is a delegated user token (not
app-only, ``scp`` present) receives the mapped role for each matching ``roles`` value or
``groups`` object id (never on group overage). Such a role is time-bound to the token's expiry,
is never stored, and with no mapping configured no role or group claim is read at all.

Derivation, in order (any failure denies; nothing returns a partial or empty scope on error):

1. Cloud and tenant must equal this deployment's binding (else ``unauthorized``); an expired
   token is ``unauthorized``. ``customer_id`` comes from the deployment's tenant binding.
2. Principal id = HMAC pseudonym of tenant id + object id (C15).
3. Revocation hook (item 5): revoked -> ``forbidden``; checker failure -> ``dependency_transient``.
4. Policy head (version) and the principal's policy document, through the TTL cache (C14).
   Missing head or document = no stored grants. Store error or timeout = ``dependency_transient``.
5. Claim role mapping (only when configured, after 3 and 4): one assignment ``entra.<entry id>``
   per matched entry, on the entry's explicit domains or, for ``domains: "all"``, every active
   domain of the domain directory (TTL cache), plus the customer control domain when the entry
   says so. Directory missing or failing -> ``domain_directory_unavailable``; 1000 or more active
   domains -> ``role_mapping_domain_overflow`` (never truncated). An entry left with no domain
   grants nothing.
6. Role assignments: unexpired only, clipped to the principal's domain memberships (mapped
   assignments are not clipped: the mapping is the membership), and only domains of this cloud
   and customer. Grants: unexpired only, one named non-domain resource of this cloud and
   customer. Grants narrow; they never add a role or a domain (C7).
7. When mapped roles were applied and an observer is configured, it is awaited before the
   derivation is returned; its failure denies with ``audit_write_failed``.
"""

from __future__ import annotations

import asyncio
import functools
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Final

from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractIdentityScope
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from neurosphere_core.auth.jwt import Clock, VerifiedClaims
from neurosphere_core.auth.jwt.config import normalize_tenant_id
from neurosphere_core.auth.scope.cache import TtlCache
from neurosphere_core.auth.scope.claim_mapping import (
    MAX_ENTRY_DOMAINS,
    ClaimGrant,
    ClaimGrantObserver,
    ClaimRoleMapping,
    DomainDirectory,
    matching_entries,
)
from neurosphere_core.auth.scope.hashing import compute_scope_hash
from neurosphere_core.auth.scope.permissions import (
    Permission,
    customer_control_domain_id,
    role_permissions,
)
from neurosphere_core.auth.scope.policy import (
    CANONICAL_ID_PATTERN,
    NO_POLICY_VERSION,
    PolicyHead,
    PolicyRepository,
    PrincipalPolicy,
)
from neurosphere_core.auth.scope.pseudonym import PrincipalKind, PrincipalPseudonymizer
from neurosphere_core.auth.scope.revocation_hook import NoRevocationCheck, RevocationChecker
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import (
    DependencyTransientError,
    ForbiddenError,
    NeuroSphereError,
    UnauthorizedError,
)
from neurosphere_core.scope import IdentityScope

__all__ = [
    "DEFAULT_POLICY_CACHE_TTL_SECONDS",
    "DEFAULT_SCOPE_TTL_SECONDS",
    "DEFAULT_STORE_TIMEOUT_SECONDS",
    "MAPPED_ASSIGNMENT_PREFIX",
    "MAX_ALL_DOMAINS",
    "SCOPE_SCHEMA_VERSION",
    "ScopeDerivation",
    "ScopeDerivationConfig",
    "ScopeDeriver",
]

SCOPE_SCHEMA_VERSION: Final = "1.0.0"
DEFAULT_SCOPE_TTL_SECONDS: Final = 300
DEFAULT_POLICY_CACHE_TTL_SECONDS: Final = 30.0
DEFAULT_STORE_TIMEOUT_SECONDS: Final = 2.0
#: Assignment id prefix of a role applied from the claim role mapping (``entra.<entry id>``).
MAPPED_ASSIGNMENT_PREFIX: Final = "entra."
#: An ``all`` entry denies at this many active registry domains instead of truncating
#: (PRP-138 clarification 4; the registry lists at most 1000).
MAX_ALL_DOMAINS: Final = 1000
_CANONICAL = re.compile(CANONICAL_ID_PATTERN)
_MAX_CANONICAL_LENGTH: Final = 512


class ScopeDerivationConfig(BaseModel):
    """Deployment binding: one cloud, one tenant, one customer (never request-supplied)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cloud: CloudName
    tenant_id: str
    customer_id: Annotated[str, StringConstraints(pattern=r"^[a-z0-9._-]{1,128}$")]
    scope_ttl_seconds: int = Field(default=DEFAULT_SCOPE_TTL_SECONDS, ge=1, le=3600)
    policy_cache_ttl_seconds: float = Field(default=DEFAULT_POLICY_CACHE_TTL_SECONDS, gt=0, le=300)
    store_timeout_seconds: float = Field(default=DEFAULT_STORE_TIMEOUT_SECONDS, gt=0, le=30)
    cache_max_entries: int = Field(default=4096, ge=1, le=100_000)

    @field_validator("tenant_id")
    @classmethod
    def _tenant_guid(cls, value: str) -> str:
        return normalize_tenant_id(value)


@dataclass(frozen=True, slots=True)
class ScopeDerivation:
    """Derived scope plus the policy record ids it used (for audit; not part of the contract)."""

    scope: IdentityScope
    assignment_ids: tuple[str, ...]
    grant_ids: tuple[str, ...]
    #: Roles applied from the claim role mapping (PRP-138); empty when none matched or off.
    claim_grants: tuple[ClaimGrant, ...] = ()


def _ts(value: datetime) -> str:
    value = value.astimezone(UTC)
    fraction = f".{value.microsecond:06d}" if value.microsecond else ""
    return value.strftime("%Y-%m-%dT%H:%M:%S") + fraction + "Z"


def _segments(canonical_id: str) -> list[str]:
    return canonical_id.split(":")


def _invalid_policy(detail: str) -> DependencyTransientError:
    return DependencyTransientError(detail, reason="policy_document_invalid", upstream_invalid=True)


def _directory_unavailable(*, upstream_invalid: bool = False) -> DependencyTransientError:
    return DependencyTransientError(
        "domain directory unavailable",
        reason="domain_directory_unavailable",
        upstream_invalid=upstream_invalid,
    )


def _domain_overflow() -> DependencyTransientError:
    return DependencyTransientError(
        "too many domains for a mapped role", reason="role_mapping_domain_overflow"
    )


def _is_domain_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= _MAX_CANONICAL_LENGTH
        and _CANONICAL.fullmatch(value) is not None
        and _segments(value)[3] == "domain"
    )


class ScopeDeriver:
    def __init__(
        self,
        config: ScopeDerivationConfig,
        *,
        policy_repository: PolicyRepository,
        pseudonymizer: PrincipalPseudonymizer,
        revocation_checker: RevocationChecker,
        clock: Clock = time.time,
        claim_mapping: ClaimRoleMapping | None = None,
        domain_directory: DomainDirectory | None = None,
        claim_grant_observer: ClaimGrantObserver | None = None,
        allow_dev_issuer: bool = False,
    ) -> None:
        # Required on purpose: ``None`` would silently skip revocation. Opting out is
        # ``NoRevocationCheck()`` so it is visible where the deriver is built.
        if not isinstance(revocation_checker, RevocationChecker):
            raise TypeError(
                "revocation_checker is required; pass a RevocationChecker or NoRevocationCheck()"
            )
        if claim_mapping is not None and not isinstance(claim_mapping, ClaimRoleMapping):
            raise TypeError("claim_mapping must be a parsed ClaimRoleMapping or None")
        if domain_directory is not None and not isinstance(domain_directory, DomainDirectory):
            raise TypeError("domain_directory must implement DomainDirectory or be None")
        if claim_grant_observer is not None and not isinstance(
            claim_grant_observer, ClaimGrantObserver
        ):
            raise TypeError("claim_grant_observer must implement ClaimGrantObserver or be None")
        if not isinstance(allow_dev_issuer, bool):
            raise TypeError("allow_dev_issuer must be a bool")
        self._config = config
        self._repo = policy_repository
        self._pseudonymizer = pseudonymizer
        self._revocation = revocation_checker
        self._clock = clock
        self._claim_mapping = claim_mapping
        self._directory = domain_directory
        self._observer = claim_grant_observer
        self._allow_dev_issuer = allow_dev_issuer
        cache_args: dict[str, Any] = {
            "ttl_seconds": config.policy_cache_ttl_seconds,
            "max_entries": config.cache_max_entries,
            "clock": clock,
        }
        self._heads: TtlCache[str, PolicyHead | None] = TtlCache(**cache_args)
        self._principals: TtlCache[tuple[str, str, str], PrincipalPolicy | None] = TtlCache(
            **cache_args
        )
        # Active registry domains per customer, for ``domains: "all"`` entries. Same TTL as the
        # policy cache; only successful, validated loads are cached.
        self._domains: TtlCache[str, tuple[str, ...]] = TtlCache(**cache_args)

    @property
    def config(self) -> ScopeDerivationConfig:
        return self._config

    # ------------------------------------------------------------------ public API

    async def from_verified_claims(self, claims: VerifiedClaims) -> IdentityScope:
        """Derive the caller's scope. The only input is a validator-built ``VerifiedClaims``."""
        return (await self.derive(claims)).scope

    async def derive(self, claims: VerifiedClaims) -> ScopeDerivation:
        if not isinstance(claims, VerifiedClaims):
            raise TypeError("scope derivation accepts only VerifiedClaims from the JWT validator")
        cfg = self._config
        now = datetime.fromtimestamp(self._clock(), UTC)
        if claims.cloud is not cfg.cloud:
            raise UnauthorizedError("token cloud does not match deployment", reason="cloud")
        if claims.tenant_id.lower() != cfg.tenant_id:
            raise UnauthorizedError("token tenant does not match deployment", reason="tenant")
        if claims.is_expired_at(now):
            raise UnauthorizedError("token expired", reason="expired")

        kind: PrincipalKind = "service_principal" if claims.identity_type == "app" else "user"
        principal_id = self._pseudonymizer.principal_id(
            cloud=cfg.cloud,
            customer_id=cfg.customer_id,
            tenant_id=cfg.tenant_id,
            object_id=claims.object_id,
            kind=kind,
        )
        await self._check_revocation(principal_id, claims.issued_at)

        customer = cfg.customer_id
        head = await self._heads.get_or_load(
            customer, functools.partial(self._guarded, self._repo.get_policy_head, customer)
        )
        if head is not None and head.customer_id != customer:
            raise _invalid_policy("policy head belongs to another customer")
        version = head.policy_version if head is not None else NO_POLICY_VERSION
        policy: PrincipalPolicy | None = None
        if head is not None:
            policy = await self._principals.get_or_load(
                (customer, version, principal_id),
                functools.partial(
                    self._guarded, self._repo.get_principal_policy, customer, principal_id
                ),
            )
        if policy is not None and (
            policy.customer_id != customer or policy.principal_id != principal_id
        ):
            raise _invalid_policy("policy document belongs to another principal")
        if self._claim_mapping is None:
            return self._build(claims, principal_id, kind, version, policy, now)
        mapped = await self._claim_grants(self._claim_mapping, claims)
        derivation = self._build(claims, principal_id, kind, version, policy, now, mapped)
        observer = self._observer
        if mapped and observer is not None:
            await self._notify(observer, derivation.scope, mapped, claims)
        return derivation

    def invalidate_principal(self, principal_id: str) -> int:
        """Drop cached policy documents for one principal (revocation cache hook, item 5)."""
        return self._principals.discard_where(lambda key: key[2] == principal_id)

    def invalidate_all(self) -> None:
        self._heads.clear()
        self._principals.clear()
        self._domains.clear()

    # ------------------------------------------------------------------ internals

    async def _guarded[T](self, call: Callable[..., Awaitable[T]], *args: str) -> T:
        try:
            async with asyncio.timeout(self._config.store_timeout_seconds):
                return await call(*args)
        except DependencyTransientError:
            raise
        except Exception as exc:
            raise DependencyTransientError(
                "policy store unavailable", reason="policy_store_unavailable"
            ) from exc

    async def _check_revocation(self, principal_id: str, issued_at: datetime) -> None:
        if isinstance(self._revocation, NoRevocationCheck):
            return
        try:
            async with asyncio.timeout(self._config.store_timeout_seconds):
                revoked = await self._revocation.is_revoked(principal_id, issued_at)
        except NeuroSphereError:
            raise
        except Exception as exc:
            raise DependencyTransientError(
                "revocation check unavailable", reason="revocation_unavailable"
            ) from exc
        if revoked is False:
            return
        if revoked is True:
            raise ForbiddenError("principal access revoked", reason="principal_revoked")
        raise DependencyTransientError(
            "revocation check returned an invalid answer",
            reason="revocation_unavailable",
            upstream_invalid=True,
        )

    def _owned(self, canonical_id: str, *, domain: bool) -> bool:
        cloud, customer, _source, type_, _id = _segments(canonical_id)
        if cloud != self._config.cloud.value or customer != self._config.customer_id:
            return False
        return (type_ == "domain") is domain

    async def _claim_grants(
        self, mapping: ClaimRoleMapping, claims: VerifiedClaims
    ) -> tuple[ClaimGrant, ...]:
        """Roles the mapping confers on ``claims`` (issuer, tenant, audience: the matcher's)."""
        entries = matching_entries(mapping, claims, allow_dev_issuer=self._allow_dev_issuer)
        if not entries:
            return ()
        cfg = self._config
        registry: tuple[str, ...] = ()
        if any(entry.domains == "all" for entry in entries):
            registry = await self._active_domains()
        control = customer_control_domain_id(cfg.cloud.value, cfg.customer_id)
        grants: list[ClaimGrant] = []
        for entry in entries:
            candidates = set(registry if entry.domains == "all" else entry.domains)
            if entry.customer_control:
                candidates.add(control)
            domains = sorted(d for d in candidates if self._owned(d, domain=True))
            if not domains:
                continue  # grants nothing; never an assignment without a domain
            if len(domains) > MAX_ENTRY_DOMAINS:
                raise _domain_overflow()
            grants.append(
                ClaimGrant(
                    entry_id=entry.id,
                    claim=entry.claim,
                    role=entry.role,
                    domain_ids=tuple(domains),
                    customer_control=entry.customer_control,
                    expires_at=claims.expires_at,
                )
            )
        return tuple(grants)

    async def _active_domains(self) -> tuple[str, ...]:
        directory = self._directory
        if directory is None:
            raise _directory_unavailable()
        customer = self._config.customer_id
        domains = await self._domains.get_or_load(
            customer, functools.partial(self._load_domains, directory, customer)
        )
        if len(domains) >= MAX_ALL_DOMAINS:
            raise _domain_overflow()
        return domains

    async def _load_domains(self, directory: DomainDirectory, customer: str) -> tuple[str, ...]:
        try:
            async with asyncio.timeout(self._config.store_timeout_seconds):
                raw: object = await directory.active_domain_ids(customer)
        except Exception as exc:
            raise _directory_unavailable() from exc
        if not isinstance(raw, (tuple, list)):
            raise _directory_unavailable(upstream_invalid=True)
        items: list[object] = list(raw)  # pyright: ignore[reportUnknownArgumentType]
        if not all(_is_domain_id(item) for item in items):
            raise _directory_unavailable(upstream_invalid=True)
        return tuple(sorted({str(item) for item in items}))

    async def _notify(
        self,
        observer: ClaimGrantObserver,
        scope: IdentityScope,
        grants: tuple[ClaimGrant, ...],
        claims: VerifiedClaims,
    ) -> None:
        try:
            async with asyncio.timeout(self._config.store_timeout_seconds):
                await observer.on_claim_grants(scope, grants, claims.issued_at, claims.expires_at)
        except Exception as exc:
            raise DependencyTransientError(
                "claim role audit unavailable", reason="audit_write_failed"
            ) from exc

    def _build(
        self,
        claims: VerifiedClaims,
        principal_id: str,
        kind: PrincipalKind,
        version: str,
        policy: PrincipalPolicy | None,
        now: datetime,
        mapped: tuple[ClaimGrant, ...] = (),
    ) -> ScopeDerivation:
        cfg = self._config
        expiries: list[datetime] = [
            now + timedelta(seconds=cfg.scope_ttl_seconds),
            claims.expires_at,
        ]
        roles: list[dict[str, Any]] = []
        readable: set[str] = set()
        resources: list[dict[str, Any]] = []
        assignment_ids: list[str] = []
        grant_ids: list[str] = []

        if policy is not None:
            members = {d for d in policy.domain_memberships if self._owned(d, domain=True)}
            for assignment in policy.role_assignments:
                if assignment.expires_at is not None and now >= assignment.expires_at:
                    continue
                domains = sorted(members.intersection(assignment.domain_ids))
                if not domains:
                    continue
                role: dict[str, Any] = {"role": assignment.role.value, "domain_ids": domains}
                if assignment.expires_at is not None:
                    role["expires_at"] = _ts(assignment.expires_at)
                    expiries.append(assignment.expires_at)
                roles.append(role)
                assignment_ids.append(assignment.assignment_id)
                if Permission.DATA_READ in role_permissions(assignment.role):
                    readable.update(domains)
            for grant in policy.grants:
                if now >= grant.expires_at or not self._owned(grant.resource_id, domain=False):
                    continue
                resources.append(
                    {
                        "resource_id": grant.resource_id,
                        "permissions": sorted(set(grant.permissions)),
                        "expires_at": _ts(grant.expires_at),
                    }
                )
                expiries.append(grant.expires_at)
                grant_ids.append(grant.grant_id)

        # Claim-mapped roles (PRP-138): already filtered by ``_owned``; not clipped to the stored
        # memberships (the mapping is the membership); time-bound to the token.
        for mapped_grant in mapped:
            domains = list(mapped_grant.domain_ids)
            roles.append(
                {
                    "role": mapped_grant.role.value,
                    "domain_ids": domains,
                    "expires_at": _ts(mapped_grant.expires_at),
                }
            )
            expiries.append(mapped_grant.expires_at)
            assignment_ids.append(MAPPED_ASSIGNMENT_PREFIX + mapped_grant.entry_id)
            if Permission.DATA_READ in role_permissions(mapped_grant.role):
                readable.update(domains)

        doc: dict[str, Any] = {
            "schema_version": SCOPE_SCHEMA_VERSION,
            "cloud": cfg.cloud.value,
            "customer_id": cfg.customer_id,
            "principal": {
                "principal_id": principal_id,
                "principal_pseudonym": principal_id.rsplit(":", 1)[-1],
                "principal_kind": kind,
            },
            "roles": sorted(roles, key=_role_sort_key),
            "allowed_domains": sorted(readable),
            "allowed_resources": sorted(resources, key=_grant_sort_key),
            "policy_version": version,
            "derived_at": _ts(now),
            "expires_at": _ts(min(expiries)),
        }
        doc["scope_hash"] = compute_scope_hash(doc)
        try:
            contract = ContractIdentityScope.model_validate(doc)
        except ValidationError as exc:
            raise _invalid_policy("derived scope violates the contract") from exc
        return ScopeDerivation(
            scope=IdentityScope._from_verified_contract(contract),
            assignment_ids=tuple(sorted(assignment_ids)),
            grant_ids=tuple(sorted(grant_ids)),
            claim_grants=mapped,
        )


def _role_sort_key(role: dict[str, Any]) -> tuple[str, tuple[str, ...], str]:
    return (role["role"], tuple(role["domain_ids"]), role.get("expires_at", ""))


def _grant_sort_key(grant: dict[str, Any]) -> tuple[str, tuple[str, ...], str]:
    return (grant["resource_id"], tuple(grant["permissions"]), grant["expires_at"])
