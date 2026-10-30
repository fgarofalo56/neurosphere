"""Publish a catalog MCP server through the gateway (PRP-34 item 6): ``mcp_server_publish`` and
``mcp_server_unpublish``, as an ``IntentTranslator`` for target kind ``mcp_server``.

Target and diff
---------------
The target is the catalog ``McpServer`` itself (``entity_type = mcp_server``, canonical id of the
catalog entity). The diff is one ``replace /publication`` operation whose value is a
:class:`McpPublication` (plus the ``test /plan_digest`` operation ``dry_run`` binds in). The
gateway named in it must be the gateway this connector is bound to.

Stages and fail-closed ordering
-------------------------------
The shared applier reverses every completed step when a later step fails, so a deny written in
the same plan as the change it guards would be undone by that reversal. Deny-first is therefore
a STAGE of its own, and the connector refuses a change or a removal unless the deny is already
in place on the gateway:

========== ======================== ============== ==============================================
stage      kind                     target_version writes
========== ======================== ============== ==============================================
publish    ``mcp_server_publish``   ``mcp-absent`` backend, enforcement fragment, MCP API, API
                                                   policy, PRM operation (+ shared metadata API)
deny       publish or unpublish     ``mcp-published`` API policy := deny (503); nothing else
change     ``mcp_server_publish``   ``mcp-denied`` backend, fragment, API, PRM operation, API
                                                   policy := enforcement (last per-server write)
remove     ``mcp_server_unpublish`` ``mcp-denied`` deletes API policy, PRM operation, API, fragment,
                                                   backend
========== ======================== ============== ==============================================

A failure in ``change`` or ``remove`` reverses only that stage's steps, so the API policy is
restored to its prior document, which is the deny: the deny stays and the failure is reported
(``rollback_failed`` with orphans, or the original error). Nothing ever restores the enforcement
automatically. ``target_version`` is the live publication state read from the gateway
(``mcp-absent``: no MCP API; ``mcp-denied``: the API policy is the deny; ``mcp-published``
otherwise), so a stage drafted against another state is ``stale_version``.

Ownership
---------
``publish`` refuses (``mcp_resource_exists``) when any per-server resource already exists: the
connector never adopts a resource it did not create, so every per-server resource of a publication
is ``created`` by NeuroSphere and ``remove`` deletes only those. The ``ns-mcp-metadata`` API (blank
path) and its policy are shared by every publication on the gateway: upserted with identical
content, never deleted by an unpublish. Publication is refused (``mcp_metadata_path_taken``) when
another API already owns the blank path, and (``mcp_api_path_taken``) when another API owns the
requested path. Both checks need an API path listing (:class:`ApiPathIndex`); without one the
connector refuses to publish (``mcp_api_paths_unreadable``), it never guesses.

Refusals (publish and change): SSE-only upstream (``mcp_sse_unsupported``), API-key upstream
(``mcp_api_key_upstream``), no audience (``mcp_audience_missing``), query string or fragment in the
URL (``mcp_url_query``), URL not ending in ``/mcp`` (``mcp_url_not_mcp``), a named value the
enforcement references that does not exist on the gateway (``mcp_named_value_missing``).

Named values: tenant and audience are referenced as ``{{name}}`` and must already exist (the
operator provisions them, as Key Vault references or plain values). The plan never creates a
named value, so the item 1 rule (named values only for key-authenticated backends) is unchanged.

The managed identity of the gateway is attached with ``authentication-managed-identity`` in the
enforcement fragment when the server auth kind is ``managed_identity``; the backend itself carries
no credentials object (the ARM backend managed-identity credential shape was not confirmed against
Learn, and a literal or unknown credential is never written).

Logging: MCP APIs log zero body bytes. No policy here reads a request or response body and
forwarding runs with buffering off, so streamable HTTP stays unbuffered.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol, cast, runtime_checkable
from urllib.parse import urlsplit, urlunsplit

import httpx
from neurosphere_connector.write import WriteRequest
from neurosphere_core.cloud.profile import profile_for
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    DependencyTransientError,
    InvalidSchemaError,
)
from neurosphere_core.gateway.models import GATEWAY_ID_PATTERN, normalize_arm_id
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from neurosphere_connector_apim_gateway.arm import APIM_API_VERSION, ApimArm, map_status
from neurosphere_connector_apim_gateway.compare import payload_matches
from neurosphere_connector_apim_gateway.gateway import GatewayRef
from neurosphere_connector_apim_gateway.inmemory import InMemoryApim
from neurosphere_connector_apim_gateway.models import ResourceSpec, ResourceType, classify_path
from neurosphere_connector_apim_gateway.policies import fragment_payload
from neurosphere_connector_apim_gateway.policies.mcp_publication import (
    McpGrantLimit,
    render_mcp_api_policy,
    render_mcp_deny_policy,
    render_mcp_prm_policy,
    render_mcp_server_enforcement,
)
from neurosphere_connector_apim_gateway.translate import PLAN_DIGEST_PATH

__all__ = [
    "ACTION_KIND_MISMATCH",
    "KIND_STAGES",
    "MCP_SERVER_ENTITY_TYPE",
    "METADATA_API",
    "PUBLICATION_PATH",
    "STAGE_VERSIONS",
    "TENANT_NAMED_VALUE",
    "VERSION_ABSENT",
    "VERSION_DENIED",
    "VERSION_PUBLISHED",
    "ApiPathIndex",
    "HttpApiPathIndex",
    "InMemoryApiPathIndex",
    "McpGrant",
    "McpPublication",
    "McpResourceNames",
    "McpServerTranslator",
    "check_mcp_kind",
    "publication_prefix",
    "resource_names",
]

MCP_SERVER_ENTITY_TYPE: Final = "mcp_server"
PUBLICATION_PATH: Final = "/publication"
#: Shared API holding every publication's protected-resource-metadata operation (blank path).
METADATA_API: Final = "ns-mcp-metadata"
#: Named value with the Entra tenant id, shared by every publication on a gateway.
TENANT_NAMED_VALUE: Final = "ns-mcp-tenant-id"
VERSION_ABSENT: Final = "mcp-absent"
VERSION_PUBLISHED: Final = "mcp-published"
VERSION_DENIED: Final = "mcp-denied"
Stage = Literal["publish", "deny", "change", "remove"]
#: The live publication state each stage must be drafted against (the deny-first rule).
STAGE_VERSIONS: Final[Mapping[str, str]] = {
    "publish": VERSION_ABSENT,
    "deny": VERSION_PUBLISHED,
    "change": VERSION_DENIED,
    "remove": VERSION_DENIED,
}
PUBLISH_KIND: Final = "mcp_server_publish"
UNPUBLISH_KIND: Final = "mcp_server_unpublish"
#: The stages each action kind may carry (PRP-34 item 10): ``remove`` never rides on a publish
#: and ``publish``/``change`` never on an unpublish. ``WriteRequest`` carries no kind, so the
#: executor and the API planning view check it through ``check_kind`` before a plan is made.
KIND_STAGES: Final[Mapping[str, frozenset[str]]] = {
    PUBLISH_KIND: frozenset({"publish", "deny", "change"}),
    UNPUBLISH_KIND: frozenset({"deny", "remove"}),
}
ACTION_KIND_MISMATCH: Final = "action_kind_mismatch"
PRM_PREFIX: Final = "/.well-known/oauth-protected-resource"
_MCP_SUFFIX: Final = "/mcp"
_NAME = r"^[A-Za-z0-9._-]{1,256}$"
_API_PATH = r"^[a-z0-9][a-z0-9-]{0,62}$"
_MAX_PATH_PAGES: Final = 20


def publication_prefix(canonical_id: str) -> str:
    """Deterministic resource-name prefix of one catalog MCP server (``ns-mcp-`` + 16 hex)."""
    return "ns-mcp-" + hashlib.sha256(canonical_id.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class McpResourceNames:
    """Relative ARM paths of one publication: per-server resources and the shared ones."""

    prefix: str

    @property
    def backend(self) -> str:
        return f"backends/{self.prefix}"

    @property
    def fragment_id(self) -> str:
        return f"{self.prefix}-enforce"

    @property
    def fragment(self) -> str:
        return f"policyFragments/{self.fragment_id}"

    @property
    def api(self) -> str:
        return f"apis/{self.prefix}"

    @property
    def api_policy(self) -> str:
        return f"apis/{self.prefix}/policies/policy"

    @property
    def prm_operation(self) -> str:
        return f"apis/{METADATA_API}/operations/{self.prefix}-prm"

    @property
    def metadata_api(self) -> str:
        return f"apis/{METADATA_API}"

    @property
    def metadata_policy(self) -> str:
        return f"apis/{METADATA_API}/policies/policy"

    @property
    def per_server(self) -> tuple[str, ...]:
        """Created by the publication and removed by the unpublish (dependency order)."""
        return (self.backend, self.fragment, self.api, self.prm_operation, self.api_policy)

    @property
    def shared(self) -> tuple[str, ...]:
        """Shared by every publication on the gateway; never deleted by an unpublish."""
        return (self.metadata_api, self.metadata_policy)


def resource_names(canonical_id: str) -> McpResourceNames:
    return McpResourceNames(prefix=publication_prefix(canonical_id))


class McpGrant(BaseModel):
    """One direct (``oid``) grant on the server and its MCP calls per minute (null: no limit)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    oid: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    calls_per_minute: int | None = Field(default=None, ge=1, le=1_000_000)


