"""Target ``grant``: ``budget_cap_change`` rewrites a grant's ``llm-token-limit`` (PRP-34 item 4).

A cap change is a real gateway change: the grant's policy fragment (``grant-product.xml``) is
re-rendered with the new ``tokens-per-minute``, ``token-quota`` and ``token-quota-period``
attributes and PUT through the shared planner and applier, so it is digest-bound, written with
``If-Match`` from the preceding read, recorded with ownership ``found`` and the captured prior
fragment, verified by reading the fragment back and rolled back by restoring that prior
fragment. Nothing edits the catalog Grant document to stand in for the cap.

Diff grammar (target ``grant``, ``target_version`` = the fragment's ETag). The diff names the
COMPLETE desired limit set, because ``specs`` is pure and the fragment is rendered from the diff:

- ``test /target/kind`` (required): the Grant's ``target.kind``. ``mcp_server`` is refused with
  ``invalid_schema`` reason ``mcp_grant_token_limit``: MCP grants are call-limited only.
- ``test /counter_key`` (required): ``subscription`` or ``oid``. It must equal the live fragment's
  counter key: a cap change never moves a grant to another counter (one scope per grant).
- ``test /metric_namespace`` (optional, default ``neurosphere``): must equal the live one.
- ``add``/``replace`` at ``/limits/tokens_per_minute``, ``/limits/token_quota`` (positive
  integers) and ``/limits/quota_period`` (the Grant contract tokens ``hour``, ``day``, ``week``,
  ``month``, ``year``; ``minute`` has no APIM equivalent and is refused). ``remove`` at one of
  those paths drops that limit. Every limit the live fragment sets must be named by the diff
  (``invalid_schema`` reason ``cap_diff_incomplete``), so a limit is never dropped silently.

Safety checks that need the live fragment run in ``current_version`` while the fragment's ETag
still equals ``target_version`` (dry-run and apply). After our own write the ETag differs and
``verify`` only needs the version, so drift is then reported by verify's read-back comparison
instead of an exception. A live fragment that is not exactly a rendering of the grant template
(foreign content, a DTD, an unknown counter key) is refused (``grant_fragment_unrecognised``)
rather than overwritten; an MCP enforcement fragment is refused as ``mcp_grant_token_limit``.

The fragment id is ``grant_fragment_id(grant canonical id)`` unless the constructor is given the
naming function the grant publisher uses (PRP-34 item 5).
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Literal, cast

from neurosphere_connector.write import WriteRequest
from neurosphere_contracts.actions.v1.action_intent import ProposedDiff
from neurosphere_core.errors import CapabilityUnavailableError, InvalidSchemaError

from neurosphere_connector_apim_gateway.arm import ApimArm
from neurosphere_connector_apim_gateway.compare import normalize_xml
from neurosphere_connector_apim_gateway.gateway import GatewayRef
from neurosphere_connector_apim_gateway.models import ResourceSpec, ResourceType
from neurosphere_connector_apim_gateway.policies import (
    COUNTER_KEYS,
    GrantLimits,
    fragment_payload,
    render_grant_fragment,
)
from neurosphere_connector_apim_gateway.translate import PLAN_DIGEST_PATH

__all__ = [
    "BUDGET_CAP_KIND",
    "GRANT_ENTITY_TYPE",
    "LIMIT_ATTRIBUTES",
    "MCP_GRANT_TOKEN_LIMIT",
    "AttributeChange",
    "BudgetCapTranslator",
    "CapIntent",
    "attribute_diff",
    "grant_fragment_id",
    "limit_attributes",
    "parse_cap_diff",
    "parse_grant_fragment",
]

GRANT_ENTITY_TYPE: Final = "grant"
BUDGET_CAP_KIND: Final = "budget_cap_change"
MCP_GRANT_TOKEN_LIMIT: Final = "mcp_grant_token_limit"  # noqa: S105 - an error reason
LIMIT_ATTRIBUTES: Final = ("tokens-per-minute", "token-quota", "token-quota-period")
DEFAULT_METRIC_NAMESPACE: Final = "neurosphere"
MAX_FRAGMENT_CHARS: Final = 64 * 1024

_TARGET_KIND: Final = "/target/kind"
_COUNTER_KEY: Final = "/counter_key"
_NAMESPACE: Final = "/metric_namespace"
_LIMIT_PATHS: Final[Mapping[str, str]] = {
    "/limits/tokens_per_minute": "tokens_per_minute",
    "/limits/token_quota": "token_quota",
    "/limits/quota_period": "quota_period",
}
_TARGET_KINDS: Final = frozenset({"model_api", "model_deployment", "mcp_server"})
# Grant contract ``limits.quota_period`` token -> APIM ``token-quota-period`` value.
_PERIODS: Final[Mapping[str, str]] = {
    "hour": "Hourly",
    "day": "Daily",
    "week": "Weekly",
    "month": "Monthly",
    "year": "Yearly",
}
_PERIOD_TOKENS: Final = {v: k for k, v in _PERIODS.items()}
_COUNTER_BY_EXPR: Final = {expr: key for key, expr in COUNTER_KEYS.items()}
_MCP_ELEMENTS: Final = frozenset({"rate-limit-by-key", "validate-azure-ad-token"})

CounterKey = Literal["subscription", "oid"]


def grant_fragment_id(grant_id: str) -> str:
    """Default policy fragment id for a grant canonical id (a valid APIM resource segment)."""
    return "ns-grant-" + hashlib.sha256(grant_id.encode("utf-8")).hexdigest()[:24]


def _bad(message: str, reason: str) -> InvalidSchemaError:
    return InvalidSchemaError(message, reason=reason)


@dataclass(frozen=True)
class CapIntent:
    """The desired cap: limits to render plus the limit fields the diff names."""

    target_kind: str
    limits: GrantLimits
    named: frozenset[str]


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _bad("token limits must be positive integers", "bad_limits")
    return value


def parse_cap_diff(diff: ProposedDiff) -> CapIntent:
    """Read the cap grammar (module docstring); pure, raises ``InvalidSchemaError``."""
    seen: set[str] = set()
    tests: dict[str, object] = {}
    values: dict[str, object] = {}
    named: set[str] = set()
    for op in diff.operations:
        if op.path == PLAN_DIGEST_PATH:
            continue
        if op.path in seen:
            raise _bad("a path appears twice in the cap diff", "duplicate_operation")
        seen.add(op.path)
        if op.path in (_TARGET_KIND, _COUNTER_KEY, _NAMESPACE):
            if op.op != "test":
                raise _bad("grant facts are test operations", "unsupported_operation")
            tests[op.path] = op.value
            continue
        field = _LIMIT_PATHS.get(op.path)
        if field is None:
            raise _bad("unsupported cap diff path", "unsupported_operation")
        named.add(field)
        if op.op == "remove":
            continue
        if op.op not in ("add", "replace"):
            raise _bad("unsupported cap diff operation", "unsupported_operation")
        values[field] = op.value

    kind = tests.get(_TARGET_KIND)
    if not isinstance(kind, str) or kind not in _TARGET_KINDS:
        raise _bad("the cap diff must test /target/kind", "grant_target_kind_required")
    if kind == "mcp_server":
        raise _bad("MCP grants are call-limited only; token limits refused", MCP_GRANT_TOKEN_LIMIT)
    counter = tests.get(_COUNTER_KEY)
    if counter not in COUNTER_KEYS:
        raise _bad("the cap diff must test /counter_key", "counter_key_required")
    namespace = tests.get(_NAMESPACE, DEFAULT_METRIC_NAMESPACE)
    if not isinstance(namespace, str):
        raise _bad("metric namespace must be a string", "bad_limits")

    tpm = values.get("tokens_per_minute")
    quota = values.get("token_quota")
    period = values.get("quota_period")
    apim_period: str | None = None
    if period is not None:
        if not isinstance(period, str) or period not in _PERIODS:
            raise _bad("quota_period has no APIM token-quota-period", "unsupported_quota_period")
        apim_period = _PERIODS[period]
    try:
        limits = GrantLimits(
            counter_key=cast(CounterKey, counter),
            tokens_per_minute=None if tpm is None else _positive_int(tpm),
            token_quota=None if quota is None else _positive_int(quota),
            token_quota_period=apim_period,
            metric_namespace=namespace,
        )
    except ValueError as exc:
        raise _bad(str(exc), "bad_limits") from None
    return CapIntent(target_kind=kind, limits=limits, named=frozenset(named))


def _parse_xml(text: str) -> ET.Element:
    """Parse a fragment read back from the gateway. DTDs are refused, so no entity expands."""
    if len(text) > MAX_FRAGMENT_CHARS or "<!" in text:
        raise _bad("the grant fragment is not a grant template", "grant_fragment_unrecognised")
    try:
        # Bounded, DTD-free text; expat resolves no external entities.
        return ET.fromstring(text)  # noqa: S314
    except ET.ParseError:
        raise _bad("the grant fragment is not XML", "grant_fragment_unrecognised") from None


def limit_attributes(xml: str) -> dict[str, str]:
    """The ``llm-token-limit`` cap attributes a fragment sets (``LIMIT_ATTRIBUTES`` only)."""
    root = _parse_xml(xml)
    found = [el for el in root.iter() if el.tag == "llm-token-limit"]
    if not found:
        if any(el.tag in _MCP_ELEMENTS for el in root.iter()):
            raise _bad("an MCP grant fragment carries no token limits", MCP_GRANT_TOKEN_LIMIT)
        raise _bad("the fragment has no llm-token-limit", "grant_fragment_unrecognised")
    if len(found) > 1:
        raise _bad("the fragment has several llm-token-limit", "grant_fragment_unrecognised")
    return {k: v for k, v in found[0].attrib.items() if k in LIMIT_ATTRIBUTES}


def _int_attr(attrs: Mapping[str, str], name: str) -> int | None:
    raw = attrs.get(name)
    if raw is None:
        return None
    if not raw.isdigit():
        raise _bad("a token limit attribute is not an integer", "grant_fragment_unrecognised")
    return int(raw)


def parse_grant_fragment(xml: str) -> GrantLimits:
    """The ``GrantLimits`` a live fragment renders from; refuses anything else."""
    attrs = limit_attributes(xml)
    root = _parse_xml(xml)
    limit = next(el for el in root.iter() if el.tag == "llm-token-limit")
    metric = next((el for el in root.iter() if el.tag == "llm-emit-token-metric"), None)
    counter = _COUNTER_BY_EXPR.get(limit.attrib.get("counter-key", ""))
    if counter is None or metric is None:
        raise _bad("the grant fragment is not a grant template", "grant_fragment_unrecognised")
    try:
        limits = GrantLimits(
            counter_key=cast(CounterKey, counter),
            tokens_per_minute=_int_attr(attrs, "tokens-per-minute"),
            token_quota=_int_attr(attrs, "token-quota"),
            token_quota_period=attrs.get("token-quota-period"),
            metric_namespace=metric.attrib.get("namespace", ""),
        )
    except ValueError:
        raise _bad("the grant fragment limits are invalid", "grant_fragment_unrecognised") from None
    if normalize_xml(render_grant_fragment(limits)) != normalize_xml(xml):
        # Foreign content (or a hand edit) in the fragment: never overwrite it.
        raise _bad("the grant fragment is not a grant template", "grant_fragment_unrecognised")
    return limits


@dataclass(frozen=True)
class AttributeChange:
    """One ``llm-token-limit`` attribute before and after (None = not set)."""

    attribute: str
    before: str | None
    after: str | None


def attribute_diff(before_xml: str, after_xml: str) -> list[AttributeChange]:
    """Changed cap attributes between two fragments, in ``LIMIT_ATTRIBUTES`` order."""
    before = limit_attributes(before_xml)
    after = limit_attributes(after_xml)
    return [
        AttributeChange(name, before.get(name), after.get(name))
        for name in LIMIT_ATTRIBUTES
        if before.get(name) != after.get(name)
    ]


def _live_fields(limits: GrantLimits) -> set[str]:
    fields: set[str] = set()
    if limits.tokens_per_minute is not None:
        fields.add("tokens_per_minute")
    if limits.token_quota is not None:
        fields.update({"token_quota", "quota_period"})
    return fields


class BudgetCapTranslator:
    """``IntentTranslator`` for target ``grant`` (``budget_cap_change``)."""

    def __init__(self, *, fragment_id: Callable[[str], str] = grant_fragment_id) -> None:
        self._fragment_id = fragment_id

    @property
    def entity_types(self) -> frozenset[str]:
        return frozenset({GRANT_ENTITY_TYPE})

    def fragment_path(self, gateway: GatewayRef, request: WriteRequest) -> str:
        """Relative ARM path of the grant's policy fragment on this gateway."""
        parts = request.target.canonical_id.split(":")
        if request.target.entity_type != GRANT_ENTITY_TYPE or len(parts) < 5:
            raise _bad("target is not a grant", "wrong_entity")
        if parts[3] != GRANT_ENTITY_TYPE:
            raise _bad("target is not a grant", "wrong_entity")
        if parts[0] != gateway.cloud.value:
            raise _bad("target cloud differs from connector", "cloud_mismatch")
        return "policyFragments/" + self._fragment_id(request.target.canonical_id)

    def specs(self, gateway: GatewayRef, request: WriteRequest) -> list[ResourceSpec]:
        path = self.fragment_path(gateway, request)
        intent = parse_cap_diff(request.proposed_diff)
        xml = render_grant_fragment(intent.limits)
        return [
            ResourceSpec(
                resource_type=ResourceType.POLICY_FRAGMENT,
                name=path,
                operation="upsert",
                payload=fragment_payload(xml),
            )
        ]

    async def _read(
        self, arm: ApimArm, gateway: GatewayRef, request: WriteRequest
    ) -> tuple[str, str]:
        """(ETag, policy text) of the grant fragment; refuses an unpublished grant."""
        resource = await arm.get(self.fragment_path(gateway, request))
        if resource is None:
            raise _bad("the grant is not published on this gateway", "grant_not_published")
        if not resource.etag:
            raise CapabilityUnavailableError(
                "grant_fragment_not_readable", "the grant fragment has no readable ETag"
            )
        value = resource.properties.get("value")
        if not isinstance(value, str):
            raise _bad("the grant fragment has no policy text", "grant_fragment_unrecognised")
        return resource.etag, value

    @staticmethod
    def _check_live(intent: CapIntent, xml: str) -> None:
        live = parse_grant_fragment(xml)
        if live.counter_key != intent.limits.counter_key:
            raise _bad("a cap change never moves the counter key", "counter_key_mismatch")
        if live.metric_namespace != intent.limits.metric_namespace:
            raise _bad("the metric namespace differs", "metric_namespace_mismatch")
        if not _live_fields(live) <= intent.named:
            raise _bad("the diff must name every live limit", "cap_diff_incomplete")

    async def current_version(
        self, arm: ApimArm, gateway: GatewayRef, request: WriteRequest
    ) -> str:
        """The fragment ETag; while it equals ``target_version`` the live fragment is checked."""
        intent = parse_cap_diff(request.proposed_diff)
        etag, xml = await self._read(arm, gateway, request)
        if etag == request.target_version:
            self._check_live(intent, xml)
        # Otherwise stale (the connector refuses it) or our own write (verify reads back).
        return etag

    async def preview(
        self, arm: ApimArm, gateway: GatewayRef, request: WriteRequest
    ) -> list[AttributeChange]:
        """Attribute diff of the live fragment against the one ``specs`` renders (reads only)."""
        intent = parse_cap_diff(request.proposed_diff)
        _, before = await self._read(arm, gateway, request)
        self._check_live(intent, before)
        return attribute_diff(before, render_grant_fragment(intent.limits))
