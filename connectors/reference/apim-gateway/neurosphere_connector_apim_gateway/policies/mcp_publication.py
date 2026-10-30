"""Policy templates for publishing a catalog MCP server through the gateway (PRP-34 item 6).

Four documents, all rendered from ``templates/mcp-*.xml`` with ``[[name]]`` placeholders filled
from validated inputs only (never caller free text):

- ``mcp-server-enforcement.xml`` (policy fragment): ``validate-azure-ad-token`` for the tenant and
  audience held in named values (referenced as ``{{name}}``, never inlined), deletes
  ``Authorization``, ``Ocp-Apim-Subscription-Key``, ``api-key`` and ``subscription-key`` before
  forwarding (a customer server never sees the caller's credentials), then one ``when`` per grant
  matching the token ``oid`` with a ``rate-limit-by-key`` for that grant (a caller without a
  matching grant gets 403: no grant, no access), and last, optionally, attaches the gateway
  managed identity (``authentication-managed-identity``, after the strip so the only
  ``Authorization`` the upstream sees is the gateway's own token, and only for admitted callers).
- ``mcp-server-api-policy.xml`` (API policy): includes the fragment, routes with
  ``set-backend-service`` and forwards with request and response buffering off.
- ``mcp-deny-policy.xml`` (API policy): ``return-response`` 503. Written FIRST before a backend
  change or an unpublish (fail closed).
- ``mcp-prm-policy.xml`` (shared ``ns-mcp-metadata`` API policy): RFC 9728 protected-resource
  metadata whose ``resource`` is computed from the request URL, so it always equals the gateway
  URL of the server it describes.

Nothing here reads a request or response body: expressions touch headers, the validated token
variable and the request URL only, so MCP streaming stays unbuffered.

This is a separate module from ``policies/__init__`` (item 1) so later items extend without
editing the shared loader; item 1's ``mcp-enforcement.xml`` (one rate limit for every caller)
stays as it is.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from typing import Final
from xml.sax.saxutils import escape

from neurosphere_connector_apim_gateway.policies import named_value_ref

__all__ = [
    "MCP_TEMPLATE_NAMES",
    "McpGrantLimit",
    "load_mcp_template",
    "render_mcp_api_policy",
    "render_mcp_deny_policy",
    "render_mcp_prm_policy",
    "render_mcp_server_enforcement",
]

MCP_TEMPLATE_NAMES: Final = (
    "mcp-server-enforcement.xml",
    "mcp-server-api-policy.xml",
    "mcp-deny-policy.xml",
    "mcp-prm-policy.xml",
)
_PLACEHOLDER = re.compile(r"\[\[([a-z_]+)\]\]")
_RESOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_OID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_OID_CLAIM: Final = '((Jwt)context.Variables["ns-jwt"]).Claims.GetValueOrDefault("oid", "")'
#: Most grants one publication renders (keeps the fragment far below the APIM policy size cap).
MAX_GRANTS: Final = 256
#: ``rate-limit-by-key`` renewal period for per-minute grant limits.
RENEWAL_SECONDS: Final = 60


def load_mcp_template(name: str) -> str:
    if name not in MCP_TEMPLATE_NAMES:
        raise ValueError("unknown MCP policy template")
    return files(__package__).joinpath("templates", name).read_text(encoding="utf-8")


def _render(name: str, values: Mapping[str, str]) -> str:
    text = load_mcp_template(name)

    def sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ValueError(f"template {name} placeholder {key} has no value")
        return values[key]

    out = _PLACEHOLDER.sub(sub, text)
    if _PLACEHOLDER.search(out):
        raise ValueError("unfilled placeholder")
    return out


def _resource_id(value: str) -> str:
    if not _RESOURCE_ID.fullmatch(value):
        raise ValueError("invalid APIM resource id")
    return value


@dataclass(frozen=True)
class McpGrantLimit:
    """One grant on the server: the principal ``oid`` and its MCP calls per minute (or none)."""

    oid: str
    calls_per_minute: int | None = None

    def __post_init__(self) -> None:
        if not _OID.fullmatch(self.oid):
            raise ValueError("grant oid must be a lowercase GUID")
        if self.calls_per_minute is not None and self.calls_per_minute <= 0:
            raise ValueError("calls per minute must be positive")


def _forbidden(indent: str) -> str:
    return (
        f"{indent}<return-response>\n"
        f'{indent}\t<set-status code="403" reason="Forbidden" />\n'
        f"{indent}</return-response>"
    )


def _grant_access(counter_prefix: str, grants: Sequence[McpGrantLimit]) -> str:
    """One ``when`` per grant (matched on the token ``oid``); everyone else gets 403."""
    if not grants:
        return _forbidden("\t")
    if len(grants) > MAX_GRANTS:
        raise ValueError("too many grants for one publication")
    if len({g.oid for g in grants}) != len(grants):
        raise ValueError("one grant per principal")
    lines = ["\t<choose>"]
    for grant in sorted(grants, key=lambda g: g.oid):
        condition = escape(f'@({_OID_CLAIM} == "{grant.oid}")', {"'": "&apos;"})
        if grant.calls_per_minute is None:
            lines.append(f"\t\t<when condition='{condition}' />")
            continue
        lines += [
            f"\t\t<when condition='{condition}'>",
            f'\t\t\t<rate-limit-by-key calls="{grant.calls_per_minute}" '
            f'renewal-period="{RENEWAL_SECONDS}" counter-key="{counter_prefix}:{grant.oid}" />',
            "\t\t</when>",
        ]
    lines += ["\t\t<otherwise>", _forbidden("\t\t\t"), "\t\t</otherwise>", "\t</choose>"]
    return "\n".join(lines)


def render_mcp_server_enforcement(
    *,
    tenant_named_value: str,
    audience_named_value: str,
    counter_prefix: str,
    grants: Sequence[McpGrantLimit],
    managed_identity: bool,
) -> str:
    """The enforcement fragment for one customer MCP server.

    ``managed_identity`` attaches the gateway identity for the audience named value (the
    upstream's audience) after the caller's credentials are stripped.
    """
    tenant = named_value_ref(tenant_named_value)
    audience = named_value_ref(audience_named_value)
    managed = (
        f'\n\t<authentication-managed-identity resource="{audience}" />' if managed_identity else ""
    )
    return _render(
        "mcp-server-enforcement.xml",
        {
            "tenant_named_value": tenant[2:-2],
            "audience_named_value": audience[2:-2],
            "managed_identity": managed,
            "grant_access": _grant_access(_resource_id(counter_prefix), grants),
        },
    )


def render_mcp_api_policy(*, fragment_id: str, backend_id: str) -> str:
    """API policy of a published server: enforcement fragment, backend, unbuffered forward."""
    return _render(
        "mcp-server-api-policy.xml",
        {"fragment_id": _resource_id(fragment_id), "backend_id": _resource_id(backend_id)},
    )


def render_mcp_deny_policy() -> str:
    """Fail-closed API policy (503) written before a backend change or an unpublish."""
    return _render("mcp-deny-policy.xml", {})


def render_mcp_prm_policy(*, login_host: str, tenant_named_value: str) -> str:
    """Shared protected-resource-metadata policy; ``login_host`` comes from the cloud profile."""
    if not _HOST.fullmatch(login_host):
        raise ValueError("invalid login host")
    tenant = named_value_ref(tenant_named_value)
    return _render(
        "mcp-prm-policy.xml",
        {"login_host": login_host, "tenant_named_value": tenant[2:-2]},
    )