class McpPublication(BaseModel):
    """The value of ``replace /publication``: what the maker confirms and the approver approves."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: Stage
    gateway_id: str = Field(pattern=GATEWAY_ID_PATTERN)
    url: str | None = Field(default=None, max_length=2048)
    transport: Literal["streamable_http", "sse"] | None = None
    auth_kind: Literal["entra", "managed_identity", "none", "api_key"] | None = None
    audience: str | None = Field(default=None, max_length=512)
    api_path: str | None = Field(default=None, pattern=_API_PATH)
    audience_named_value: str | None = Field(default=None, pattern=_NAME)
    grants: tuple[McpGrant, ...] = Field(default=(), max_length=256)

    @model_validator(mode="after")
    def _one_grant_per_principal(self) -> McpPublication:
        if len({g.oid for g in self.grants}) != len(self.grants):
            raise ValueError("one grant per principal")
        return self


@dataclass(frozen=True)
class _Upstream:
    backend_url: str
    api_path: str
    audience_named_value: str
    managed_identity: bool


# -- API path index (blank-path and path-collision checks) ------------------------------------


@runtime_checkable
class ApiPathIndex(Protocol):
    async def api_paths(self) -> dict[str, str]:
        """``{api name: path}`` for every API on the gateway (names only, nothing else)."""
        ...


class InMemoryApiPathIndex:
    """``ApiPathIndex`` over the ``InMemoryApim`` test double."""

    def __init__(self, apim: InMemoryApim) -> None:
        self._apim = apim

    async def api_paths(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for path, (props, _) in self._apim.resources.items():
            parts = path.split("/")
            if len(parts) == 2 and parts[0] == "apis":
                value = props.get("path")
                out[parts[1]] = value if isinstance(value, str) else ""
        return out


class HttpApiPathIndex:
    """``ApiPathIndex`` over ARM REST (``GET {service}/apis``), paging on the same host only.

    Uses the same bearer-authenticated client as ``HttpApimArm``. Keeps each API's ``name`` and
    ``properties.path``; nothing else of the response is retained.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        service_arm_id: str,
        *,
        api_version: str = APIM_API_VERSION,
    ) -> None:
        self._client = client
        self._service = normalize_arm_id(service_arm_id)
        self._api_version = api_version

    async def api_paths(self) -> dict[str, str]:
        url = f"{self._service}/apis?api-version={self._api_version}"
        base = urlsplit(str(self._client.base_url))
        out: dict[str, str] = {}
        for _ in range(_MAX_PATH_PAGES):
            try:
                response = await self._client.get(url)
            except (httpx.TransportError, httpx.TimeoutException):
                raise DependencyTransientError(
                    "ARM is unreachable", reason="arm_unreachable"
                ) from None
            if response.status_code >= 300:
                raise map_status(response.status_code)
            try:
                body: object = response.json()
            except ValueError:
                body = None
            if not isinstance(body, dict):
                raise DependencyTransientError(
                    "ARM returned an unexpected body",
                    reason="arm_invalid_body",
                    upstream_invalid=True,
                )
            page = cast(dict[str, Any], body)
            for item in cast(list[object], page.get("value") or []):
                if not isinstance(item, Mapping):
                    continue
                entry = cast(Mapping[str, Any], item)
                name = entry.get("name")
                props = entry.get("properties")
                path = props.get("path") if isinstance(props, Mapping) else None
                if isinstance(name, str):
                    out[name] = path if isinstance(path, str) else ""
            next_link = page.get("nextLink")
            if not isinstance(next_link, str) or not next_link:
                return out
            target = urlsplit(next_link)
            if target.scheme != "https" or target.netloc.lower() != base.netloc.lower():
                raise DependencyTransientError(
                    "ARM paging left the management host", reason="arm_invalid_body"
                )
            url = next_link
        raise DependencyTransientError("too many API pages", reason="arm_paging_limit")


