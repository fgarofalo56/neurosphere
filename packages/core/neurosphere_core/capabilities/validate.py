"""Validate a deployment profile against the capability matrix (NS-07, NS-08).

Output is "disabled with reason", never a guess: every requested capability, in every
requested region, resolves to ``supported`` or ``disabled``. A ``disabled`` result carries a
PRP-01 ``ProblemDetails`` (code ``capability_unavailable``, HTTP 409), a human-readable
``reason`` naming the matrix row id and source, and a ``cause``:

* ``unavailable`` - a row says the capability is not offered (or only in preview, and the
  profile does not allow preview);
* ``unverified`` - no row speaks for the combination, the row says ``unverified``, or the
  SKU cannot be resolved. Never ``supported``.

Availability, GA and authorization stay separate: ``supported`` means the row says
``available``. ``ga_status`` ``unverified`` is surfaced as a warning and
``authorization_scope`` is passed through verbatim as a citation; neither is a claim that
NeuroSphere or the service is authorized for any agency.

Mapping of profile choices to matrix (service, feature) keys:

* hosting ``aks`` -> (``aks``, ``base``); ``appservice`` -> (``app_service``, ``base``).
* analytics ``fabric`` | ``synapse`` | ``databricks`` -> (<backend>, ``base``).
* optional features are explicit (service, feature[, sku]) requests.

The shipped matrix has no ``aks`` or ``app_service`` rows, so hosting choices resolve
``unverified`` (disabled) until rows with sources are added; no rows are invented here.

Resolution rules:

* only rows of the profile's own cloud are ever consulted, so a Government profile can never
  resolve a Commercial row and vice versa; there is no cross-cloud fallback;
* region precedence: exact region, then the cloud's ``*`` wildcard (named regions of that
  cloud only, as ``capability_region_covers`` in tests/contracts/validators.py), then the
  cloud's ``global`` row (a non-regional offering). ``global`` is its own row;
* SKU: a requested SKU matches a row for that SKU, else a SKU-independent row; with no SKU
  requested only a SKU-independent row applies, and SKU-specific rows alone resolve
  ``unverified`` (the SKU is a customer input that must not be silently chosen);
* staleness (``observed_on`` older than 90 days) adds a warning and ``stale`` flag only; it
  never changes a status.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from functools import cache
from typing import Literal, Self

from neurosphere_contracts.deployment.v1.capability_matrix_entry import CapabilityMatrixEntry
from neurosphere_contracts.errors.v1.problem_details import ProblemDetails
from pydantic import BaseModel, ConfigDict, Field, model_validator

from neurosphere_core.capabilities.loader import CapabilityMatrix, load_matrix, observed_date

STALE_AFTER_DAYS = 90
DEFAULT_CORRELATION_ID = "capability-matrix-validation"

Cloud = Literal["commercial", "government"]
Hosting = Literal["aks", "appservice"]
Analytics = Literal["fabric", "synapse", "databricks"]
Kind = Literal["hosting", "analytics", "feature"]
Status = Literal["supported", "disabled"]
Cause = Literal["unavailable", "unverified"]

HOSTING_KEYS: dict[str, tuple[str, str]] = {
    "aks": ("aks", "base"),
    "appservice": ("app_service", "base"),
}
ANALYTICS_KEYS: dict[str, tuple[str, str]] = {
    "fabric": ("fabric", "base"),
    "synapse": ("synapse", "base"),
    "databricks": ("databricks", "base"),
}

_GOV_REGION_RE = re.compile(r"^us(gov|dod)[a-z0-9]+$")
_REGION_RE = re.compile(r"^[a-z][a-z0-9]{2,39}$")


class FeatureRequest(BaseModel):
    """An optional feature the deployment wants (for example a Foundry model or CMK)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    service: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    feature: str = Field(pattern=r"^[a-z][a-z0-9_]{1,127}$")
    sku: str | None = Field(default=None, min_length=1, max_length=128)


