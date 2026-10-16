"""Pure reuse/create/skip planner and its projection to the PRP-01 ``DeploymentManifest``.

No ARM or HTTP call happens here: the planner consumes a prior :class:`ScanResponse`, the
capability matrix, operator choices, consent records and a versioned price table.

Rules (each is enforced in code and covered by ``tests/deployment/test_plan.py``):

1. *Shared* rule: a discovered resource is **NeuroSphere-created** only when it carries the tag
   ``neurosphere:created-by`` with value ``neurosphere`` (``CREATED_BY_TAG``); every other
   discovered resource is *shared*. Reusing a shared resource needs a **granted** consent record
   naming a pseudonymous owner principal and listing that resource id; otherwise the item is
   ``needs_consent``, never ``reuse``.
2. *Residency*: reuse needs the resource location to be one of the profile regions (which the
   profile validator already pins to the profile cloud). A Government profile therefore can never
   reuse a Commercial-region resource. On failure the item falls back to the operator's
   ``fallback`` (``create`` by default, or ``skip``) with the reason recorded.
3. *Capability matrix*: hosting / analytics / feature requests the matrix marks disabled become
   ``disabled`` items carrying the matrix reason, code and source; they are never ``create``.
4. *Cost*: ``create`` is ``estimated`` from the price table when an entry exists, else
   ``unknown`` with a ``None`` amount; ``reuse`` / ``skip`` / ``needs_consent`` / ``disabled``
   add nothing and are ``no_incremental_cost``. Unknown is never ``0``.

Checks that need live data (sku fit, network reachability, quota, permission, lifecycle) are
``unknown`` here, never ``pass``; only residency is derivable from scan data.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from neurosphere_contracts.deployment.v1.deployment_manifest import DeploymentManifest
from neurosphere_core.capabilities import (
    CapabilityMatrix,
    CapabilityResult,
    DeploymentProfile,
    validate_profile,
)

from neurosphere_api.deploy.plan.models import (
    DeploymentPlan,
    OwnerConsentRecord,
    PlanCheck,
    PlanCost,
    PlanItem,
    PlanRequest,
    PriceTable,
    ServiceChoice,
)
from neurosphere_api.deploy.scan import DiscoveredResource

#: Tag marking a resource NeuroSphere created (Clarification 12: ``created_by=neurosphere``).
CREATED_BY_TAG = "neurosphere:created-by"
CREATED_BY_VALUE = "neurosphere"

#: Scan category -> manifest service.
CATEGORY_SERVICE: dict[str, str] = {
    "apim": "api_management",
    "model_endpoint": "model_endpoint",
    "key_vault": "key_vault",
    "monitoring": "monitoring",
    "event_hubs": "event_hubs",
    "storage": "storage",
    "analytics_workspace": "analytics_workspace",
}
_PLATFORM_SERVICES = (
    "api_management",
    "model_endpoint",
    "key_vault",
    "monitoring",
    "event_hubs",
    "storage",
    "analytics_workspace",
    "cosmos_db",
    "ai_search",
    "container_registry",
)
_HOSTING_SERVICE = {"aks": "kubernetes", "appservice": "app_service"}

_UNKNOWN_REASONS: dict[str, str] = {
    "sku": "SKU fit is not evaluated without live resource detail",
    "network_reachability": "network reachability needs a live probe; none was run",
    "quota": "quota needs a live subscription query; none was run",
    "permission": "write permission on the target needs a live check; none was run",
    "lifecycle": "resource lifecycle state is not part of the scan data",
}


def is_neurosphere_created(resource: DiscoveredResource) -> bool:
    return resource.tags.get(CREATED_BY_TAG) == CREATED_BY_VALUE


def _norm_region(location: str | None) -> str | None:
    return None if location is None else location.strip().lower().replace(" ", "")


def _unknown_checks(*, residency: PlanCheck) -> list[PlanCheck]:
    checks = [PlanCheck(name="sku", outcome="unknown", reason=_UNKNOWN_REASONS["sku"])]
    for name in ("network_reachability", "quota", "permission"):
        checks.append(PlanCheck(name=name, outcome="unknown", reason=_UNKNOWN_REASONS[name]))
    checks.append(residency)
    checks.append(
        PlanCheck(name="lifecycle", outcome="unknown", reason=_UNKNOWN_REASONS["lifecycle"])
    )
    return checks


def _residency_check(resource: DiscoveredResource, profile: DeploymentProfile) -> PlanCheck:
    region = _norm_region(resource.location)
    if region is None:
        return PlanCheck(
            name="residency",
            outcome="fail",
            reason="resource has no location, so residency cannot be established",
        )
    if region in profile.regions:
        return PlanCheck(
            name="residency",
            outcome="pass",
            reason=f"{region} is a profile region in the {profile.cloud} cloud",
        )
    return PlanCheck(
        name="residency",
        outcome="fail",
        reason=(
            f"resource is in {region}, outside the profile regions "
            f"{', '.join(profile.regions)} of the {profile.cloud} cloud; "
            "data is never bridged across clouds or regions"
        ),
    )


def _create_residency() -> PlanCheck:
    return PlanCheck(
        name="residency",
        outcome="pass",
        reason="a new resource is created only in a profile region of the profile cloud",
    )


def _no_cost(summary: str) -> PlanCost:
    return PlanCost(basis="no_incremental_cost", summary=summary)


def _create_cost(service: str, sku: str | None, prices: PriceTable | None) -> PlanCost:
    if prices is not None:
        match = next(
            (e for e in prices.entries if e.service == service and sku and e.sku == sku), None
        ) or next((e for e in prices.entries if e.service == service and e.sku is None), None)
        if match is not None:
            amount = format(Decimal(match.monthly_amount), "f")
            return PlanCost(
                basis="estimated",
                monthly_amount=amount,
                currency=prices.currency,
                price_version=prices.price_version,
                summary=f"Estimated from price table {prices.price_version}.",
            )
    return PlanCost(basis="unknown", summary="No price entry for this service; cost is unknown.")


def _disabled_item(service: str, kind: str, result: CapabilityResult) -> PlanItem:
    return PlanItem(
        service=service,
        kind="feature" if kind == "feature" else "service",
        status="disabled",
        disabled_reason=result.reason,
        reason_code=result.reason_code,
        source_url=result.source_url,
        notes=[f"region {result.region}"] if result.region else [],
        cost_implication=_no_cost("Disabled by the capability matrix; nothing is provisioned."),
    )


def _fallback_item(
    service: str,
    choice: ServiceChoice,
    prices: PriceTable | None,
    notes: list[str],
    checks: list[PlanCheck],
) -> PlanItem:
    if choice.fallback == "skip":
        return PlanItem(
            service=service,
            status="skip",
            notes=[*notes, "falling back to skip"],
            checks=checks,
            cost_implication=_no_cost("Skipped; no incremental cost."),
        )
    return PlanItem(
        service=service,
        status="create",
        notes=[*notes, "falling back to create"],
        checks=checks,
        cost_implication=_create_cost(service, choice.sku, prices),
    )


def _pick_candidate(
    candidates: list[DiscoveredResource],
    choice: ServiceChoice,
    profile: DeploymentProfile,
    consents: list[OwnerConsentRecord],
) -> tuple[DiscoveredResource | None, str | None]:
    if choice.resource_id is not None:
        wanted = choice.resource_id.casefold()
        picked = next((c for c in candidates if c.id.casefold() == wanted), None)
        if picked is None:
            return None, f"requested resource {choice.resource_id} was not found in the scan"
        return picked, None
    if not candidates:
        return None, "no discovered candidate for this service"

    def rank(resource: DiscoveredResource) -> tuple[int, int, int, str]:
        in_region = _residency_check(resource, profile).outcome == "pass"
        consented = _consent_for(resource, consents) is not None
        return (
            int(not in_region),
            int(not is_neurosphere_created(resource)),
            int(not consented),
            resource.id,
        )

    return sorted(candidates, key=rank)[0], None


def _consent_for(
    resource: DiscoveredResource, consents: list[OwnerConsentRecord]
) -> OwnerConsentRecord | None:
    return next(
        (c for c in consents if c.granted and c.owner_principal and c.covers(resource.id)),
        None,
    )


def _plan_service(
    service: str,
    request: PlanRequest,
    candidates: list[DiscoveredResource],
) -> PlanItem:
    prices = request.price_table
    profile = request.profile
    choice = request.choices.get(service)  # pyright: ignore[reportArgumentType]
    if choice is None:
        choice = ServiceChoice(decision="reuse" if candidates else "create")
    if choice.decision == "skip":
        return PlanItem(
            service=service,
            status="skip",
            notes=["operator chose skip"],
            cost_implication=_no_cost("Skipped; no incremental cost."),
        )
    if choice.decision == "create":
        return PlanItem(
            service=service,
            status="create",
            checks=_unknown_checks(residency=_create_residency()),
            notes=["operator chose create"],
            cost_implication=_create_cost(service, choice.sku, prices),
        )

    resource, why_not = _pick_candidate(candidates, choice, profile, request.consents)
    if resource is None:
        return _fallback_item(
            service,
            choice,
            prices,
            [why_not or "no candidate"],
            _unknown_checks(residency=_create_residency()),
        )
    residency = _residency_check(resource, profile)
    checks = _unknown_checks(residency=residency)
    if residency.outcome != "pass":
        return _fallback_item(
            service, choice, prices, [f"cannot reuse {resource.id}: {residency.reason}"], checks
        )

    created = is_neurosphere_created(resource)
    shared = not created
    if shared:
        consent = _consent_for(resource, request.consents)
        if consent is None:
            return PlanItem(
                service=service,
                status="needs_consent",
                existing_resource_id=resource.id,
                shared=True,
                checks=checks,
                notes=[
                    "shared resource: a granted owner-consent record naming an owner "
                    "principal and covering this resource id is required before reuse"
                ],
                cost_implication=_no_cost("Nothing is provisioned until owner consent is granted."),
            )
        return PlanItem(
            service=service,
            status="reuse",
            existing_resource_id=resource.id,
            shared=True,
            checks=checks,
            owner_consent=consent,
            cost_implication=_no_cost("Reuses an existing shared resource."),
        )
    return PlanItem(
        service=service,
        status="reuse",
        existing_resource_id=resource.id,
        shared=False,
        neurosphere_created=True,
        checks=checks,
        notes=["resource is tagged as NeuroSphere-created; no foreign owner consent applies"],
        cost_implication=_no_cost("Reuses a NeuroSphere-created resource."),
    )


def build_plan(
    request: PlanRequest,
    *,
    matrix: CapabilityMatrix | None = None,
    now: datetime | None = None,
    plan_id: str | None = None,
) -> DeploymentPlan:
    profile = request.profile
    now = now or datetime.now(UTC)
    result = validate_profile(profile, matrix=matrix, today=now.astimezone(UTC).date())

    discovered: dict[str, list[DiscoveredResource]] = {}
    if request.scan is not None:
        for sub in request.scan.subscriptions:
            if sub.status != "visible":
                continue
            for resource in sub.resources:
                service = CATEGORY_SERVICE[resource.category]
                discovered.setdefault(service, []).append(resource)

    hosting_service = _HOSTING_SERVICE[profile.hosting]
    disabled_by_service: dict[str, CapabilityResult] = {}
    feature_items: list[PlanItem] = []
    seen_features: set[tuple[str, str | None, str]] = set()
    for cap in result.results:
        if cap.status != "disabled":
            continue
        if cap.kind == "hosting":
            disabled_by_service.setdefault(hosting_service, cap)
        elif cap.kind == "analytics":
            disabled_by_service.setdefault("analytics_workspace", cap)
        else:
            key = (f"{cap.service}.{cap.feature}", cap.sku, cap.region)
            if key not in seen_features:
                seen_features.add(key)
                feature_items.append(_disabled_item(key[0], "feature", cap))

    items: list[PlanItem] = []
    for service in (*_PLATFORM_SERVICES, hosting_service):
        cap = disabled_by_service.get(service)
        if cap is not None:
            items.append(_disabled_item(service, cap.kind, cap))
        else:
            items.append(_plan_service(service, request, discovered.get(service, [])))
    items.extend(feature_items)

    relied: dict[str, OwnerConsentRecord] = {}
    for item in items:
        if item.owner_consent is not None:
            relied.setdefault(item.owner_consent.consent_id, item.owner_consent)

    return DeploymentPlan(
        plan_id=plan_id or f"plan-{uuid.uuid4().hex}",
        deployment_id=request.deployment_id or f"ns-{uuid.uuid4().hex[:12]}",
        profile=profile,
        items=items,
        capability_warnings=list(result.warnings),
        consents=list(relied.values()),
        created_at=now,
    )


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_manifest(plan: DeploymentPlan) -> DeploymentManifest:
    """Project a plan to the PRP-01 ``DeploymentManifest``.

    Mapping (the manifest ``decision`` enum is only ``reuse|create|skip``):

    * ``reuse``         -> ``reuse`` with ``existing_resource_id`` and ``owner_consent``
      ``required=true, granted=true`` carrying the consent's principal and time. A
      NeuroSphere-created resource has no foreign owner, so its consent block is
      ``granted=true`` with principal ``neurosphere:created`` at plan time.
    * ``create``        -> ``create``, consent ``required=false``.
    * ``skip``          -> ``skip`` with the recorded reason.
    * ``needs_consent`` -> ``skip`` (never ``reuse``; the schema forbids an id on skip) with
      ``owner_consent.required=true, granted=false`` and the resource id named in ``skip_reason``.
    * ``disabled``      -> ``skip`` with the matrix reason as ``skip_reason``.
    * ``feature`` items (disabled optional capabilities) are plan-only: no manifest encoding.

    Manifest ``status`` is ``draft`` while any item is ``needs_consent``, else ``planned``.
    """
    created_at = _utc(plan.created_at)
    services: list[dict[str, object]] = []
    for item in plan.items:
        if item.kind != "service":
            continue
        cost: dict[str, object] = {
            "basis": item.cost_implication.basis,
            "monthly_amount": item.cost_implication.monthly_amount,
            "currency": item.cost_implication.currency,
            "price_version": item.cost_implication.price_version,
        }
        if item.cost_implication.summary:
            cost["summary"] = item.cost_implication.summary[:500]
        entry: dict[str, object] = {
            "service": item.service,
            "existing_resource_id": None,
            "owner_consent": {
                "required": False,
                "granted": False,
                "owner_principal": None,
                "recorded_at": None,
            },
            "cost_implication": cost,
        }
        if item.status == "reuse":
            consent = item.owner_consent
            entry["decision"] = "reuse"
            entry["existing_resource_id"] = item.existing_resource_id
            entry["owner_consent"] = {
                "required": True,
                "granted": True,
                "owner_principal": consent.owner_principal if consent else "neurosphere:created",
                "recorded_at": _utc(consent.recorded_at) if consent else created_at,
            }
        elif item.status == "create":
            entry["decision"] = "create"
        elif item.status == "needs_consent":
            entry["decision"] = "skip"
            entry["skip_reason"] = (
                f"Owner consent required to reuse {item.existing_resource_id}; not yet granted."
            )[:500]
            entry["owner_consent"] = {
                "required": True,
                "granted": False,
                "owner_principal": None,
                "recorded_at": None,
            }
        elif item.status == "disabled":
            entry["decision"] = "skip"
            entry["skip_reason"] = (item.disabled_reason or "Disabled by the capability matrix.")[
                :500
            ]
        else:
            entry["decision"] = "skip"
            entry["skip_reason"] = "; ".join(item.notes) or "Skipped by the operator."
        services.append(entry)

    draft = any(i.status == "needs_consent" for i in plan.items)
    return DeploymentManifest.model_validate(
        {
            "schema_version": "1.0.0",
            "deployment_id": plan.deployment_id,
            "cloud": plan.profile.cloud,
            "regions": list(plan.profile.regions),
            "hosting_profile": plan.profile.hosting,
            "analytics_backend": plan.profile.analytics,
            "status": "draft" if draft else "planned",
            "services": services,
            "created_at": created_at,
        }
    )