# -- translator -------------------------------------------------------------------------------


def _bad(reason: str, detail: str) -> InvalidSchemaError:
    return InvalidSchemaError(detail, reason=reason)


def parse_publication(request: WriteRequest) -> McpPublication:
    """The single ``replace /publication`` operation of the diff (``/plan_digest`` aside)."""
    ops = [op for op in request.proposed_diff.operations if op.path != PLAN_DIGEST_PATH]
    if len(ops) != 1 or ops[0].path != PUBLICATION_PATH or ops[0].op not in ("add", "replace"):
        raise _bad("unsupported_operation", "the diff must be one replace /publication")
    value = ops[0].value
    if not isinstance(value, Mapping):
        raise _bad("bad_payload", "the publication must be an object")
    try:
        return McpPublication.model_validate(value)
    except ValidationError:
        raise _bad("bad_payload", "the publication is not valid") from None


def check_mcp_kind(action_kind: str, request: WriteRequest) -> None:
    """Refuse a stage the action kind may not carry (``action_kind_mismatch``)."""
    pub = parse_publication(request)
    if pub.stage not in KIND_STAGES.get(action_kind, frozenset()):
        raise _bad(ACTION_KIND_MISMATCH, f"stage {pub.stage} is not part of {action_kind}")


def _upstream(pub: McpPublication) -> _Upstream:
    """Refusals of an unpublishable upstream; the upstream facts of a publishable one."""
    if (
        pub.url is None
        or pub.transport is None
        or pub.auth_kind is None
        or pub.api_path is None
        or pub.audience_named_value is None
    ):
        raise _bad("mcp_publication_incomplete", "publish and change need the full upstream")
    if pub.transport == "sse":
        raise CapabilityUnavailableError(
            "mcp_sse_unsupported", "only streamable HTTP MCP servers can be published"
        )
    if pub.auth_kind == "api_key":
        raise CapabilityUnavailableError(
            "mcp_api_key_upstream", "an API-key upstream cannot be published (no key passthrough)"
        )
    if not pub.audience:
        raise _bad("mcp_audience_missing", "the server has no Entra audience to validate")
    parts = urlsplit(pub.url)
    if parts.query or parts.fragment or "?" in pub.url or "#" in pub.url:
        raise _bad("mcp_url_query", "the server URL carries a query string or fragment")
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise _bad("mcp_url_invalid", "the server URL must be https with a host and no user info")
    if not parts.path.endswith(_MCP_SUFFIX):
        raise _bad("mcp_url_not_mcp", "the server URL must end in /mcp")
    base = urlunsplit((parts.scheme, parts.netloc, parts.path[: -len(_MCP_SUFFIX)], "", ""))
    return _Upstream(
        backend_url=base,
        api_path=pub.api_path,
        audience_named_value=pub.audience_named_value,
        managed_identity=pub.auth_kind == "managed_identity",
    )