class DeploymentProfile(BaseModel):
    """What the operator asks for at deployment (PRD NS-07)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cloud: Cloud
    regions: tuple[str, ...] = Field(min_length=1)
    hosting: Hosting
    analytics: Analytics
    features: tuple[FeatureRequest, ...] = ()
    allow_preview: bool = False

    @model_validator(mode="after")
    def _regions_belong_to_cloud(self) -> Self:
        for region in self.regions:
            if not _REGION_RE.match(region):
                raise ValueError(f"region {region!r} must be a lowercase ARM region name")
            if region == "global":
                raise ValueError("global is a matrix row, not a deployable region")
            is_gov = bool(_GOV_REGION_RE.match(region))
            if (self.cloud == "government") != is_gov:
                raise ValueError(f"region {region!r} does not belong to cloud {self.cloud!r}")
        if len(set(self.regions)) != len(self.regions):
            raise ValueError("regions must be unique")
        return self


class CapabilityResult(BaseModel):
    """Outcome for one requested capability in one region."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability: str
    kind: Kind
    service: str
    feature: str
    sku: str | None
    region: str
    status: Status
    cause: Cause | None = None
    reason: str | None = None
    reason_code: str | None = None
    row_id: str | None = None
    source_url: str | None = None
    observed_on: str | None = None
    authorization_scope: str | None = None
    stale: bool = False
    warnings: tuple[str, ...] = ()
    error: ProblemDetails | None = None


