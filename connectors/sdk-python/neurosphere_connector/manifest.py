"""Manifest builder and validator over the PRP-01 ``ConnectorManifest`` contract.

The contract model is never redefined here. ``validate_manifest`` applies the generated model
plus the rules JSON Schema expresses with ``if/then`` (which the generated model drops) and the
cross-field rules named in the schema description (unique credential names, vault host matches a
supported cloud). Issues carry an RFC 6901 pointer and a value-free message, so a rejected
manifest never echoes what was submitted.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from neurosphere_contracts.connectors.v1.connector_manifest import (
    ConnectorManifest,
    CredentialRef,
    Freshness,
    Granularity,
    RateLimit,
    WriteSupport,
)
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from pydantic import ValidationError

__all__ = ["build_manifest", "manifest_issues", "validate_manifest"]

_VAULT_HOST_CLOUD = {"vault.azure.net": "commercial", "vault.usgovcloudapi.net": "government"}
Capability = Literal[
    "telemetry_ingest",
    "cost_ingest",
    "catalog_discovery",
    "usage_reports",
    "evaluation_results",
    "audit_events",
    "health_reporting",
    "action_execution",
]
WriteAction = Literal[
    "model_deployment_swap",
    "model_deployment_scale",
    "policy_update",
    "routing_update",
    "agent_disable",
    "agent_enable",
    "budget_cap_change",
    "grant_publish",
    "grant_unpublish",
    "mcp_server_publish",
    "mcp_server_unpublish",
    "gateway_mode_change",
]
Cloud = Literal["commercial", "government"]


def _pointer(loc: Sequence[object]) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in loc)


def _cross_field_issues(m: ConnectorManifest) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    refs = m.credential_refs
    if m.auth_mode == "vault_reference" and not refs:
        issues.append(ValidationIssue("/credential_refs", "vault_reference requires a ref"))
    if m.auth_mode != "vault_reference" and refs:
        issues.append(ValidationIssue("/credential_refs", "only vault_reference carries refs"))
    names = [r.name for r in refs]
    for i, name in enumerate(names):
        if names.index(name) != i:
            issues.append(ValidationIssue(f"/credential_refs/{i}/name", "duplicate name"))
    clouds = set(m.supported_clouds)
    for i, ref in enumerate(refs):
        host = ref.vault_ref.removeprefix("https://").split("/", 1)[0]
        cloud = next((c for s, c in _VAULT_HOST_CLOUD.items() if host.endswith("." + s)), None)
        if cloud not in clouds:
            issues.append(
                ValidationIssue(
                    f"/credential_refs/{i}/vault_ref", "vault host not in a listed cloud"
                )
            )
    ws = m.write_support
    if ws.supported and not ws.actions:
        issues.append(ValidationIssue("/write_support/actions", "supported requires an action"))
    if not ws.supported and ws.actions:
        issues.append(ValidationIssue("/write_support/actions", "must be empty when unsupported"))
    if len(set(ws.actions)) != len(ws.actions):
        issues.append(ValidationIssue("/write_support/actions", "actions must be unique"))
    if m.advisory == ws.supported:
        issues.append(
            ValidationIssue("/advisory", "advisory must be true iff write is unsupported")
        )
    if ("action_execution" in m.capabilities) != ws.supported:
        issues.append(
            ValidationIssue("/capabilities", "action_execution iff write_support.supported")
        )
    return issues


def manifest_issues(data: Mapping[str, Any] | str | bytes) -> list[ValidationIssue]:
    """Return every contract violation (empty list means valid). Messages never hold values."""
    if isinstance(data, (str, bytes)):
        try:
            parsed = json.loads(data)
        except ValueError:
            return [ValidationIssue("", "document is not valid JSON")]
        if not isinstance(parsed, dict):
            return [ValidationIssue("", "document must be a JSON object")]
        data = cast("dict[str, Any]", parsed)
    try:
        model = ConnectorManifest.model_validate(data)
    except ValidationError as exc:
        return [ValidationIssue(_pointer(e["loc"]), e["msg"]) for e in exc.errors()]
    return _cross_field_issues(model)


def validate_manifest(
    data: Mapping[str, Any] | str | bytes | ConnectorManifest,
) -> ConnectorManifest:
    """Return the validated manifest or raise ``InvalidSchemaError`` listing the issues."""
    if isinstance(data, ConnectorManifest):
        data = data.model_dump(mode="json")
    issues = manifest_issues(data)
    if issues:
        raise InvalidSchemaError("connector manifest is invalid", errors=issues)
    if isinstance(data, (str, bytes)):
        return ConnectorManifest.model_validate_json(data)
    return ConnectorManifest.model_validate(data)


def build_manifest(
    *,
    name: str,
    version: str,
    capabilities: Sequence[Capability],
    supported_clouds: Sequence[Cloud],
    granularity: Granularity,
    freshness: Freshness | None = None,
    scopes: Sequence[str] = (),
    rate_limits: Sequence[RateLimit] | None = None,
    credential_refs: Sequence[CredentialRef] = (),
    write_actions: Sequence[WriteAction] = (),
    documentation_url: str | None = None,
    auth_mode: Literal["managed_identity", "workload_identity_federation", "vault_reference"]
    | None = None,
    schema_version: str = "1.0.0",
) -> ConnectorManifest:
    """Assemble and validate a manifest, deriving ``advisory``, ``write_support`` and auth mode.

    Unknown freshness defaults to null/null (never 0); unknown ``rate_limits`` stays None.
    ``action_execution`` is added when ``write_actions`` is non-empty.
    """
    caps = list(capabilities)
    if write_actions and "action_execution" not in caps:
        caps.append("action_execution")
    mode = auth_mode or ("vault_reference" if credential_refs else "managed_identity")
    doc: dict[str, Any] = {
        "schema_version": schema_version,
        "name": name,
        "version": version,
        "supported_clouds": list(supported_clouds),
        "capabilities": caps,
        "scopes": list(scopes),
        "granularity": granularity.model_dump(mode="json"),
        "freshness": (freshness or Freshness(typical_delay_ms=None, max_delay_ms=None)).model_dump(
            mode="json"
        ),
        "rate_limits": None if rate_limits is None else [r.model_dump() for r in rate_limits],
        "auth_mode": mode,
        "credential_refs": [r.model_dump() for r in credential_refs],
        "advisory": not write_actions,
        "write_support": WriteSupport(
            supported=bool(write_actions), actions=list(write_actions)
        ).model_dump(),
    }
    if documentation_url is not None:
        doc["documentation_url"] = documentation_url
    return validate_manifest(doc)
