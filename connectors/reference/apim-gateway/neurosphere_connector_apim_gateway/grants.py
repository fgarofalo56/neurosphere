"""Grant publication translator (PRP-34 item 5): ``grant_publish`` and ``grant_unpublish``.

Target kind ``grant`` (the catalog Grant is the target; the gateway the connector is bound to is
named inside the diff and must equal it). One translator serves both kinds: the diff grammar
tells them apart.

Publish diff (one ``add`` operation)::

    add /publication  {gateway_id, api_id, access, principal_kind, principal_object_id,
                       tokens_per_minute?, token_quota?, token_quota_period?,
                       tenant_named_value?, audience_named_value?}

Unpublish diff (``remove /publication`` guarded by three ``test`` operations)::

    test /publication/gateway_id    <gateway id>
    test /publication/apply_record  <id of the publish apply record>
    test /publication/resources     [relative ARM paths to delete]
    remove /publication

The resource names are derived from the grant id (``publication_names``) so a grant can never
address a resource outside its own ``ns-grant-*`` namespace; an unpublish may name only a subset
of those, and (PRP-34 item 10) only resources the named publish apply record recorded
``created``: the translator reads that record from the connector's apply-record store while it
plans (``dry_run`` and ``apply``) and refuses (``resource_not_created``) any listed resource the
publication merely found, and a record of another grant or gateway or of a publish that did not
succeed (``ownership_record_mismatch``). Without a record store an unpublish is refused
(``ownership_unverifiable``): a resource is never deleted on the diff's word alone.

The diff grammar is tied to the action kind (``check_kind``): a publish diff only under
``grant_publish``, an unpublish diff only under ``grant_unpublish`` (``action_kind_mismatch``).

What a publish plans (dependency order is the planner's job): a policy fragment with
``llm-token-limit`` + ``llm-emit-token-metric`` (the item 1 grant template), a product, a product
policy that includes the fragment, the product-API link to the target API, and then EITHER

* ``access = subscription``: an APIM subscription scoped to the product (key-authenticated
  principal). The subscription key is never read: the connector's ARM layer has no POST and
  never calls ``listSecrets``; the principal retrieves the key from the portal or the operator.
  The counter key is the subscription id; OR
* ``access = entra``: a ``validate-azure-ad-token`` block in the product policy that requires the
  principal ``oid`` claim (user, application, agent) or the ``groups`` claim (Entra group). The
  counter key is the caller ``oid``. Entra ``groups`` overage (a token with many groups carries
  a ``_claim_names`` pointer instead of the claim) omits ``groups``, so a group grant FAILS
  CLOSED and a member needs a direct grant.

``tenant_named_value`` / ``audience_named_value`` are named-value NAMES that must already exist on
the gateway; their values are never inlined.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Final, Literal

from neurosphere_connector.write import WriteRequest
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from neurosphere_connector_apim_gateway.arm import ApimArm, check_path
from neurosphere_connector_apim_gateway.gateway import GatewayRef
from neurosphere_connector_apim_gateway.models import ResourceSpec, ResourceType, StepOwnership
from neurosphere_connector_apim_gateway.policies import (
    GrantLimits,
    fragment_payload,
    named_value_ref,
    render_api_policy,
    render_grant_fragment,
)
from neurosphere_connector_apim_gateway.records import ApplyRecordStore
from neurosphere_connector_apim_gateway.translate import PLAN_DIGEST_PATH

__all__ = [
    "ACTION_KIND_MISMATCH",
    "APPLY_RECORD_PATH",
    "GRANT_ENTITY_TYPE",
    "PUBLICATION_PATH",
    "PUBLISH_KIND",
    "RESOURCES_PATH",
    "UNPUBLISH_KIND",
    "VERSION_PUBLISHED",
    "VERSION_UNPUBLISHED",
    "GrantPublicationTranslator",
    "PublicationNames",
    "PublicationSpec",
    "check_grant_kind",
    "fragment_id_for",
    "is_publish_diff",
    "publication_names",
]

GRANT_ENTITY_TYPE: Final = "grant"
PUBLICATION_PATH: Final = "/publication"
RESOURCES_PATH: Final = "/publication/resources"
APPLY_RECORD_PATH: Final = "/publication/apply_record"
_GATEWAY_PATH: Final = "/publication/gateway_id"
PUBLISH_KIND: Final = "grant_publish"
UNPUBLISH_KIND: Final = "grant_unpublish"
#: Refusal reason when a diff's grammar does not belong to the intent's action kind.
ACTION_KIND_MISMATCH: Final = "action_kind_mismatch"
#: The version a grant publication intent binds to: it moves when the product appears or goes.
VERSION_UNPUBLISHED: Final = "grant-unpublished"
VERSION_PUBLISHED: Final = "grant-published"

_SEG = r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}"
_GUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
_NAMED_VALUE = re.compile(r"^[A-Za-z0-9._-]{1,256}$")
_API_ID = re.compile(rf"^{_SEG}$")
_GATEWAY_ID = re.compile(r"^gw-[0-9a-f]{32}$")
_SLUG_BAD = re.compile(r"[^a-z0-9]+")
_QUOTA_PERIODS: Final = ("Hourly", "Daily", "Weekly", "Monthly", "Yearly")
_DEFAULT_TENANT_NV: Final = "ns-tenant-id"
_DEFAULT_AUDIENCE_NV: Final = "ns-api-audience"

Access = Literal["subscription", "entra"]
PrincipalKind = Literal["user", "application", "agent", "entra_group"]


class PublicationNames(BaseModel):
    """The resources one grant owns on a gateway, all inside the ``ns-grant-`` namespace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fragment: str
    product: str
    product_policy: str
    subscription: str
    link_prefix: str

    def link(self, api_id: str) -> str:
        return f"{self.link_prefix}{api_id}"


