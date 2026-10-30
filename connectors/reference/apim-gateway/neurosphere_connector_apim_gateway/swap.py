"""``model_deployment_swap`` against an ``apim_backend`` target (PRP-34 item 3).

A model swap on the gateway is a change of ONE APIM backend document, written through the same
digest-bound plan, applier and ownership record as every other APIM change:

* a ``Single`` backend swaps its ``url`` atomically. APIM has no traffic split for one backend,
  so the executor's canary for it is ``verify_only`` (the probe says so; nothing pretends);
* a ``Pool`` backend shifts ``pool.services[i].weight``. The canary is a REAL weight shift: a
  member whose traffic share is below ``canary_percent`` (default 10) may be raised at most to
  that share by one intent (``invalid_schema`` reason ``canary_weight_exceeded``); a later
  intent promotes it. The worker's ``CanaryProbe`` reads the pool back and, when the gateway
  writes ``GatewayLogs``, waits for one log row naming the raised member (absence = failure).

Target: entity type ``apim_backend``; canonical id ``{cloud}:{customer}:apim:apim_backend:{id}``
where ``{id}`` is the backend name, optionally prefixed by the bound gateway id
(``gw-.../name``). ``target_version`` is the backend's ETag.

Diff grammar (besides the ``test /plan_digest`` that ``dry_run`` binds in):

* exactly one ``test /backend`` whose value is the backend ``properties`` as read when the
  intent was drafted (:func:`backend_swap_diff` builds it). The ARM PUT replaces the whole
  document, so the payload is the base with the change applied; the base must still EQUAL the
  live document when the plan is made (``stale_version`` reason ``backend_base_mismatch``), so a
  swap can never smuggle another property change past the reviewer;
* ``Single``: exactly one ``replace /url`` (an ``https`` URL);
* ``Pool``: one or more ``replace /pool/services/{i}/weight`` (integers 0..1000).

Verify reads the backend back and compares it with the proposed document (the connector's
generic read-back); rollback restores the prior document the applier captured at write time
(``If-Match`` on the ETag our write produced). Credentials in the base must be named-value
references (the planner refuses literals), so the diff never carries a secret.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, cast
from urllib.parse import urlsplit

from neurosphere_connector.write import WriteRequest
from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from neurosphere_contracts.actions.v1.target_ref import TargetRef
from neurosphere_core.errors import (
    CapabilityUnavailableError,
    InvalidSchemaError,
    StaleVersionError,
)
from neurosphere_core.gateway.models import GATEWAY_ID_PATTERN

from neurosphere_connector_apim_gateway.arm import ApimArm, ArmResource
from neurosphere_connector_apim_gateway.compare import payload_matches
from neurosphere_connector_apim_gateway.gateway import GatewayRef
from neurosphere_connector_apim_gateway.models import ResourceSpec, ResourceType
from neurosphere_connector_apim_gateway.translate import PLAN_DIGEST_PATH

__all__ = [
    "BACKEND_ENTITY_TYPE",
    "BASE_PATH",
    "DEFAULT_CANARY_PERCENT",
    "MAX_POOL_WEIGHT",
    "BackendSwap",
    "BackendSwapTranslator",
    "PoolShift",
    "backend_name_of",
    "backend_swap_diff",
    "backend_target",
    "member_name",
    "parse_backend_swap",
    "pool_weights",
]

BACKEND_ENTITY_TYPE: Final = "apim_backend"
BASE_PATH: Final = "/backend"
URL_PATH: Final = "/url"
DEFAULT_CANARY_PERCENT: Final = 10
MAX_POOL_WEIGHT: Final = 1000
_WEIGHT_PATH = re.compile(r"^/pool/services/(0|[1-9][0-9]{0,3})/weight$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_GATEWAY_ID = re.compile(GATEWAY_ID_PATTERN)

BackendKind = Literal["single", "pool"]


def _bad(detail: str, reason: str = "bad_backend_swap") -> InvalidSchemaError:
    return InvalidSchemaError(detail, reason=reason)


@dataclass(frozen=True)
class PoolShift:
    """One pool member whose weight the intent raises (the member the canary watches)."""

    index: int
    member: str
    weight_before: int | None
    weight_after: int


@dataclass(frozen=True)
class BackendSwap:
    """A parsed swap: the backend path, its kind, the base and the desired document."""

    path: str
    kind: BackendKind
    base: dict[str, Any]
    desired: dict[str, Any]
    raised: tuple[PoolShift, ...] = ()


# -- target ---------------------------------------------------------------------------------------


def backend_target(cloud: str, customer_id: str, backend: str) -> TargetRef:
    """``TargetRef`` of a backend swap (canonical ids are lowercase)."""
    return TargetRef(
        canonical_id=f"{cloud}:{customer_id}:apim:{BACKEND_ENTITY_TYPE}:{backend}",
        entity_type=BACKEND_ENTITY_TYPE,
    )


def backend_name_of(gateway: GatewayRef, target: TargetRef) -> str:
    """The backend name a target names on ``gateway``; refuses another cloud or gateway."""
    if target.entity_type != BACKEND_ENTITY_TYPE:
        raise _bad("not a backend target", reason="wrong_entity")
    cloud, _, rest = target.canonical_id.partition(":")
    if cloud != gateway.cloud.value:
        raise _bad("target cloud differs from connector", reason="cloud_mismatch")
    tail = rest.rsplit(":", 1)[-1]
    gateway_id, sep, name = tail.rpartition("/")
    if sep and gateway_id != gateway.gateway_id:
        reason = "wrong_entity" if _GATEWAY_ID.fullmatch(gateway_id) else "bad_path"
        raise _bad("target is not a backend of this gateway", reason=reason)
    if not _NAME.fullmatch(name):
        raise _bad("not a backend name", reason="bad_path")
    return name


def member_name(service: Mapping[str, Any]) -> str:
    """Backend name of a pool member (``id`` is ``/backends/{name}`` or a full ARM id)."""
    raw = service.get("id")
    if not isinstance(raw, str) or "/backends/" not in raw.lower():
        raise _bad("pool member has no backend id")
    return raw.rsplit("/", 1)[-1]


def _services(document: Mapping[str, Any]) -> list[dict[str, Any]]:
    pool = document.get("pool")
    services = pool.get("services") if isinstance(pool, Mapping) else None  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if not isinstance(services, list) or not services:
        raise _bad("a pool backend lists its members in pool.services")
    found: list[dict[str, Any]] = []
    for item in cast(list[object], services):
        if not isinstance(item, Mapping):
            raise _bad("pool members must be objects")
        found.append({str(k): v for k, v in cast(Mapping[Any, Any], item).items()})
    return found


def pool_weights(document: Mapping[str, Any]) -> dict[str, int | None]:
    """Member name -> weight as written in a pool document (None when unset)."""
    weights: dict[str, int | None] = {}
    for service in _services(document):
        weight = service.get("weight")
        weights[member_name(service)] = (
            weight if isinstance(weight, int) and not isinstance(weight, bool) else None
        )
    return weights


def _kind(base: Mapping[str, Any]) -> BackendKind:
    raw = base.get("type", "Single")
    if raw == "Pool":
        return "pool"
    if raw == "Single":
        return "single"
    raise _bad("backend type must be Single or Pool")


# -- parsing --------------------------------------------------------------------------------------


def _base(operations: Sequence[PatchOperation]) -> dict[str, Any]:
    found = [op for op in operations if op.path == BASE_PATH]
    if len(found) != 1 or found[0].op != "test" or not isinstance(found[0].value, Mapping):
        raise _bad("a backend swap carries exactly one test /backend with the base document")
    value = cast(Mapping[Any, Any], found[0].value)
    return {str(k): copy.deepcopy(v) for k, v in value.items()}


def _https(url: object) -> str:
    if not isinstance(url, str) or len(url) > 2000:
        raise _bad("the backend url must be a string")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise _bad("the backend url must be an absolute https URL", reason="backend_url_invalid")
    return url


def _weight(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_POOL_WEIGHT:
        raise _bad(f"pool weights are integers 0..{MAX_POOL_WEIGHT}")
    return value


def _effective(weights: Sequence[int | None]) -> list[int]:
    # An unset weight is an equal share (APIM distributes evenly when no weight is given).
    return [1 if w is None else w for w in weights]


def _share(weights: Sequence[int], index: int) -> float:
    total = sum(weights)
    return 0.0 if total == 0 else 100.0 * weights[index] / total


def parse_backend_swap(
    gateway: GatewayRef,
    request: WriteRequest,
    *,
    canary_percent: int | None = DEFAULT_CANARY_PERCENT,
) -> BackendSwap:
    """Validate the diff and compute the desired backend document. Pure, no I/O."""
    name = backend_name_of(gateway, request.target)
    operations = [op for op in request.proposed_diff.operations if op.path != PLAN_DIGEST_PATH]
    base = _base(operations)
    changes = [op for op in operations if op.path != BASE_PATH]
    if not changes:
        raise _bad("the diff changes nothing", reason="empty_plan")
    if any(op.op != "replace" for op in changes):
        raise _bad("a backend swap only replaces", reason="unsupported_operation")
    kind = _kind(base)
    desired = copy.deepcopy(base)
    path = f"backends/{name}"
    if kind == "single":
        if len(changes) != 1 or changes[0].path != URL_PATH:
            raise _bad(
                "a single backend swap replaces /url exactly once", reason="unsupported_operation"
            )
        desired["url"] = _https(changes[0].value)
        return BackendSwap(path=path, kind=kind, base=base, desired=desired)
    services = _services(desired)
    before = [s.get("weight") for s in services]
    seen: set[int] = set()
    for op in changes:
        match = _WEIGHT_PATH.fullmatch(op.path)
        if match is None:
            raise _bad(
                "a pool swap replaces /pool/services/{i}/weight only",
                reason="unsupported_operation",
            )
        index = int(match.group(1))
        if index >= len(services) or index in seen:
            raise _bad("pool member index is out of range or repeated")
        seen.add(index)
        services[index]["weight"] = _weight(op.value)
    desired["pool"] = {**cast(Mapping[str, Any], desired["pool"]), "services": services}
    typed_before: list[int | None] = [
        w if isinstance(w, int) and not isinstance(w, bool) else None for w in before
    ]
    after = _effective([s.get("weight") for s in services])
    prior = _effective(typed_before)
    raised: list[PoolShift] = []
    # Every member whose SHARE grows counts, also one whose own weight is untouched (lowering
    # the other members' weights shifts traffic too): no promotion past the canary by proxy.
    for index in range(len(services)):
        share_before, share_after = _share(prior, index), _share(after, index)
        if share_after <= share_before:
            continue
        if (
            canary_percent is not None
            and share_before < canary_percent
            and share_after > canary_percent
        ):
            raise _bad(
                f"a member below {canary_percent}% of the pool is raised to at most "
                f"{canary_percent}% first (canary); promote it with a later intent",
                reason="canary_weight_exceeded",
            )
        raised.append(
            PoolShift(
                index=index,
                member=member_name(services[index]),
                weight_before=typed_before[index],
                weight_after=after[index],
            )
        )
    return BackendSwap(path=path, kind=kind, base=base, desired=desired, raised=tuple(raised))


# -- translator -----------------------------------------------------------------------------------


class BackendSwapTranslator:
    """``IntentTranslator`` for ``apim_backend``: one backend document, ETag-versioned."""

    def __init__(self, *, canary_percent: int | None = DEFAULT_CANARY_PERCENT) -> None:
        if canary_percent is not None and not 1 <= canary_percent <= 100:
            raise ValueError("canary_percent must be 1..100")
        self.canary_percent = canary_percent

    @property
    def entity_types(self) -> frozenset[str]:
        return frozenset({BACKEND_ENTITY_TYPE})

    def parse(self, gateway: GatewayRef, request: WriteRequest) -> BackendSwap:
        return parse_backend_swap(gateway, request, canary_percent=self.canary_percent)

    async def current_version(
        self, arm: ApimArm, gateway: GatewayRef, request: WriteRequest
    ) -> str:
        swap = self.parse(gateway, request)
        current = await arm.get(swap.path)
        if current is None:
            raise InvalidSchemaError("the backend does not exist", reason="target_not_found")
        if not current.etag:
            raise CapabilityUnavailableError(
                "backend_not_readable", "the backend has no readable ETag"
            )
        if current.etag == request.target_version:
            _check_base(swap, current)
        return current.etag

    def specs(self, gateway: GatewayRef, request: WriteRequest) -> list[ResourceSpec]:
        swap = self.parse(gateway, request)
        return [
            ResourceSpec(
                resource_type=ResourceType.BACKEND,
                name=swap.path,
                operation="upsert",
                payload=swap.desired,
            )
        ]


def _check_base(swap: BackendSwap, live: ArmResource) -> None:
    """The reviewed base equals the live document (both ways), so only the swap changes."""
    if _kind(live.properties) != swap.kind:
        raise StaleVersionError("the backend type changed", reason="backend_base_mismatch")
    if not (
        payload_matches(ResourceType.BACKEND, swap.base, live.properties)
        and payload_matches(ResourceType.BACKEND, live.properties, swap.base)
    ):
        raise StaleVersionError(
            "the reviewed backend document differs from the live one",
            reason="backend_base_mismatch",
        )


# -- drafting helper ------------------------------------------------------------------------------


def backend_swap_diff(
    base: Mapping[str, Any],
    *,
    url: str | None = None,
    weights: Mapping[str, int] | None = None,
) -> ProposedDiff:
    """The diff a maker confirms: the base document plus the URL or the member weights.

    ``base`` is the backend ``properties`` as read (``ArmResource.properties``); ``weights``
    maps member backend names to their new weight.
    """
    if (url is None) == (weights is None):
        raise ValueError("give either url (single backend) or weights (pool)")
    operations: list[PatchOperation] = [
        PatchOperation(op="test", path=BASE_PATH, value=copy.deepcopy(dict(base)))
    ]
    if url is not None:
        operations.append(PatchOperation(op="replace", path=URL_PATH, value=url))
    else:
        assert weights is not None
        names = [member_name(s) for s in _services(base)]
        unknown = set(weights) - set(names)
        if unknown:
            raise ValueError("not pool members: " + ", ".join(sorted(unknown)))
        operations.extend(
            PatchOperation(op="replace", path=f"/pool/services/{index}/weight", value=weights[name])
            for index, name in enumerate(names)
            if name in weights
        )
    return ProposedDiff(format="json_patch", operations=operations)