def _policy(xml: str) -> dict[str, str]:
    return fragment_payload(xml)


class McpServerTranslator:
    """Target ``mcp_server``: publication stages for one catalog MCP server (see module doc)."""

    def __init__(self, *, paths: ApiPathIndex | None = None) -> None:
        self._paths = paths

    @property
    def entity_types(self) -> frozenset[str]:
        return frozenset({MCP_SERVER_ENTITY_TYPE})

    # -- shared checks ---------------------------------------------------------------------

    @staticmethod
    def _check_target(gateway: GatewayRef, request: WriteRequest, pub: McpPublication) -> None:
        cloud = request.target.canonical_id.split(":", 1)[0]
        if cloud != gateway.cloud.value:
            raise _bad("cloud_mismatch", "target cloud differs from connector")
        if pub.gateway_id != gateway.gateway_id:
            raise _bad("wrong_entity", "the publication names another gateway")

    def check_kind(self, action_kind: str, request: WriteRequest) -> None:
        check_mcp_kind(action_kind, request)

    @staticmethod
    def _check_stage(request: WriteRequest, pub: McpPublication) -> None:
        """Stage against the live publication state. The stage-to-kind tie (``remove`` only
        under ``mcp_server_unpublish``) is ``check_kind``: the request itself carries no kind."""
        expected = STAGE_VERSIONS[pub.stage]
        if request.target_version == expected:
            return
        if pub.stage in ("change", "remove"):
            raise _bad(
                "mcp_deny_first_required",
                "a change or removal is planned only against a denied API (deny stage first)",
            )
        raise _bad("mcp_stage_out_of_order", f"stage {pub.stage} needs version {expected}")

    async def _state(self, arm: ApimArm, names: McpResourceNames) -> str:
        if await arm.get(names.api) is None:
            return VERSION_ABSENT
        policy = await arm.get(names.api_policy)
        deny = _policy(render_mcp_deny_policy())
        if policy is not None and payload_matches(ResourceType.API_POLICY, deny, policy.properties):
            return VERSION_DENIED
        return VERSION_PUBLISHED

    async def _check_paths(self, names: McpResourceNames, api_path: str) -> None:
        if self._paths is None:
            raise CapabilityUnavailableError(
                "mcp_api_paths_unreadable",
                "the gateway's API paths cannot be listed; publication refused (fail closed)",
            )
        paths = await self._paths.api_paths()
        own = names.api.split("/", 1)[1]
        for name, path in paths.items():
            if path.strip("/") == "" and name != METADATA_API:
                raise CapabilityUnavailableError(
                    "mcp_metadata_path_taken", "another API already owns the blank path"
                )
            if path.strip("/") == api_path and name != own:
                raise CapabilityUnavailableError(
                    "mcp_api_path_taken", "another API already owns the requested path"
                )

    @staticmethod
    async def _check_named_values(arm: ApimArm, up: _Upstream) -> None:
        for name in (TENANT_NAMED_VALUE, up.audience_named_value):
            if await arm.get(f"namedValues/{name}") is None:
                raise CapabilityUnavailableError(
                    "mcp_named_value_missing",
                    f"named value {name} does not exist on the gateway",
                )

    @staticmethod
    async def _check_unowned(arm: ApimArm, names: McpResourceNames) -> None:
        for name in names.per_server:
            if await arm.get(name) is not None:
                raise CapabilityUnavailableError(
                    "mcp_resource_exists",
                    "a resource of this publication already exists; it is never adopted",
                )

    # -- IntentTranslator ------------------------------------------------------------------

    async def current_version(
        self, arm: ApimArm, gateway: GatewayRef, request: WriteRequest
    ) -> str:
        pub = parse_publication(request)
        self._check_target(gateway, request, pub)
        names = resource_names(request.target.canonical_id)
        state = await self._state(arm, names)
        if pub.stage in ("publish", "change"):
            up = _upstream(pub)
            await self._check_named_values(arm, up)
            await self._check_paths(names, up.api_path)
            if pub.stage == "publish" and state == VERSION_ABSENT:
                await self._check_unowned(arm, names)
        return state

    def specs(self, gateway: GatewayRef, request: WriteRequest) -> list[ResourceSpec]:
        pub = parse_publication(request)
        self._check_target(gateway, request, pub)
        self._check_stage(request, pub)
        names = resource_names(request.target.canonical_id)
        if pub.stage == "deny":
            return [_api_policy(names, render_mcp_deny_policy())]
        if pub.stage == "remove":
            # Deletes run in reverse dependency order: the (deny) API policy, the PRM operation,
            # the API, the fragment, the backend. On a failure the reversal restores them newest
            # first, ending with the deny policy, so the API is never left serving.
            return [
                ResourceSpec(resource_type=_type(name), name=name, operation="delete")
                for name in names.per_server
            ]
        up = _upstream(pub)
        return _publish_specs(gateway, names, up, pub.grants)


