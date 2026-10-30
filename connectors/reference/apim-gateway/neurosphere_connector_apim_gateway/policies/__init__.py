"""APIM policy XML templates and their renderers (PRP-34 item 1).

Templates live as ``templates/*.xml`` so Bicep (item 7) can load the same text. Placeholders are
``[[name]]``; renderers substitute XML-escaped values or blocks built here from validated inputs,
and refuse to return text with an unfilled placeholder. Named values are referenced only as
``{{name}}``: a renderer takes a named value's NAME, never its value, so no secret or tenant
detail is ever inlined into policy text.

Policy XML is written against Microsoft Learn (llm-token-limit, llm-emit-token-metric,
validate-azure-ad-token, rate-limit-by-key, authentication-managed-identity, return-response,
include-fragment, set-backend-service). Attributes holding policy expressions with double quotes
are single-quoted so every rendered document is well-formed XML; fragments are submitted with
``format: rawxml``. No template reads a request or response body (MCP streaming stays
unbuffered).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from typing import Final, Literal
from xml.sax.saxutils import escape

__all__ = [
    "COUNTER_KEYS",
    "TEMPLATE_NAMES",
    "GrantLimits",
    "McpEnforcement",
    "fragment_payload",
    "load_template",
    "named_value_ref",
    "render_api_policy",
    "render_deny_fragment",
    "render_grant_fragment",
    "render_mcp_enforcement_fragment",
]

TEMPLATE_NAMES: Final = ("api-policy.xml", "deny.xml", "grant-product.xml", "mcp-enforcement.xml")
_PLACEHOLDER = re.compile(r"\[\[([a-z_]+)\]\]")
_NAMED_VALUE = re.compile(r"^[A-Za-z0-9._-]{1,256}$")
_RESOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_NAMESPACE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
_QUOTA_PERIODS: Final = ("Hourly", "Daily", "Weekly", "Monthly", "Yearly")
_SQ_ESCAPES: Final = {"'": "&apos;"}
_DQ_ESCAPES: Final = {'"': "&quot;"}

# Counter keys are fixed expressions, never caller text. ``subscription`` keys on the APIM
# subscription; ``oid`` on the caller's Entra object id from the bearer token.
COUNTER_KEYS: Final[Mapping[str, str]] = {
    "subscription": "@(context.Subscription.Id)",
    "oid": (
        '@(context.Request.Headers.GetValueOrDefault("Authorization", "")'
        '.AsJwt()?.Claims.GetValueOrDefault("oid", "anonymous"))'
    ),
}


def load_template(name: str) -> str:
    if name not in TEMPLATE_NAMES:
        raise ValueError("unknown policy template")
    return files(__package__).joinpath("templates", name).read_text(encoding="utf-8")


def _attr_sq(value: str) -> str:
    """Escape for a single-quoted attribute (expressions keep their double quotes)."""
    return escape(value, _SQ_ESCAPES)


def _attr(value: str) -> str:
    """Escape for a double-quoted attribute."""
    return escape(value, _DQ_ESCAPES)


def named_value_ref(name: str) -> str:
    """``{{name}}`` for a validated named-value name."""
    if not _NAMED_VALUE.fullmatch(name):
        raise ValueError("invalid named value name")
    return "{{" + name + "}}"


def _render(name: str, values: Mapping[str, str]) -> str:
    text = load_template(name)

    def sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ValueError(f"template {name} placeholder {key} has no value")
        return values[key]

    out = _PLACEHOLDER.sub(sub, text)
    if _PLACEHOLDER.search(out):
        raise ValueError("unfilled placeholder")
    return out


@dataclass(frozen=True)
class GrantLimits:
    """``llm-token-limit`` inputs for one grant (one scope per grant: PRP-34 gotcha)."""

    counter_key: Literal["subscription", "oid"]
    tokens_per_minute: int | None = None
    token_quota: int | None = None
    token_quota_period: str | None = None
    metric_namespace: str = "neurosphere"

    def __post_init__(self) -> None:
        if self.tokens_per_minute is None and self.token_quota is None:
            raise ValueError("set tokens_per_minute, token_quota or both")
        for value in (self.tokens_per_minute, self.token_quota):
            if value is not None and value <= 0:
                raise ValueError("token limits must be positive")
        if (self.token_quota is None) != (self.token_quota_period is None):
            raise ValueError("token_quota and token_quota_period go together")
        if self.token_quota_period is not None and self.token_quota_period not in _QUOTA_PERIODS:
            raise ValueError("invalid token_quota_period")
        if not _NAMESPACE.fullmatch(self.metric_namespace):
            raise ValueError("invalid metric namespace")


def render_grant_fragment(limits: GrantLimits) -> str:
    """Grant fragment: ``llm-token-limit`` plus ``llm-emit-token-metric`` (3 of 5 dimensions)."""
    attrs = ""
    if limits.tokens_per_minute is not None:
        attrs += f' tokens-per-minute="{limits.tokens_per_minute}"'
    if limits.token_quota is not None and limits.token_quota_period is not None:
        attrs += f' token-quota="{limits.token_quota}"'
        attrs += f' token-quota-period="{limits.token_quota_period}"'
    return _render(
        "grant-product.xml",
        {
            "counter_key": _attr_sq(COUNTER_KEYS[limits.counter_key]),
            "limit_attributes": attrs,
            "metric_namespace": _attr(limits.metric_namespace),
        },
    )


@dataclass(frozen=True)
class McpEnforcement:
    """Inputs for the MCP enforcement fragment; tenant and audience are named-value NAMES."""

    tenant_named_value: str
    audience_named_value: str
    calls: int
    renewal_period_seconds: int
    managed_identity_resource: str | None = None

    def __post_init__(self) -> None:
        named_value_ref(self.tenant_named_value)
        named_value_ref(self.audience_named_value)
        if self.calls <= 0 or self.renewal_period_seconds <= 0:
            raise ValueError("rate limits must be positive")
        resource = self.managed_identity_resource
        if resource is not None and (not resource or len(resource) > 512 or "\n" in resource):
            raise ValueError("invalid managed identity resource")


def render_mcp_enforcement_fragment(config: McpEnforcement) -> str:
    """Entra validation, credential stripping, optional managed identity, per-oid rate limit."""
    managed = ""
    if config.managed_identity_resource is not None:
        managed = (
            "\n\t<authentication-managed-identity "
            f'resource="{_attr(config.managed_identity_resource)}" />'
        )
    return _render(
        "mcp-enforcement.xml",
        {
            "tenant_named_value": config.tenant_named_value,
            "audience_named_value": config.audience_named_value,
            "managed_identity": managed,
            "calls": str(config.calls),
            "renewal_period": str(config.renewal_period_seconds),
        },
    )


def render_deny_fragment() -> str:
    """Fail-closed fragment written before an MCP backend change or unpublish."""
    return _render("deny.xml", {})


def render_api_policy(fragment_ids: Sequence[str], *, backend_id: str | None = None) -> str:
    """API (or product) policy that includes fragments and optionally routes to a backend."""
    for value in (*fragment_ids, *([backend_id] if backend_id else [])):
        if not _RESOURCE_ID.fullmatch(value):
            raise ValueError("invalid fragment or backend id")
    includes = "".join(f'\n\t\t<include-fragment fragment-id="{f}" />' for f in fragment_ids)
    backend = f'\n\t\t<set-backend-service backend-id="{backend_id}" />' if backend_id else ""
    return _render("api-policy.xml", {"includes": includes, "backend": backend})


def fragment_payload(xml: str, *, description: str | None = None) -> dict[str, str]:
    """ARM ``properties`` for a policy fragment or policy (``format: rawxml``)."""
    payload = {"format": "rawxml", "value": xml}
    if description is not None:
        payload["description"] = description[:1000]
    return payload