class ProfileResult(BaseModel):
    """Result of ``validate_profile``; consumed by the PRP-08 plan and UI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cloud: Cloud
    regions: tuple[str, ...]
    evaluated_on: str
    results: tuple[CapabilityResult, ...]

    @property
    def supported(self) -> bool:
        """True only when every capability is supported in every region."""
        return all(r.status == "supported" for r in self.results)

    @property
    def disabled(self) -> tuple[CapabilityResult, ...]:
        return tuple(r for r in self.results if r.status == "disabled")

    @property
    def stale(self) -> tuple[CapabilityResult, ...]:
        return tuple(r for r in self.results if r.stale)

    @property
    def warnings(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for result in self.results:
            for warning in result.warnings:
                seen.setdefault(warning)
        return tuple(seen)


@cache
def default_matrix() -> CapabilityMatrix:
    """The shipped matrix, loaded once."""
    return load_matrix()


def _region_rank(row_region: str, cloud: str, region: str) -> int | None:
    """0 exact, 1 cloud wildcard, 2 global row; None when the row does not speak for it."""
    if row_region == region:
        return 0
    if row_region == "*":
        # Mirrors capability_region_covers: * covers named regions of its own cloud only.
        is_gov_region = region.startswith(("usgov", "usdod"))
        return 1 if (is_gov_region if cloud == "government" else not is_gov_region) else None
    if row_region == "global":
        return 2
    return None


def _norm_sku(sku: str | None) -> str | None:
    return None if sku is None else sku.strip().lower()


def _resolve(
    matrix: CapabilityMatrix, service: str, feature: str, cloud: str, region: str, sku: str | None
) -> tuple[CapabilityMatrixEntry | None, str | None]:
    """Best row for the request, or (None, why-not). Only same-cloud rows are considered."""
    ranked: dict[int, list[CapabilityMatrixEntry]] = {}
    for row in matrix.rows:
        if row.service != service or row.feature != feature or row.cloud != cloud:
            continue
        rank = _region_rank(row.region, cloud, region)
        if rank is not None:
            ranked.setdefault(rank, []).append(row)
    want = _norm_sku(sku)
    sku_note: str | None = None
    for rank in sorted(ranked):
        group = ranked[rank]
        if want is not None:
            exact = [r for r in group if _norm_sku(r.sku) == want]
            if exact:
                return exact[0], None
        independent = [r for r in group if r.sku is None]
        if independent:
            return independent[0], None
        ids = ", ".join(r.id for r in group)
        sku_note = (
            f"SKU {sku!r} is not covered by rows {ids}"
            if want is not None
            else f"a SKU must be chosen; the matrix only has SKU-specific rows ({ids})"
        )
    return None, sku_note


def _is_stale(row: CapabilityMatrixEntry, today: date) -> bool:
    return (today - observed_date(row)).days > STALE_AFTER_DAYS


def _problem(
    reason: str, reason_code: str, correlation_id: str, instance: str | None
) -> ProblemDetails:
    return ProblemDetails(
        schema_version="1.0.0",
        type="https://neurosphere.invalid/problems/capability_unavailable",
        title="Capability unavailable",
        status=409,
        code="capability_unavailable",
        retryable=False,
        correlation_id=correlation_id,
        reason=reason_code,
        detail=reason,
        instance=instance,
    )


def _evaluate(
    matrix: CapabilityMatrix,
    kind: Kind,
    service: str,
    feature: str,
    sku: str | None,
    cloud: str,
    region: str,
    allow_preview: bool,
    today: date,
    correlation_id: str,
) -> CapabilityResult:
    capability = f"{kind}:{service}.{feature}" + (f"#{sku}" if sku else "")
    base = {
        "capability": capability,
        "kind": kind,
        "service": service,
        "feature": feature,
        "sku": sku,
        "region": region,
    }
    row, why = _resolve(matrix, service, feature, cloud, region, sku)
    status: Status = "disabled"
    cause: Cause | None = None
    reason: str | None = None
    code: str | None = None
    warnings: list[str] = []
    if row is None:
        cause, code = "unverified", "not_verified"
        reason = (
            f"No capability-matrix row for {service}.{feature} in {cloud} {region}"
            + (f" ({why})" if why else "")
            + "; unverified, so disabled. Availability must be verified from a cited source."
        )
        return _finish(base, status, cause, reason, code, None, correlation_id, warnings, today)
    where = f"row {row.id} (source {row.source_url}, observed {row.observed_on})"
    preview = row.availability == "preview" or row.ga_status == "preview"
    if row.availability == "unavailable":
        cause = "unavailable"
        code = (
            "not_available_in_region"
            if row.region not in ("global", "*")
            else ("not_available_in_cloud")
        )
        reason = f"{service}.{feature} is not available in {cloud} {region} per {where}."
    elif row.availability == "unverified":
        cause, code = "unverified", "not_verified"
        reason = (
            f"{service}.{feature} availability in {cloud} {region} is unverified per {where}; "
            "disabled until verified."
        )
    elif preview and not allow_preview:
        cause, code = "unavailable", "preview_only"
        reason = (
            f"{service}.{feature} is preview only in {cloud} {region} per {where}; "
            "the profile does not allow preview."
        )
    else:
        status = "supported"
        if preview:
            warnings.append(f"preview: {service}.{feature} is preview per row {row.id}")
        if row.ga_status == "unverified":
            warnings.append(f"ga_unverified: GA status of {service}.{feature} is unverified")
    return _finish(base, status, cause, reason, code, row, correlation_id, warnings, today)


def _finish(
    base: dict[str, object],
    status: Status,
    cause: Cause | None,
    reason: str | None,
    code: str | None,
    row: CapabilityMatrixEntry | None,
    correlation_id: str,
    warnings: list[str],
    today: date,
) -> CapabilityResult:
    stale = row is not None and _is_stale(row, today)
    if row is not None and stale:
        age = (today - observed_date(row)).days
        warnings.append(
            f"stale: row {row.id} observed {row.observed_on} is {age} days old "
            f"(>{STALE_AFTER_DAYS}); re-verify against {row.source_url}"
        )
    error = None
    if status == "disabled" and reason is not None and code is not None:
        error = _problem(reason, code, correlation_id, None)
    return CapabilityResult.model_validate(
        {
            **base,
            "status": status,
            "cause": cause,
            "reason": reason,
            "reason_code": code,
            "row_id": row.id if row else None,
            "source_url": row.source_url if row else None,
            "observed_on": row.observed_on if row else None,
            "authorization_scope": row.authorization_scope if row else None,
            "stale": stale,
            "warnings": tuple(warnings),
            "error": error,
        }
    )


def validate_profile(
    profile: DeploymentProfile,
    matrix: CapabilityMatrix | None = None,
    today: date | None = None,
    correlation_id: str = DEFAULT_CORRELATION_ID,
) -> ProfileResult:
    """Resolve hosting, analytics backend and optional features in every region.

    ``matrix`` defaults to the shipped data; ``today`` (UTC) drives the staleness warning.
    """
    matrix = matrix if matrix is not None else default_matrix()
    today = today or datetime.now(UTC).date()
    requests: list[tuple[Kind, str, str, str | None]] = [
        ("hosting", *HOSTING_KEYS[profile.hosting], None),
        ("analytics", *ANALYTICS_KEYS[profile.analytics], None),
        *(("feature", f.service, f.feature, f.sku) for f in profile.features),
    ]
    results = tuple(
        _evaluate(
            matrix,
            kind,
            service,
            feature,
            sku,
            profile.cloud,
            region,
            profile.allow_preview,
            today,
            correlation_id,
        )
        for region in profile.regions
        for kind, service, feature, sku in requests
    )
    return ProfileResult(
        cloud=profile.cloud,
        regions=profile.regions,
        evaluated_on=today.isoformat(),
        results=results,
    )
