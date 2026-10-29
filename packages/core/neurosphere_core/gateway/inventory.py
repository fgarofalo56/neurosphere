"""Read-only APIM inventory and preflight over ARM REST (PRP-33 item 6, observe mode).

Every request is a ``GET``. This module never calls ``listSecrets``/``listKeys`` (no POST exists
here), never requests named-value values, and never keeps a policy fragment body, subscription
key or backend credential: the snapshot models have no field for them. ``nextLink`` is followed
only to the SAME host as the ARM client (and, when a profile is given, a host of that cloud).
429 honours ``Retry-After`` with capped backoff (3 retries) and then maps to
``dependency_transient``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict

from neurosphere_core.clients import assert_host_in_cloud
from neurosphere_core.cloud import CloudProfile
from neurosphere_core.errors import CapabilityUnavailableError, DependencyTransientError
from neurosphere_core.gateway.models import (
    ApiEntry,
    BackendEntry,
    CircuitBreakerRule,
    DiagnosticsState,
    GatewayInventory,
    OperationEntry,
    PolicyFragmentEntry,
    PoolMember,
    ProductApiLink,
    ProductEntry,
    SubscriptionEntry,
    Tier,
    gateway_id_for,
    normalize_arm_id,
)

__all__ = [
    "DIAGNOSTICS_API_VERSION",
    "SKU_TO_TIER",
    "PreflightResult",
    "preflight",
    "read_inventory",
]

DEFAULT_API_VERSION: Final = "2024-05-01"
DIAGNOSTICS_API_VERSION: Final = "2021-05-01-preview"
MAX_RETRIES: Final = 3
MAX_BACKOFF_SECONDS: Final = 30.0
MAX_PAGES: Final = 200
SKU_TO_TIER: Final[Mapping[str, Tier]] = {
    "consumption": "consumption",
    "developer": "developer",
    "basic": "basic",
    "standard": "standard",
    "premium": "premium",
    "basicv2": "basic_v2",
    "standardv2": "standard_v2",
    "premiumv2": "premium_v2",
}
_ALL_LOGS_GROUPS: Final = frozenset({"alllogs"})
_CATEGORY_FIELD: Final = {
    "gatewaylogs": "gateway_logs",
    "gatewayllmlogs": "gateway_llm_logs",
    "gatewaymcplogs": "gateway_mcp_logs",
}


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


class PreflightResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    tier: Tier
    sku_name_raw: str | None
    diagnostics: DiagnosticsState


def _unreadable(status: int) -> CapabilityUnavailableError:
    return CapabilityUnavailableError(
        "gateway_not_readable",
        f"ARM refused or could not find the gateway resource (HTTP {status})",
    )


def _retry_after(response: httpx.Response) -> float:
    raw = response.headers.get("Retry-After", "")
    try:
        seconds = float(raw)
    except ValueError:
        seconds = 1.0
    return min(max(seconds, 0.0), MAX_BACKOFF_SECONDS)


def _check_url(client: httpx.AsyncClient, profile: CloudProfile | None, url: str) -> None:
    parts = urlsplit(url)
    if not parts.scheme:  # relative: resolved against the base URL checked at the entry point
        return
    if profile is not None:
        assert_host_in_cloud(profile, url)
    host = (parts.hostname or "").lower()
    if host != (client.base_url.host or "").lower():
        raise CapabilityUnavailableError(
            "endpoint_cloud_mismatch", f"{host} is not the ARM host of this client"
        )


async def _get(
    client: httpx.AsyncClient,
    url: str,
    *,
    profile: CloudProfile | None,
    optional: bool = False,
) -> dict[str, Any] | None:
    """One GET with 429 backoff. ``optional`` turns 404 into ``None``."""
    _check_url(client, profile, url)
    attempt = 0
    while True:
        try:
            response = await client.get(url)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            raise DependencyTransientError("ARM is unreachable", reason="arm_unreachable") from exc
        status = response.status_code
        if status == 429:
            wait = _retry_after(response)
            if attempt >= MAX_RETRIES:
                raise DependencyTransientError(
                    "ARM throttled the request",
                    reason="arm_rate_limited",
                    retry_after_seconds=max(1, int(wait)),
                )
            attempt += 1
            await _sleep(min(MAX_BACKOFF_SECONDS, max(wait, 0.0) * attempt))
            continue
        if status == 404 and optional:
            return None
        if status in (401, 403, 404):
            raise _unreadable(status)
        if status >= 500:
            raise DependencyTransientError("ARM is unavailable", reason="arm_unavailable")
        if status >= 400:
            raise DependencyTransientError(
                "ARM rejected the read", reason="arm_request_rejected", upstream_invalid=True
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise DependencyTransientError(
                "ARM returned a non-JSON body", reason="arm_invalid_body", upstream_invalid=True
            ) from exc
        if not isinstance(body, dict):
            raise DependencyTransientError(
                "ARM returned an unexpected body", reason="arm_invalid_body", upstream_invalid=True
            )
        return body


def _url(arm_id: str, suffix: str, api_version: str) -> str:
    return f"{arm_id}{suffix}?api-version={api_version}"


async def _list(
    client: httpx.AsyncClient,
    url: str,
    *,
    profile: CloudProfile | None,
    optional: bool = False,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    next_url: str | None = url
    pages = 0
    while next_url is not None:
        pages += 1
        if pages > MAX_PAGES:
            raise DependencyTransientError(
                "ARM paging did not terminate", reason="arm_invalid_body", upstream_invalid=True
            )
        body = await _get(client, next_url, profile=profile, optional=optional)
        if body is None:
            return items
        value = body.get("value", [])
        if not isinstance(value, list):
            raise DependencyTransientError(
                "ARM returned an unexpected list", reason="arm_invalid_body", upstream_invalid=True
            )
        items.extend(v for v in value if isinstance(v, dict))
        link = body.get("nextLink")
        next_url = link if isinstance(link, str) and link else None
    return items


def _props(item: Mapping[str, Any]) -> Mapping[str, Any]:
    props = item.get("properties")
    return props if isinstance(props, Mapping) else {}


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _last_segment(resource_id: str) -> str:
    return resource_id.rstrip("/").rsplit("/", 1)[-1]


def _status_codes(condition: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    ranges = condition.get("statusCodeRanges")
    for entry in ranges if isinstance(ranges, list) else []:
        if not isinstance(entry, Mapping):
            continue
        low, high = _int(entry.get("min")), _int(entry.get("max"))
        if low is not None and high is not None:
            out.append(str(low) if low == high else f"{low}-{high}")
    return out


def _backend(item: Mapping[str, Any]) -> BackendEntry:
    props = _props(item)
    kind = "Pool" if _str(props.get("type")) == "Pool" else "Single"
    members: list[PoolMember] = []
    pool = props.get("pool")
    services = pool.get("services") if isinstance(pool, Mapping) else None
    for svc in services if isinstance(services, list) else []:
        if isinstance(svc, Mapping) and isinstance(svc.get("id"), str):
            members.append(
                PoolMember(
                    backend_id=_last_segment(svc["id"]),
                    weight=_int(svc.get("weight")),
                    priority=_int(svc.get("priority")),
                )
            )
    rules: list[CircuitBreakerRule] = []
    breaker = props.get("circuitBreaker")
    raw_rules = breaker.get("rules") if isinstance(breaker, Mapping) else None
    for rule in raw_rules if isinstance(raw_rules, list) else []:
        if not isinstance(rule, Mapping):
            continue
        condition = rule.get("failureCondition")
        cond: Mapping[str, Any] = condition if isinstance(condition, Mapping) else {}
        rules.append(
            CircuitBreakerRule(
                name=_str(rule.get("name")),
                trip_duration=_str(rule.get("tripDuration")),
                failure_count=_int(cond.get("count")),
                failure_interval=_str(cond.get("interval")),
                status_codes=_status_codes(cond),
            )
        )
    return BackendEntry(
        id=str(item.get("name", "")),
        type=kind,
        url=_str(props.get("url")) if kind == "Single" else None,
        pool_members=members,
        circuit_breaker_rules=rules,
    )


async def read_inventory(
    client: httpx.AsyncClient,
    arm_resource_id: str,
    *,
    api_version: str = DEFAULT_API_VERSION,
    profile: CloudProfile | None = None,
    customer_id: str = "",
    domain_id: str = "",
    gateway_id: str | None = None,
    now: datetime | None = None,
) -> GatewayInventory:
    """Snapshot of APIs, operations, products, backends, fragment names and subscription ids.

    ``gateway_id`` wins when given; otherwise it is derived from ``customer_id``/``domain_id``.
    """
    if profile is not None:
        assert_host_in_cloud(profile, str(client.base_url))
    arm_id = normalize_arm_id(arm_resource_id)
    gid = gateway_id or gateway_id_for(customer_id, domain_id, arm_id)

    def url(suffix: str) -> str:
        return _url(arm_id, suffix, api_version)

    raw_apis = await _list(client, url("/apis"), profile=profile)
    apis = [
        ApiEntry(
            id=str(a.get("name", "")),
            name=_str(_props(a).get("displayName")),
            path=_str(_props(a).get("path")),
            protocols=[p for p in _props(a).get("protocols", []) if isinstance(p, str)]
            if isinstance(_props(a).get("protocols"), list)
            else [],
            api_type=_str(_props(a).get("type")) or _str(_props(a).get("apiType")),
            subscription_required=_bool(_props(a).get("subscriptionRequired")),
            revision=_str(_props(a).get("apiRevision")),
        )
        for a in raw_apis
    ]
    operations: list[OperationEntry] = []
    for api in apis:
        ops = await _list(
            client, url(f"/apis/{quote(api.id, safe='')}/operations"), profile=profile
        )
        operations.extend(
            OperationEntry(
                api_id=api.id,
                id=str(o.get("name", "")),
                method=_str(_props(o).get("method")),
                url_template=_str(_props(o).get("urlTemplate")),
            )
            for o in ops
        )
    raw_products = await _list(client, url("/products"), profile=profile)
    products = [
        ProductEntry(
            id=str(p.get("name", "")),
            name=_str(_props(p).get("displayName")),
            state=_str(_props(p).get("state")),
            subscription_required=_bool(_props(p).get("subscriptionRequired")),
            approval_required=_bool(_props(p).get("approvalRequired")),
        )
        for p in raw_products
    ]
    links: list[ProductApiLink] = []
    for product in products:
        linked = await _list(
            client, url(f"/products/{quote(product.id, safe='')}/apis"), profile=profile
        )
        links.extend(
            ProductApiLink(product_id=product.id, api_id=str(a.get("name", ""))) for a in linked
        )
    backends = [
        _backend(b) for b in await _list(client, url("/backends"), profile=profile, optional=True)
    ]
    fragments = [
        PolicyFragmentEntry(
            name=str(f.get("name", "")), description=_str(_props(f).get("description"))
        )
        for f in await _list(client, url("/policyFragments"), profile=profile, optional=True)
    ]
    subscriptions = [
        SubscriptionEntry(
            id=str(s.get("name", "")),
            display_name=_str(_props(s).get("displayName")),
            scope=_str(_props(s).get("scope")),
            state=_str(_props(s).get("state")),
        )
        for s in await _list(client, url("/subscriptions"), profile=profile)
    ]
    return GatewayInventory(
        gateway_id=gid,
        taken_at=now or datetime.now(UTC),
        apis=apis,
        operations=operations,
        products=products,
        product_api_links=links,
        backends=backends,
        policy_fragments=fragments,
        subscriptions=subscriptions,
    )


def _diagnostics(settings: list[dict[str, Any]]) -> DiagnosticsState:
    flags = {"gateway_logs": False, "gateway_llm_logs": False, "gateway_mcp_logs": False}
    workspace: str | None = None
    for setting in settings:
        props = _props(setting)
        logs = props.get("logs")
        enabled_here = False
        for log in logs if isinstance(logs, list) else []:
            if not isinstance(log, Mapping) or log.get("enabled") is not True:
                continue
            category = (_str(log.get("category")) or "").lower()
            group = (_str(log.get("categoryGroup")) or "").lower()
            if group in _ALL_LOGS_GROUPS:
                flags = dict.fromkeys(flags, True)
                enabled_here = True
            elif category in _CATEGORY_FIELD:
                flags[_CATEGORY_FIELD[category]] = True
                enabled_here = True
        ws = _str(props.get("workspaceId"))
        if enabled_here and ws and workspace is None:
            workspace = ws
    return DiagnosticsState(workspace_resource_id=workspace, **flags)


async def preflight(
    client: httpx.AsyncClient,
    arm_resource_id: str,
    *,
    api_version: str = DEFAULT_API_VERSION,
    profile: CloudProfile | None = None,
) -> PreflightResult:
    """GET the service document (tier from ``sku.name``) and its diagnostic settings."""
    if profile is not None:
        assert_host_in_cloud(profile, str(client.base_url))
    arm_id = normalize_arm_id(arm_resource_id)
    service = await _get(client, _url(arm_id, "", api_version), profile=profile)
    assert service is not None
    sku = service.get("sku")
    raw = _str(sku.get("name")) if isinstance(sku, Mapping) else None
    tier: Tier = SKU_TO_TIER.get((raw or "").lower(), "unknown")
    settings = await _list(
        client,
        _url(arm_id, "/providers/Microsoft.Insights/diagnosticSettings", DIAGNOSTICS_API_VERSION),
        profile=profile,
    )
    return PreflightResult(
        name=_last_segment(arm_id),
        tier=tier,
        sku_name_raw=raw[:64] if raw else None,
        diagnostics=_diagnostics(settings),
    )
