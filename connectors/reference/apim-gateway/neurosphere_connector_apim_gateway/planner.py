"""Build a ``PublishPlan`` from desired resource specs and the gateway's current state.

Order is fixed by ``DEPENDENCY_ORDER``: upserts in that order (then by name), deletes after all
upserts in the reverse order. Deletes after upserts gives fail-closed ordering for free: a deny
policy written as an upsert lands before any resource is removed (MOSAIC ADR-0017).

Planning only READS (one GET per resource). ``expected`` is ``create`` when the resource is
absent and ``found`` when it exists; ``changes`` is False for a found resource whose current
properties already contain the payload, so a re-run of the same publication writes nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from neurosphere_core.errors import InvalidSchemaError, StaleVersionError

from neurosphere_connector_apim_gateway.arm import ApimArm, check_path
from neurosphere_connector_apim_gateway.compare import payload_matches
from neurosphere_connector_apim_gateway.digest import payload_digest, plan_digest
from neurosphere_connector_apim_gateway.models import (
    DEPENDENCY_ORDER,
    PlanStep,
    PublishPlan,
    ResourceSpec,
    ResourceType,
)

__all__ = [
    "build_plan",
    "check_plan_integrity",
    "order_specs",
    "validate_specs",
]

_RANK: Final = {t: i for i, t in enumerate(DEPENDENCY_ORDER)}
_REF = re.compile(r"^\{\{([A-Za-z0-9._-]{1,256})\}\}$")
_SECRET_FIELDS: Final = frozenset({"primaryKey", "secondaryKey"})


def _sort_key(spec: ResourceSpec) -> tuple[int, int, str]:
    rank = _RANK[spec.resource_type]
    if spec.operation == "upsert":
        return (0, rank, spec.name)
    return (1, len(DEPENDENCY_ORDER) - rank, spec.name)


def order_specs(specs: Iterable[ResourceSpec]) -> list[ResourceSpec]:
    """Canonical dependency order (deterministic for any input order)."""
    return sorted(specs, key=_sort_key)


def _refs(values: Any) -> list[str] | None:
    """Named-value names when every credential value is a ``{{name}}`` reference, else None."""
    if not isinstance(values, Mapping):
        return None
    names: list[str] = []
    for raw in values.values():  # pyright: ignore[reportUnknownVariableType]
        items: list[Any] = list(raw) if isinstance(raw, list) else [raw]  # pyright: ignore[reportUnknownArgumentType]
        for item in items:
            match = _REF.fullmatch(item) if isinstance(item, str) else None
            if match is None:
                return None
            names.append(match.group(1))
    return names


def _backend_key_refs(payload: Mapping[str, Any]) -> set[str]:
    """Named values a key-authenticated backend references; refuses literal credentials."""
    creds = payload.get("credentials")
    if creds is None:
        return set()
    if not isinstance(creds, Mapping):
        raise InvalidSchemaError("backend credentials must be an object", reason="bad_payload")
    found: set[str] = set()
    for part in ("header", "query"):
        if part in creds:
            names = _refs(creds[part])
            if names is None:
                raise InvalidSchemaError(
                    "backend credentials must reference named values ({{name}}), never literals",
                    reason="literal_credential",
                )
            found.update(names)
    auth = creds.get("authorization")
    if auth is not None:
        param = auth.get("parameter") if isinstance(auth, Mapping) else None
        match = _REF.fullmatch(param) if isinstance(param, str) else None
        if match is None:
            raise InvalidSchemaError(
                "backend authorization must reference a named value", reason="literal_credential"
            )
        found.add(match.group(1))
    return found


def _check_named_value(spec: ResourceSpec, payload: Mapping[str, Any]) -> set[str]:
    vault = payload.get("keyVault")
    if (
        payload.get("secret") is not True
        or not isinstance(vault, Mapping)
        or not isinstance(vault.get("secretIdentifier"), str)
    ):
        raise InvalidSchemaError(
            "named values must be secret Key Vault references",
            reason="named_value_requires_key_vault",
        )
    name = spec.name.split("/", 1)[1]
    display = payload.get("displayName")
    return {name, display} if isinstance(display, str) else {name}


def validate_specs(specs: Sequence[ResourceSpec]) -> None:
    """Shape and safety rules every plan must satisfy before any read is issued."""
    seen: set[str] = set()
    key_refs: set[str] = set()
    named: list[tuple[ResourceSpec, set[str]]] = []
    for spec in specs:
        rtype = check_path(spec.name)
        if rtype is not spec.resource_type:
            raise InvalidSchemaError("resource type does not match its path", reason="bad_path")
        if spec.name in seen:
            raise InvalidSchemaError(
                "a resource appears twice in one plan", reason="duplicate_resource"
            )
        seen.add(spec.name)
        if spec.operation == "delete":
            if spec.payload is not None:
                raise InvalidSchemaError("a delete carries no payload", reason="bad_payload")
            continue
        payload = spec.payload
        if payload is None:
            raise InvalidSchemaError("an upsert needs a payload", reason="bad_payload")
        if any(k in payload for k in _SECRET_FIELDS):
            raise InvalidSchemaError("secret material is never written", reason="secret_in_payload")
        if rtype is ResourceType.NAMED_VALUE:
            if "value" in payload:
                raise InvalidSchemaError(
                    "named-value values are never written", reason="secret_in_payload"
                )
            named.append((spec, _check_named_value(spec, payload)))
        elif rtype is ResourceType.BACKEND:
            key_refs |= _backend_key_refs(payload)
    for _spec, names in named:
        # A named value exists only to hold a key-authenticated backend's credential.
        if not names & key_refs:
            raise InvalidSchemaError(
                "a named value is planned only for a key-authenticated backend in the same plan",
                reason="named_value_without_key_backend",
            )


async def build_plan(
    arm: ApimArm,
    *,
    gateway_id: str,
    target: str,
    target_version: str,
    specs: Sequence[ResourceSpec],
) -> PublishPlan:
    """Order, validate and read; returns an immutable plan with its digest."""
    validate_specs(specs)
    steps: list[PlanStep] = []
    for spec in order_specs(specs):
        current = await arm.get(spec.name)
        if spec.operation == "delete":
            if current is None:
                continue  # already absent: nothing to undo or remove
            steps.append(
                PlanStep(
                    index=len(steps),
                    resource_type=spec.resource_type,
                    name=spec.name,
                    operation="delete",
                    expected="found",
                    changes=True,
                )
            )
            continue
        payload = spec.payload or {}
        steps.append(
            PlanStep(
                index=len(steps),
                resource_type=spec.resource_type,
                name=spec.name,
                operation="upsert",
                expected="create" if current is None else "found",
                changes=current is None
                or not payload_matches(spec.resource_type, payload, current.properties),
                payload_digest=payload_digest(payload),
            )
        )
    digest = plan_digest(
        gateway_id=gateway_id, target=target, target_version=target_version, steps=steps
    )
    return PublishPlan(
        gateway_id=gateway_id,
        target=target,
        target_version=target_version,
        steps=tuple(steps),
        digest=digest,
    )


def _mismatch() -> StaleVersionError:
    return StaleVersionError(
        "the plan no longer matches the reviewed plan", reason="plan_digest_mismatch"
    )


def check_plan_integrity(
    plan: PublishPlan, specs: Sequence[ResourceSpec]
) -> dict[int, ResourceSpec]:
    """Refuse a plan whose order, digest or payloads differ; returns step index -> spec."""
    recomputed = plan_digest(
        gateway_id=plan.gateway_id,
        target=plan.target,
        target_version=plan.target_version,
        steps=plan.steps,
    )
    if recomputed != plan.digest:
        raise _mismatch()
    if [s.index for s in plan.steps] != list(range(len(plan.steps))):
        raise _mismatch()
    keys = [
        _sort_key(ResourceSpec(resource_type=s.resource_type, name=s.name, operation=s.operation))
        for s in plan.steps
    ]
    if keys != sorted(keys):
        raise _mismatch()
    by_name = {s.name: s for s in specs}
    bound: dict[int, ResourceSpec] = {}
    for step in plan.steps:
        spec = by_name.get(step.name)
        if (
            spec is None
            or spec.operation != step.operation
            or spec.resource_type is not step.resource_type
        ):
            raise _mismatch()
        if step.operation == "upsert" and payload_digest(spec.payload or {}) != step.payload_digest:
            raise _mismatch()
        bound[step.index] = spec
    return bound