def _type(name: str) -> ResourceType:
    rtype = classify_path(name)
    if rtype is None:  # pragma: no cover - names are built from validated segments
        raise _bad("bad_path", "not a resource this connector writes")
    return rtype


def _api_policy(names: McpResourceNames, xml: str) -> ResourceSpec:
    return ResourceSpec(
        resource_type=ResourceType.API_POLICY, name=names.api_policy, payload=_policy(xml)
    )


def _publish_specs(
    gateway: GatewayRef,
    names: McpResourceNames,
    up: _Upstream,
    grants: Sequence[McpGrant],
) -> list[ResourceSpec]:
    enforcement = render_mcp_server_enforcement(
        tenant_named_value=TENANT_NAMED_VALUE,
        audience_named_value=up.audience_named_value,
        counter_prefix=names.prefix,
        grants=[McpGrantLimit(oid=g.oid, calls_per_minute=g.calls_per_minute) for g in grants],
        managed_identity=up.managed_identity,
    )
    prm = render_mcp_prm_policy(
        login_host=profile_for(gateway.cloud).login_host, tenant_named_value=TENANT_NAMED_VALUE
    )
    return [
        ResourceSpec(
            resource_type=ResourceType.BACKEND,
            name=names.backend,
            payload={
                "protocol": "http",
                "url": up.backend_url,
                "description": f"NeuroSphere MCP publication {names.prefix}",
            },
        ),
        ResourceSpec(
            resource_type=ResourceType.POLICY_FRAGMENT,
            name=names.fragment,
            payload=fragment_payload(
                enforcement, description=f"NeuroSphere MCP enforcement {names.prefix}"
            ),
        ),
        # Passthrough MCP API (streamable HTTP). No serviceUrl or backend on the API itself:
        # traffic is routed only by the API policy, so the API cannot forward anything before
        # its enforcement policy lands (a new API is closed until its policy is in place).
        ResourceSpec(
            resource_type=ResourceType.API,
            name=names.api,
            payload={
                "displayName": f"MCP {names.prefix}",
                "path": up.api_path,
                "protocols": ["https"],
                "subscriptionRequired": False,
                "type": "mcp",
                "mcpProperties": {"transportType": "streamable"},
            },
        ),
        ResourceSpec(
            resource_type=ResourceType.API_OPERATION,
            name=names.prm_operation,
            payload={
                "displayName": f"PRM {names.prefix}",
                "method": "GET",
                "urlTemplate": f"{PRM_PREFIX}/{up.api_path}{_MCP_SUFFIX}",
            },
        ),
        _api_policy(
            names, render_mcp_api_policy(fragment_id=names.fragment_id, backend_id=names.prefix)
        ),
        # Shared protected-resource-metadata API on the blank path (identical for every
        # publication, so a later publication finds it unchanged and writes nothing).
        ResourceSpec(
            resource_type=ResourceType.API,
            name=names.metadata_api,
            payload={
                "displayName": "NeuroSphere MCP metadata",
                "path": "",
                "protocols": ["https"],
                "subscriptionRequired": False,
            },
        ),
        ResourceSpec(
            resource_type=ResourceType.API_POLICY,
            name=names.metadata_policy,
            payload=_policy(prm),
        ),
    ]
