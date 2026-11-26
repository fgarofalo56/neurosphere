"""Policy document validation (PRP-105 item 1, acceptance criterion 1).

:func:`validate_draft` is the gate every new or replaced draft passes before anything is stored;
:func:`validate_policy` re-validates any stored version (draft, published or retired). Both
check, in order:

* the document is an object and ``rules`` is a list of 1 to :data:`MAX_RULES` objects;
* every rule ``kind`` is in the closed list :data:`~.models.RULE_KINDS` (``unknown_rule_kind``);
* every rule's ``params`` validates against THAT kind's parameter model
  (:data:`~.models.PARAMS_MODEL_BY_KIND`), the ``if/then`` pin Pydantic ignores (ADR-0004);
* no list inside ``params`` or ``applies_to`` has more than :data:`MAX_LIST_ITEMS` items
  (``list_too_long``), and rule ids are unique (``duplicate_rule_id``);
* the whole document validates as the PRP-99 ``PolicyDefinition`` (``extra="forbid"`` at every
  level, so an ``expression``, ``query`` or ``template`` field is refused, never ignored);
* every canonical id in the document (domain, ``applies_to.entity_ids``, deployment ids) and the
  author belong to the document's cloud and customer (``cross_cloud`` / ``cross_customer``);
* ``published`` carries ``published_at``, ``published_intent_id`` and ``published_audit_id``
  (the schema's ``if/then``), and a draft carries none of them;
* ``content_sha256`` equals :func:`rules_digest` of the rules (``content_digest_mismatch``), or
  is stamped by the server when ``stamp_digest=True``.

Every failure raises :class:`PolicyValidationError` (``invalid_schema``, HTTP 422) with RFC 6901
pointers and value-free messages; the caller stores nothing. No code path here compiles,
evaluates or templates rule text: a rule is data checked against a closed set of models.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Final

from pydantic import BaseModel, ValidationError

from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from neurosphere_core.governance.policy.models import (
    PARAMS_MODEL_BY_KIND,
    RULE_KINDS,
    PolicyDefinition,
    PolicyRule,
)

__all__ = [
    "CONTENT_DIGEST_MISMATCH",
    "CROSS_CLOUD",
    "CROSS_CUSTOMER",
    "DRAFT_HAS_PUBLISH_EVIDENCE",
    "DUPLICATE_RULE_ID",
    "INVALID_POLICY",
    "LIST_TOO_LONG",
    "MAX_LIST_ITEMS",
    "MAX_RULES",
    "NOT_A_DRAFT",
    "PUBLISH_EVIDENCE_MISSING",
    "TOO_MANY_RULES",
    "UNKNOWN_RULE_KIND",
    "PolicyValidationError",
    "rules_digest",
    "validate_draft",
    "validate_policy",
]

#: At most this many rules. The PRP text says 50; the PRP-99 contract caps ``rules`` at 32 and the
#: contract wins, so the effective bound is the contract's.
MAX_RULES: Final = 32
#: At most this many items in any one list inside a rule's ``params`` or ``applies_to``.
MAX_LIST_ITEMS: Final = 200

INVALID_POLICY: Final = "invalid_policy"
UNKNOWN_RULE_KIND: Final = "unknown_rule_kind"
TOO_MANY_RULES: Final = "too_many_rules"
LIST_TOO_LONG: Final = "list_too_long"
DUPLICATE_RULE_ID: Final = "duplicate_rule_id"
CROSS_CUSTOMER: Final = "cross_customer"
CROSS_CLOUD: Final = "cross_cloud"
PUBLISH_EVIDENCE_MISSING: Final = "publish_evidence_missing"
DRAFT_HAS_PUBLISH_EVIDENCE: Final = "draft_has_publish_evidence"
NOT_A_DRAFT: Final = "not_a_draft"
CONTENT_DIGEST_MISMATCH: Final = "content_digest_mismatch"

_PUBLISH_FIELDS: Final = ("published_at", "published_intent_id", "published_audit_id")
_CANONICAL: Final = re.compile(
    r"^(commercial|government):([a-z0-9._-]+):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+$"
)
#: Placeholder digest used only so the contract model accepts a draft before it is stamped.
_UNSTAMPED: Final = "sha256:" + "0" * 64


class PolicyValidationError(InvalidSchemaError):
    """A policy document failed validation: ``invalid_schema`` (422); nothing was stored."""

    def __init__(self, reason: str, issues: Sequence[ValidationIssue]) -> None:
        super().__init__("policy document is invalid", errors=list(issues), reason=reason)


def _refuse(reason: str, pointer: str, detail: str) -> PolicyValidationError:
    return PolicyValidationError(reason, [ValidationIssue(pointer, detail)])


def _from_pydantic(exc: ValidationError, prefix: str) -> PolicyValidationError:
    issues = [
        ValidationIssue(prefix + "".join(f"/{part}" for part in err["loc"]), str(err["type"]))
        for err in exc.errors(include_input=False, include_url=False)
    ]
    return PolicyValidationError(INVALID_POLICY, issues)


def _raw(document: Mapping[str, Any] | BaseModel) -> dict[str, Any]:
    if isinstance(document, BaseModel):
        # exclude_unset keeps what the author set, so a defaulted params object is not dumped
        # with another kind's defaults (the generated union cannot tell them apart).
        return document.model_dump(mode="json", exclude_unset=True)
    if not isinstance(document, Mapping):
        raise _refuse(INVALID_POLICY, "", "policy document must be an object")
    return dict(document)


def _walk(node: Any, pointer: str) -> Iterator[tuple[str, Any]]:
    yield pointer, node
    if isinstance(node, Mapping):
        for key, value in node.items():
            yield from _walk(value, f"{pointer}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{pointer}/{index}")


def _check_list_bounds(node: Any, pointer: str) -> None:
    for where, value in _walk(node, pointer):
        if isinstance(value, list) and len(value) > MAX_LIST_ITEMS:
            raise _refuse(LIST_TOO_LONG, where, f"at most {MAX_LIST_ITEMS} items")


def _validated_rule(raw: Any, index: int) -> dict[str, Any]:
    pointer = f"/rules/{index}"
    if not isinstance(raw, Mapping):
        raise _refuse(INVALID_POLICY, pointer, "rule must be an object")
    rule = dict(raw)
    kind = rule.get("kind")
    if not isinstance(kind, str) or kind not in RULE_KINDS:
        raise _refuse(UNKNOWN_RULE_KIND, f"{pointer}/kind", "rule kind is not in the closed list")
    _check_list_bounds(rule.get("applies_to"), f"{pointer}/applies_to")
    params = rule.get("params")
    if not isinstance(params, Mapping):
        raise _refuse(INVALID_POLICY, f"{pointer}/params", "params must be an object")
    _check_list_bounds(params, f"{pointer}/params")
    try:
        rule["params"] = PARAMS_MODEL_BY_KIND[kind].model_validate(dict(params))
    except ValidationError as exc:
        raise _from_pydantic(exc, f"{pointer}/params") from None
    return rule


def _check_scope_of_ids(policy: PolicyDefinition) -> None:
    cloud, customer = policy.cloud.root, policy.customer_id.root
    document = policy.model_dump(mode="json")
    for pointer, value in _walk(document, ""):
        if not isinstance(value, str):
            continue
        match = _CANONICAL.fullmatch(value)
        if match is None:
            continue
        if match.group(2) != customer:
            raise _refuse(CROSS_CUSTOMER, pointer, "id belongs to another customer")
        if match.group(1) != cloud:
            raise _refuse(CROSS_CLOUD, pointer, "id belongs to another cloud")
    author = policy.created_by.root.split(":")
    if len(author) < 2 or author[1] != customer:
        raise _refuse(CROSS_CUSTOMER, "/created_by", "principal of another customer")
    if author[0] != cloud:
        raise _refuse(CROSS_CLOUD, "/created_by", "principal of another cloud")


def rules_digest(rules: Sequence[PolicyRule]) -> str:
    """``sha256:<hex>`` of the canonical JSON of ``rules`` (sorted keys, defaults included)."""
    canonical = json.dumps(
        [rule.model_dump(mode="json") for rule in rules],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_policy(
    document: Mapping[str, Any] | BaseModel, *, stamp_digest: bool = False
) -> PolicyDefinition:
    """Validate one policy version (any status); see the module docstring for the rules.

    ``stamp_digest=True`` sets ``content_sha256`` from the rules (the server owns that field);
    otherwise a stored digest that does not match the rules is ``content_digest_mismatch``.
    """
    raw = _raw(document)
    rules = raw.get("rules")
    if not isinstance(rules, list) or not rules:
        raise _refuse(INVALID_POLICY, "/rules", "rules must be a non-empty list")
    if len(rules) > MAX_RULES:
        raise _refuse(TOO_MANY_RULES, "/rules", f"at most {MAX_RULES} rules")
    raw["rules"] = [_validated_rule(rule, index) for index, rule in enumerate(rules)]
    seen: set[str] = set()
    for index, rule in enumerate(raw["rules"]):
        rule_id = rule.get("rule_id")
        if isinstance(rule_id, str):
            if rule_id in seen:
                raise _refuse(DUPLICATE_RULE_ID, f"/rules/{index}/rule_id", "rule ids are unique")
            seen.add(rule_id)
    if stamp_digest:
        raw["content_sha256"] = _UNSTAMPED
    try:
        policy = PolicyDefinition.model_validate(raw)
    except ValidationError as exc:
        raise _from_pydantic(exc, "") from None
    _check_scope_of_ids(policy)
    if policy.status == "published":
        for field in _PUBLISH_FIELDS:
            if getattr(policy, field) is None:
                raise _refuse(PUBLISH_EVIDENCE_MISSING, f"/{field}", "published needs evidence")
    digest = rules_digest(policy.rules)
    if stamp_digest:
        return policy.model_copy(update={"content_sha256": digest})
    if policy.content_sha256 != digest:
        raise _refuse(CONTENT_DIGEST_MISMATCH, "/content_sha256", "digest does not match rules")
    return policy


def validate_draft(
    document: Mapping[str, Any] | BaseModel, *, stamp_digest: bool = True
) -> PolicyDefinition:
    """Validate a draft before it is created or replaced; ``content_sha256`` is server-stamped."""
    raw = _raw(document)
    if raw.get("status") != "draft":
        raise _refuse(NOT_A_DRAFT, "/status", "only a draft can be created or replaced")
    for field in _PUBLISH_FIELDS:
        if raw.get(field) is not None:
            raise _refuse(DRAFT_HAS_PUBLISH_EVIDENCE, f"/{field}", "a draft is not published")
    return validate_policy(raw, stamp_digest=stamp_digest)
