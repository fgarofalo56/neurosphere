"""Recording an McpServer publication stage in the catalog (PRP-34 items 6 and 10): the shared
rules of ``POST /api/v1/catalog/mcp-servers/{id}/publication-record`` and of the worker's
post-success recorder.

:func:`check_mcp_intent` accepts only a succeeded, verified, non-dry-run publication intent of
THIS server whose stage belongs to its action kind (``remove`` never under
``mcp_server_publish``), drafted against the server's current publication state, on the gateway
the server is recorded on, and not applied before the last record (a superseded change).
:func:`mcp_publication_document` returns the McpServer document after recording the stage.

Naming mirrors the APIM connector's ``mcp`` module (the API does not import connectors; a test
asserts both sides agree).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final, Literal, cast

from neurosphere_core.actions import StoredIntent
from neurosphere_core.catalog.rules import format_timestamp, parse_timestamp
from neurosphere_core.errors import InvalidSchemaError, StaleVersionError

__all__ = [
    "ATTRIBUTE_PREFIX",
    "CONNECTOR_SOURCE",
    "CONNECTOR_VERSION",
    "KIND_STAGES",
    "MCP_ENTITY_TYPE",
    "MCP_KINDS",
    "METADATA_API",
    "PUBLISH_KIND",
    "STAGE_VERSIONS",
    "STATE_VERSIONS",
    "TENANT_NAMED_VALUE",
    "UNPUBLISH_KIND",
    "Stage",
    "State",
    "check_mcp_intent",
    "mcp_attr",
    "mcp_attributes",
    "mcp_publication_document",
    "mcp_recorded",
    "mcp_state",
    "publication_of",
    "publication_prefix",
    "publication_resources",
]

PUBLISH_KIND: Final = "mcp_server_publish"
UNPUBLISH_KIND: Final = "mcp_server_unpublish"
MCP_KINDS: Final = frozenset({PUBLISH_KIND, UNPUBLISH_KIND})
MCP_ENTITY_TYPE: Final = "mcp_server"
METADATA_API: Final = "ns-mcp-metadata"
TENANT_NAMED_VALUE: Final = "ns-mcp-tenant-id"
CONNECTOR_SOURCE: Final = "apim-gateway"
CONNECTOR_VERSION: Final = "0.1.0"
ATTRIBUTE_PREFIX: Final = "mcp_publication_"
STAGE_VERSIONS: Final[Mapping[str, str]] = {
    "publish": "mcp-absent",
    "deny": "mcp-published",
    "change": "mcp-denied",
    "remove": "mcp-denied",
}
STATE_VERSIONS: Final[Mapping[str, str]] = {
    "unpublished": "mcp-absent",
    "published": "mcp-published",
    "denied": "mcp-denied",
}
KIND_STAGES: Final[Mapping[str, frozenset[str]]] = {
    PUBLISH_KIND: frozenset({"publish", "deny", "change"}),
    UNPUBLISH_KIND: frozenset({"deny", "remove"}),
}
_AFTER: Final[Mapping[str, str]] = {
    "publish": "published",
    "deny": "denied",
    "change": "published",
    "remove": "unpublished",
}

Stage = Literal["publish", "deny", "change", "remove"]
State = Literal["unpublished", "published", "denied"]


def _bad(reason: str, detail: str) -> InvalidSchemaError:
    return InvalidSchemaError(detail, reason=reason)


def publication_prefix(server_id: str) -> str:
    """Resource-name prefix of one catalog MCP server on a gateway (``ns-mcp-`` + 16 hex)."""
    return "ns-mcp-" + hashlib.sha256(server_id.encode("utf-8")).hexdigest()[:16]


def publication_resources(server_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """``(created per-server resources, shared resources)`` as relative ARM paths."""
    prefix = publication_prefix(server_id)
    created = (
        f"backends/{prefix}",
        f"policyFragments/{prefix}-enforce",
        f"apis/{prefix}",
        f"apis/{METADATA_API}/operations/{prefix}-prm",
        f"apis/{prefix}/policies/policy",
    )
    shared = (f"apis/{METADATA_API}", f"apis/{METADATA_API}/policies/policy")
    return created, shared


def mcp_attributes(doc: Mapping[str, Any]) -> dict[str, Any]:
    raw = doc.get("attributes")
    return dict(cast(Mapping[str, Any], raw)) if isinstance(raw, Mapping) else {}


def mcp_attr(doc: Mapping[str, Any], key: str) -> str | None:
    value = mcp_attributes(doc).get(ATTRIBUTE_PREFIX + key)
    return value if isinstance(value, str) and value else None


def mcp_state(doc: Mapping[str, Any]) -> State:
    value = mcp_attr(doc, "state")
    if value in ("published", "denied"):
        return cast(State, value)
    return "unpublished"


def mcp_recorded(doc: Mapping[str, Any], intent_id: str) -> bool:
    """True when this intent is already the last recorded stage (idempotent replay)."""
    return mcp_attr(doc, "intent_id") == intent_id


def publication_of(diff: Any) -> Mapping[str, Any]:
    ops = [op for op in diff.operations if op.path == "/publication"]
    value = ops[0].value if len(ops) == 1 else None
    if not isinstance(value, Mapping):
        raise _bad("intent_mismatch", "the intent is not an MCP publication")
    return cast(Mapping[str, Any], value)


def check_mcp_intent(
    doc: Mapping[str, Any], server_id: str, stored: StoredIntent
) -> tuple[Stage, Mapping[str, Any]]:
    """(stage, publication) of a recordable intent; refuses everything else (module doc)."""
    intent = stored.intent
    if intent.target.canonical_id != server_id or intent.action_kind not in KIND_STAGES:
        raise _bad("intent_mismatch", "the intent is not a publication of this server")
    publication = publication_of(intent.proposed_diff)
    stage = publication.get("stage")
    if stage not in KIND_STAGES[intent.action_kind]:
        raise _bad("intent_mismatch", "the stage does not belong to this action kind")
    execution = stored.execution
    if (
        stored.state != "succeeded"
        or intent.dry_run
        or execution is None
        or execution.verify_matched is not True
        or execution.apply_finished_at is None
    ):
        raise _bad("intent_not_succeeded", "only a succeeded, verified intent is recorded")
    applied_at = execution.apply_finished_at
    if intent.target_version != STATE_VERSIONS[mcp_state(doc)]:
        raise StaleVersionError(
            "the publication state changed since the intent was drafted",
            reason="publication_state_changed",
        )
    recorded_gateway = mcp_attr(doc, "gateway_id")
    if recorded_gateway is not None and publication.get("gateway_id") != recorded_gateway:
        raise _bad("mcp_published_elsewhere", "the intent names another gateway")
    # An intent applied before the last record is history (its effect was superseded):
    # replaying it would record a state the gateway no longer has.
    provenance = cast(Mapping[str, Any], doc.get("provenance") or {})
    source = provenance.get("source_id")
    recorded_at = provenance.get("recorded_at")
    if (
        isinstance(source, str)
        and source.startswith(CONNECTOR_SOURCE + ".")
        and isinstance(recorded_at, str)
        and applied_at < parse_timestamp(recorded_at)
    ):
        raise StaleVersionError(
            "the intent was applied before the last recorded publication",
            reason="stale_intent",
        )
    return cast(Stage, stage), publication


def mcp_publication_document(
    doc: Mapping[str, Any],
    server_id: str,
    stage: Stage,
    publication: Mapping[str, Any],
    intent_id: str,
    now: datetime,
) -> dict[str, Any]:
    """The McpServer document after recording ``stage``: attributes plus provenance."""
    attributes = {
        k: v for k, v in mcp_attributes(doc).items() if not k.startswith(ATTRIBUTE_PREFIX)
    }
    state = _AFTER[stage]
    attributes[ATTRIBUTE_PREFIX + "state"] = state
    attributes[ATTRIBUTE_PREFIX + "intent_id"] = intent_id
    gateway_id = str(publication.get("gateway_id"))
    if state != "unpublished":
        created, shared = publication_resources(server_id)
        previous = mcp_attr(doc, "api_path")
        api_path = publication.get("api_path") or previous
        attributes[ATTRIBUTE_PREFIX + "gateway_id"] = gateway_id
        attributes[ATTRIBUTE_PREFIX + "api_path"] = api_path if isinstance(api_path, str) else None
        attributes[ATTRIBUTE_PREFIX + "audience_named_value"] = publication.get(
            "audience_named_value"
        ) or mcp_attr(doc, "audience_named_value")
        attributes[ATTRIBUTE_PREFIX + "created"] = ",".join(created)
        attributes[ATTRIBUTE_PREFIX + "shared"] = ",".join(shared)
    out = dict(doc)
    out["attributes"] = attributes
    out["provenance"] = {
        "method": "declared",
        "source_id": f"{CONNECTOR_SOURCE}.{gateway_id}",
        "connector_version": CONNECTOR_VERSION,
        "recorded_at": format_timestamp(now),
    }
    return out