def publication_names(grant_id: str) -> PublicationNames:
    """Deterministic, collision-safe names from the grant canonical id."""
    tail = grant_id.rsplit(":", 1)[-1].lower()
    slug = _SLUG_BAD.sub("-", tail).strip("-")[:40].strip("-") or "grant"
    suffix = hashlib.sha256(grant_id.encode("utf-8")).hexdigest()[:8]
    base = f"ns-grant-{slug}-{suffix}"
    return PublicationNames(
        fragment=f"policyFragments/{base}",
        product=f"products/{base}",
        product_policy=f"products/{base}/policies/policy",
        subscription=f"subscriptions/{base}-sub",
        link_prefix=f"products/{base}/apiLinks/",
    )


def fragment_id_for(grant_id: str) -> str:
    """The policy fragment id a grant publication creates (``ns-grant-<slug>-<sha8>``); the
    budget-cap translator edits this very fragment (PRP-34 item 10)."""
    return publication_names(grant_id).fragment.split("/", 1)[1]


class PublicationSpec(BaseModel):
    """The value of ``add /publication``; validated here, never trusted from the wire."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    gateway_id: str = Field(pattern=r"^gw-[0-9a-f]{32}$")
    api_id: str = Field(pattern=rf"^{_SEG}$")
    access: Access
    principal_kind: PrincipalKind
    principal_object_id: str = Field(pattern=_GUID)
    tokens_per_minute: int | None = Field(default=None, ge=1)
    token_quota: int | None = Field(default=None, ge=1)
    token_quota_period: str | None = None
    tenant_named_value: str = Field(default=_DEFAULT_TENANT_NV, pattern=_NAMED_VALUE.pattern)
    audience_named_value: str = Field(default=_DEFAULT_AUDIENCE_NV, pattern=_NAMED_VALUE.pattern)


def _bad(detail: str, reason: str) -> InvalidSchemaError:
    return InvalidSchemaError(detail, reason=reason)


def _operations(request: WriteRequest) -> list[Any]:
    return [op for op in request.proposed_diff.operations if op.path != PLAN_DIGEST_PATH]


def _gateway_matches(gateway: GatewayRef, request: WriteRequest, gateway_id: str) -> None:
    cloud = request.target.canonical_id.partition(":")[0]
    if cloud != gateway.cloud.value:
        raise _bad("target cloud differs from connector", "cloud_mismatch")
    if gateway_id != gateway.gateway_id:
        raise _bad("the diff names another gateway", "wrong_entity")


def _publish_spec(operations: list[Any]) -> PublicationSpec | None:
    """The publication of a publish diff, or None when the diff is not a publish."""
    if len(operations) != 1 or operations[0].path != PUBLICATION_PATH:
        return None
    op = operations[0]
    if op.op != "add" or not isinstance(op.value, dict):
        raise _bad("publish needs one add /publication object", "bad_payload")
    try:
        return PublicationSpec.model_validate(op.value)
    except ValidationError as exc:
        raise _bad("invalid publication", "bad_payload") from exc


def _unpublish(operations: list[Any]) -> tuple[str, list[str], str | None]:
    """(gateway id, listed resources, publish apply record id) of an unpublish diff."""
    by_path = {op.path: op for op in operations}
    remove = by_path.get(PUBLICATION_PATH)
    gate = by_path.get(_GATEWAY_PATH)
    listed = by_path.get(RESOURCES_PATH)
    record = by_path.get(APPLY_RECORD_PATH)
    if (
        len(operations) != (3 if record is None else 4)
        or len(by_path) != len(operations)
        or remove is None
        or remove.op != "remove"
        or gate is None
        or gate.op != "test"
        or not isinstance(gate.value, str)
        or listed is None
        or listed.op != "test"
        or not isinstance(listed.value, list)
        or not all(isinstance(n, str) for n in listed.value)
        or (record is not None and (record.op != "test" or not isinstance(record.value, str)))
    ):
        raise _bad("unsupported grant diff", "unsupported_operation")
    record_id = None if record is None else str(record.value)
    return gate.value, [str(n) for n in listed.value], record_id


def is_publish_diff(operations: list[Any]) -> bool:
    """True for the publish grammar: exactly one ``add /publication`` (pure, no validation)."""
    return (
        len(operations) == 1
        and operations[0].path == PUBLICATION_PATH
        and operations[0].op == "add"
    )


def check_grant_kind(action_kind: str, request: WriteRequest) -> None:
    """Refuse a publication diff under the wrong action kind (``action_kind_mismatch``): a
    publish diff only under ``grant_publish``, an unpublish diff only under ``grant_unpublish``."""
    operations = _operations(request)
    if is_publish_diff(operations):
        expected = PUBLISH_KIND
    else:
        _unpublish(operations)  # anything else is not a publication diff at all
        expected = UNPUBLISH_KIND
    if action_kind != expected:
        raise _bad("the diff is not a publication of this action kind", ACTION_KIND_MISMATCH)


def _quota_period(spec: PublicationSpec) -> str | None:
    period = spec.token_quota_period
    if period is not None and period not in _QUOTA_PERIODS:
        raise _bad("unsupported token_quota_period", "bad_payload")
    return period


def _entra_claim_block(spec: PublicationSpec) -> str:
    """``validate-azure-ad-token`` requiring the principal's ``oid`` or ``groups`` claim."""
    claim, match = ("groups", "any") if spec.principal_kind == "entra_group" else ("oid", "all")
    tenant = named_value_ref(spec.tenant_named_value)
    audience = named_value_ref(spec.audience_named_value)
    return (
        f'\n\t\t<validate-azure-ad-token tenant-id="{tenant}" header-name="Authorization" '
        'failed-validation-httpcode="401" failed-validation-error-message="Unauthorized">'
        f"\n\t\t\t<audiences><audience>{audience}</audience></audiences>"
        "\n\t\t\t<required-claims>"
        f'\n\t\t\t\t<claim name="{claim}" match="{match}"><value>{spec.principal_object_id}</value>'
        "</claim>"
        "\n\t\t\t</required-claims>"
        "\n\t\t</validate-azure-ad-token>"
    )


