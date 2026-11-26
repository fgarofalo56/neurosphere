"""Deterministic ids for the policy engine (PRP-105 item 1).

* :func:`dedup_key` - ``sha256:`` + hex digest of (policy id, rule id, subject canonical id,
  evidence class), so one breach of one rule by one subject is one violation however often the
  worker sees it.
* :func:`violation_id_for` - the violation id for the ``generation``-th violation of a dedup key
  (a resolved violation that recurs is a new record, generation + 1). Concurrent writers derive the
  same id, so a race is a create conflict, never a duplicate.
* Canonical ids in the catalog grammar ``<cloud>:<customer>:neurosphere:<type>:<id>`` for a
  violation, an exception, the projected catalog ``policy`` entity and the ``governance_policy``
  action target.
* :func:`binding_id_for` - the deterministic enforcement binding id (an ``admin_config`` id).
* :func:`governance_policy_chain_id` - the customer-level audit chain
  ``<customer>.governance-policy``.

Every helper refuses a segment that does not fit the grammar with ``invalid_schema``
(``invalid_policy_id``); nothing here is built from free text.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Final

from neurosphere_core.errors import InvalidSchemaError, ValidationIssue

__all__ = [
    "GOVERNANCE_POLICY_CHAIN_SUFFIX",
    "GOVERNANCE_POLICY_ENTITY_TYPE",
    "NEUROSPHERE_SOURCE",
    "POLICY_ENTITY_TYPE",
    "POLICY_EXCEPTION_ENTITY_TYPE",
    "POLICY_VIOLATION_ENTITY_TYPE",
    "binding_id_for",
    "dedup_key",
    "evaluation_status_id",
    "exception_canonical_id",
    "governance_policy_canonical_id",
    "governance_policy_chain_id",
    "policy_document_id",
    "policy_entity_canonical_id",
    "violation_canonical_id",
    "violation_id_for",
]

NEUROSPHERE_SOURCE: Final = "neurosphere"
POLICY_VIOLATION_ENTITY_TYPE: Final = "policy_violation"
POLICY_EXCEPTION_ENTITY_TYPE: Final = "policy_exception"
#: The catalog ``Policy`` entity each published policy is projected to.
POLICY_ENTITY_TYPE: Final = "policy"
#: The action-target entity type of publish and retire intents (PRP-99 convention).
GOVERNANCE_POLICY_ENTITY_TYPE: Final = "governance_policy"
GOVERNANCE_POLICY_CHAIN_SUFFIX: Final = "governance-policy"

_CLOUDS: Final = frozenset({"commercial", "government"})
_CUSTOMER: Final = re.compile(r"^[a-z0-9._-]{1,128}$")
_CHAIN_CUSTOMER: Final = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_CHAIN: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SLUG: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ID_SEGMENT: Final = re.compile(r"^[a-z0-9._/=-]{1,256}$")
_CANONICAL: Final = re.compile(
    r"^(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$"
)
_EVIDENCE_CLASS: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DEDUP_KEY: Final = re.compile(r"^sha256:[a-f0-9]{64}$")
#: Fixed namespace for the uuid5 ids below (never change: ids are persisted).
_NAMESPACE: Final = uuid.UUID("5d0c4f8e-2b1a-4e57-9a63-7c1f0e2d9b41")


def _invalid(pointer: str, detail: str) -> InvalidSchemaError:
    return InvalidSchemaError(
        detail, errors=[ValidationIssue(pointer, detail)], reason="invalid_policy_id"
    )


def _check(value: str, pattern: re.Pattern[str], pointer: str, detail: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise _invalid(pointer, detail)
    return value


def _check_cloud(cloud: str) -> str:
    if cloud not in _CLOUDS:
        raise _invalid("/cloud", "cloud must be commercial or government")
    return cloud


def _canonical(cloud: str, customer_id: str, entity_type: str, entity_id: str) -> str:
    _check_cloud(cloud)
    _check(customer_id, _CUSTOMER, "/customer_id", "not a customer id")
    _check(entity_id, _ID_SEGMENT, "/id", "not a canonical id segment")
    return f"{cloud}:{customer_id}:{NEUROSPHERE_SOURCE}:{entity_type}:{entity_id}"


def dedup_key(policy_id: str, rule_id: str, subject_canonical_id: str, evidence_class: str) -> str:
    """``sha256:<hex>`` of the four parts (unambiguous JSON encoding, not concatenation)."""
    _check(policy_id, _SLUG, "/policy_id", "not a policy id")
    _check(rule_id, _SLUG, "/rule_id", "not a rule id")
    _check(subject_canonical_id, _CANONICAL, "/subject", "not a canonical id")
    _check(evidence_class, _EVIDENCE_CLASS, "/evidence_class", "not an evidence class")
    material = json.dumps(
        [policy_id, rule_id, subject_canonical_id, evidence_class], separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def violation_id_for(dedup: str, generation: int) -> str:
    """Deterministic violation id (uuid5) of the ``generation``-th violation of ``dedup``."""
    _check(dedup, _DEDUP_KEY, "/dedup_key", "not a dedup key")
    if generation < 1:
        raise _invalid("/generation", "generation starts at 1")
    return str(uuid.uuid5(_NAMESPACE, f"violation|{dedup}|{generation}"))


def evaluation_status_id(run_id: str) -> str:
    """Cosmos ``id`` of a run-status document (``evaluation_status:<run_id>``)."""
    return "evaluation_status:" + str(uuid.UUID(run_id))


def policy_document_id(policy_id: str, version: int) -> str:
    """Cosmos ``id`` of one policy version (``<policy_id>@<version>``)."""
    _check(policy_id, _SLUG, "/policy_id", "not a policy id")
    if version < 1:
        raise _invalid("/policy_version", "versions start at 1")
    return f"{policy_id}@{version}"


def binding_id_for(customer_id: str, policy_id: str, point: str, target: str | None) -> str:
    """Deterministic binding id (a slug): ``b-`` + 32 hex of (customer, policy, point, target)."""
    _check(customer_id, _CUSTOMER, "/customer_id", "not a customer id")
    _check(policy_id, _SLUG, "/policy_id", "not a policy id")
    _check(point, _EVIDENCE_CLASS, "/point", "not an enforcement point")
    if target is not None:
        _check(target, _CANONICAL, "/target", "not a canonical id")
    material = json.dumps([customer_id, policy_id, point, target], separators=(",", ":"))
    return "b-" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


def violation_canonical_id(cloud: str, customer_id: str, violation_id: str) -> str:
    """``<cloud>:<customer>:neurosphere:policy_violation:<violation_id>`` (HITL ``subject_ref``)."""
    return _canonical(cloud, customer_id, POLICY_VIOLATION_ENTITY_TYPE, violation_id)


def exception_canonical_id(cloud: str, customer_id: str, exception_id: str) -> str:
    """``<cloud>:<customer>:neurosphere:policy_exception:<exception_id>``."""
    return _canonical(cloud, customer_id, POLICY_EXCEPTION_ENTITY_TYPE, exception_id)


def policy_entity_canonical_id(cloud: str, customer_id: str, policy_id: str) -> str:
    """``<cloud>:<customer>:neurosphere:policy:<policy_id>`` (the projected catalog entity)."""
    _check(policy_id, _SLUG, "/policy_id", "not a policy id")
    return _canonical(cloud, customer_id, POLICY_ENTITY_TYPE, policy_id)


def governance_policy_canonical_id(cloud: str, customer_id: str, policy_id: str) -> str:
    """``<cloud>:<customer>:neurosphere:governance_policy:<policy_id>`` (action target)."""
    _check(policy_id, _SLUG, "/policy_id", "not a policy id")
    return _canonical(cloud, customer_id, GOVERNANCE_POLICY_ENTITY_TYPE, policy_id)


def governance_policy_chain_id(customer_id: str) -> str:
    """``<customer>.governance-policy``; ``invalid_schema`` ``invalid_chain_id`` if unencodable."""
    chain = f"{customer_id}.{GOVERNANCE_POLICY_CHAIN_SUFFIX}"
    if (
        not isinstance(customer_id, str)
        or not _CHAIN_CUSTOMER.fullmatch(customer_id)
        or not _CHAIN.fullmatch(chain)
    ):
        raise InvalidSchemaError(
            "customer id cannot name an audit chain", reason="invalid_chain_id"
        )
    return chain