def _product_policy(spec: PublicationSpec, fragment_id: str) -> str:
    xml = render_api_policy([fragment_id])
    if spec.access == "entra":
        xml = xml.replace("<base />", "<base />" + _entra_claim_block(spec), 1)
    return xml


class GrantPublicationTranslator:
    """``IntentTranslator`` for target ``grant`` (publish and unpublish).

    ``records`` is the connector's apply-record store: an unpublish is checked against the
    publish record it names, and refused without a store (``ownership_unverifiable``).
    """

    def __init__(self, *, records: ApplyRecordStore | None = None) -> None:
        self._records = records

    @property
    def entity_types(self) -> frozenset[str]:
        return frozenset({GRANT_ENTITY_TYPE})

    def check_kind(self, action_kind: str, request: WriteRequest) -> None:
        check_grant_kind(action_kind, request)

    async def _check_ownership(
        self, gateway: GatewayRef, request: WriteRequest, listed: list[str], record_id: str | None
    ) -> None:
        """Every listed resource must be recorded ``created`` by the named publish record."""
        if self._records is None:
            raise CapabilityUnavailableError(
                "ownership_unverifiable",
                "no apply-record store: the unpublish cannot prove what the publish created",
            )
        if record_id is None:
            raise _bad("the unpublish must name the publish apply record", "apply_record_required")
        record = await self._records.latest(record_id)
        if (
            record is None
            or record.target != request.target.canonical_id
            or record.gateway_id != gateway.gateway_id
            or record.status != "succeeded"
        ):
            raise _bad(
                "the apply record is not a succeeded publish of this grant on this gateway",
                "ownership_record_mismatch",
            )
        created = {
            step.name
            for step in record.steps
            if step.operation == "upsert" and step.ownership == StepOwnership.CREATED
        }
        if not set(listed) <= created:
            raise _bad(
                "only resources the publication created may be deleted", "resource_not_created"
            )

    async def current_version(
        self, arm: ApimArm, gateway: GatewayRef, request: WriteRequest
    ) -> str:
        operations = _operations(request)
        publish = _publish_spec(operations)
        if publish is not None:
            _gateway_matches(gateway, request, publish.gateway_id)
        else:
            gateway_id, listed, record_id = _unpublish(operations)
            _gateway_matches(gateway, request, gateway_id)
            await self._check_ownership(gateway, request, listed, record_id)
        names = publication_names(request.target.canonical_id)
        product = await arm.get(names.product)
        if publish is not None and product is None:
            if await arm.get(f"apis/{publish.api_id}") is None:
                raise CapabilityUnavailableError(
                    "target_api_missing", "the target API is not on the gateway"
                )
        return VERSION_PUBLISHED if product is not None else VERSION_UNPUBLISHED

    def specs(self, gateway: GatewayRef, request: WriteRequest) -> list[ResourceSpec]:
        operations = _operations(request)
        publish = _publish_spec(operations)
        names = publication_names(request.target.canonical_id)
        if publish is None:
            return self._unpublish_specs(gateway, request, operations, names)
        _gateway_matches(gateway, request, publish.gateway_id)
        if publish.access == "entra":
            counter: Literal["subscription", "oid"] = "oid"
        else:
            counter = "subscription"
        try:
            limits = GrantLimits(
                counter_key=counter,
                tokens_per_minute=publish.tokens_per_minute,
                token_quota=publish.token_quota,
                token_quota_period=_quota_period(publish),
            )
        except ValueError as exc:
            raise _bad(
                "the grant carries no usable token limit", "grant_needs_token_limit"
            ) from exc
        fragment_id = names.fragment.split("/", 1)[1]
        product_id = names.product.split("/", 1)[1]
        out = [
            ResourceSpec(
                resource_type=ResourceType.POLICY_FRAGMENT,
                name=names.fragment,
                payload=fragment_payload(
                    render_grant_fragment(limits), description=f"NeuroSphere grant {fragment_id}"
                ),
            ),
            ResourceSpec(
                resource_type=ResourceType.PRODUCT,
                name=names.product,
                payload={
                    "displayName": f"NeuroSphere grant {fragment_id}",
                    "subscriptionRequired": publish.access == "subscription",
                    "state": "published",
                },
            ),
            ResourceSpec(
                resource_type=ResourceType.PRODUCT_POLICY,
                name=names.product_policy,
                payload=fragment_payload(_product_policy(publish, fragment_id)),
            ),
            ResourceSpec(
                resource_type=ResourceType.PRODUCT_API_LINK,
                name=names.link(publish.api_id),
                payload={"apiId": f"{gateway.arm_resource_id}/apis/{publish.api_id}"},
            ),
        ]
        if publish.access == "subscription":
            out.append(
                ResourceSpec(
                    resource_type=ResourceType.SUBSCRIPTION,
                    name=names.subscription,
                    payload={
                        "displayName": f"NeuroSphere grant {product_id}",
                        "scope": f"/products/{product_id}",
                        "state": "active",
                    },
                )
            )
        return out

    @staticmethod
    def _unpublish_specs(
        gateway: GatewayRef,
        request: WriteRequest,
        operations: list[Any],
        names: PublicationNames,
    ) -> list[ResourceSpec]:
        gateway_id, listed, _ = _unpublish(operations)
        _gateway_matches(gateway, request, gateway_id)
        if not listed or len(set(listed)) != len(listed):
            raise _bad("the unpublish names no (or a repeated) resource", "empty_plan")
        owned = {names.fragment, names.product, names.product_policy, names.subscription}
        out: list[ResourceSpec] = []
        for name in listed:
            if name not in owned and not (
                name.startswith(names.link_prefix)
                and _API_ID.fullmatch(name[len(names.link_prefix) :])
            ):
                raise _bad("the resource is not part of this grant publication", "wrong_entity")
            rtype = check_path(name)
            if rtype is None:  # pragma: no cover - owned names are valid ARM paths
                raise _bad("not a child resource", "bad_path")
            out.append(ResourceSpec(resource_type=rtype, name=name, operation="delete"))
        return out
