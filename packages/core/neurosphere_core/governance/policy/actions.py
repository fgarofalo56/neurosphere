"""Action-intent diff grammars of the policy engine (PRP-105 item 3, clarification 3).

Publishing, retiring and changing an enforcement mode are action-executor intents, never direct
writes. This module owns the exact RFC 6902 shape of each intent's ``proposed_diff`` and its
strict inverse, so the API that drafts the intent (item 6) and PRP-108's platform-control handler
that executes it agree byte for byte:

* ``governance_policy_publish`` - target ``<cloud>:<customer>:neurosphere:governance_policy:
  <policy_id>`` (entity type ``governance_policy``), target version ``v<policy_version>``::

      [{"op": "test", "path": "/policy_version", "value": <int>},
       {"op": "test", "path": "/policy_digest", "value": "sha256:<hex>"},
       {"op": "replace", "path": "/status", "value": "published" | "retired"}]

  ``/policy_digest`` is :func:`policy_digest` of the exact version confirmed, so the executor
  refuses a version that changed after the maker confirmed it.
* ``enforcement_mode_change`` - target ``<cloud>:<customer>:neurosphere:enforcement_binding:
  <binding_id>`` (entity type ``enforcement_binding``), target version ``v<admin version>``::

      [{"op": "test", "path": "/mode", "value": <current>},
       {"op": "replace", "path": "/mode", "value": <new>}]

  This is the ONLY grammar that can carry ``enforce`` (GD-7); PRP-108 applies it through
  :meth:`~.store.BindingStore.set_mode`.

Parsers refuse every other grammar (extra, missing or repeated operations, other paths or ops,
wrong value types) with ``invalid_schema``; every diff built or parsed here also passes the
executor's :func:`~neurosphere_core.actions.hashing.validate_proposed_diff`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, cast, get_args

from neurosphere_contracts.actions.v1.action_intent import PatchOperation, ProposedDiff
from pydantic import ValidationError

from neurosphere_core.actions.hashing import validate_proposed_diff
from neurosphere_core.audit.canonical import sha256_digest
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from neurosphere_core.governance.policy.ids import (
    GOVERNANCE_POLICY_ENTITY_TYPE,
    NEUROSPHERE_SOURCE,
    governance_policy_canonical_id,
)
from neurosphere_core.governance.policy.models import (
    EnforcementBinding,
    EnforcementModeName,
    PolicyDefinition,
    TargetRef,
)

__all__ = [
    "BAD_MODE_CHANGE_DIFF",
    "BAD_PUBLISH_DIFF",
    "ENFORCEMENT_BINDING_ENTITY_TYPE",
    "ENFORCEMENT_MODE_CHANGE_KIND",
    "GOVERNANCE_POLICY_PUBLISH_KIND",
    "ModeChangeDiff",
    "PublishDiff",
    "PublishStage",
    "binding_canonical_id",
    "mode_change_diff",
    "mode_change_target",
    "mode_change_target_version",
    "parse_mode_change_diff",
    "parse_publish_diff",
    "policy_digest",
    "publish_diff",
    "publish_target",
    "publish_target_version",
]

#: Action kinds of the two intents (PRP-99 conventions; PRP-108 registers their target).
GOVERNANCE_POLICY_PUBLISH_KIND: Final = "governance_policy_publish"
ENFORCEMENT_MODE_CHANGE_KIND: Final = "enforcement_mode_change"
ENFORCEMENT_BINDING_ENTITY_TYPE: Final = "enforcement_binding"

BAD_PUBLISH_DIFF: Final = "bad_publish_diff"
BAD_MODE_CHANGE_DIFF: Final = "bad_mode_change_diff"

PublishStage = Literal["publish", "retire"]

_VERSION_PATH: Final = "/policy_version"
_DIGEST_PATH: Final = "/policy_digest"
_STATUS_PATH: Final = "/status"
_MODE_PATH: Final = "/mode"
_STATUS_BY_STAGE: Final[Mapping[str, str]] = {"publish": "published", "retire": "retired"}
_STAGE_BY_STATUS: Final[Mapping[str, PublishStage]] = {"published": "publish", "retired": "retire"}
_REQUIRED_STATUS: Final[Mapping[str, str]] = {"publish": "draft", "retire": "published"}
_MODES: Final = frozenset(get_args(EnforcementModeName))
_DIGEST_PREFIX: Final = "sha256:"
_HEX: Final = frozenset("0123456789abcdef")
#: Fields left out of :func:`policy_digest`: they change when the version is published.
_DIGEST_EXCLUDED: Final = frozenset(
    {"status", "published_at", "published_intent_id", "published_audit_id"}
)


@dataclass(frozen=True, slots=True)
class PublishDiff:
    """A parsed ``governance_policy_publish`` diff."""

    stage: PublishStage
    policy_version: int
    policy_digest: str


@dataclass(frozen=True, slots=True)
class ModeChangeDiff:
    """A parsed ``enforcement_mode_change`` diff."""

    current_mode: EnforcementModeName
    mode: EnforcementModeName


def _bad(reason: str, detail: str) -> InvalidSchemaError:
    return InvalidSchemaError(
        detail, errors=[ValidationIssue("/proposed_diff", detail)], reason=reason
    )


def _is_digest(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith(_DIGEST_PREFIX):
        return False
    hex_part = value[len(_DIGEST_PREFIX) :]
    return len(hex_part) == 64 and set(hex_part) <= _HEX


def _diff(operations: Sequence[Mapping[str, Any]]) -> ProposedDiff:
    diff = ProposedDiff(
        format="json_patch",
        operations=[PatchOperation.model_validate(dict(op)) for op in operations],
    )
    validate_proposed_diff(diff)
    return diff


def _coerce(diff: ProposedDiff | Mapping[str, Any], reason: str) -> ProposedDiff:
    if isinstance(diff, ProposedDiff):
        parsed = diff
    else:
        try:
            parsed = ProposedDiff.model_validate(dict(diff))
        except (ValidationError, TypeError, ValueError):
            raise _bad(reason, "proposed_diff is not an RFC 6902 JSON Patch") from None
    validate_proposed_diff(parsed)
    return parsed


def _values(
    diff: ProposedDiff, expected: frozenset[tuple[str, str]], reason: str
) -> dict[tuple[str, str], Any]:
    """Each expected (op, path) exactly once and nothing else; returns their values."""
    found: dict[tuple[str, str], Any] = {}
    for op in diff.operations:
        key = (op.op, op.path)
        if key not in expected or key in found:
            raise _bad(reason, "the diff does not have the expected grammar")
        found[key] = op.value
    if set(found) != expected:
        raise _bad(reason, "the diff does not have the expected grammar")
    return found


# --- governance_policy_publish ------------------------------------------------------------------


def policy_digest(policy: PolicyDefinition) -> str:
    """``sha256:`` over the canonical JSON of the version, publish fields left out.

    It covers the rules, mode, severity, domain and display name: any change to what the maker
    confirmed changes the digest, while publishing the version does not.
    """
    body = {k: v for k, v in policy.model_dump(mode="json").items() if k not in _DIGEST_EXCLUDED}
    return sha256_digest(body)


def publish_target(policy: PolicyDefinition) -> TargetRef:
    """The ``governance_policy`` target of a publish or retire intent."""
    return TargetRef(
        canonical_id=governance_policy_canonical_id(
            policy.cloud.root, policy.customer_id.root, policy.policy_id.root
        ),
        entity_type=GOVERNANCE_POLICY_ENTITY_TYPE,
    )


def publish_target_version(policy: PolicyDefinition) -> str:
    """``v<policy_version>``: the intent binds to the exact version."""
    return f"v{policy.policy_version}"


def publish_diff(stage: PublishStage, policy: PolicyDefinition) -> ProposedDiff:
    """The diff a maker confirms to publish (a draft) or retire (a published version)."""
    if stage not in _STATUS_BY_STAGE:
        raise _bad(BAD_PUBLISH_DIFF, "stage must be publish or retire")
    if policy.status != _REQUIRED_STATUS[stage]:
        raise InvalidSchemaError(
            "the policy version is not in the state this stage needs",
            errors=[ValidationIssue("/status", f"{stage} needs {_REQUIRED_STATUS[stage]}")],
            reason="policy_not_draft" if stage == "publish" else "policy_not_published",
        )
    return _diff(
        [
            {"op": "test", "path": _VERSION_PATH, "value": policy.policy_version},
            {"op": "test", "path": _DIGEST_PATH, "value": policy_digest(policy)},
            {"op": "replace", "path": _STATUS_PATH, "value": _STATUS_BY_STAGE[stage]},
        ]
    )


_PUBLISH_KEYS: Final = frozenset(
    {("test", _VERSION_PATH), ("test", _DIGEST_PATH), ("replace", _STATUS_PATH)}
)


def parse_publish_diff(diff: ProposedDiff | Mapping[str, Any]) -> PublishDiff:
    """Strict inverse of :func:`publish_diff` (operations in any order, each exactly once)."""
    values = _values(_coerce(diff, BAD_PUBLISH_DIFF), _PUBLISH_KEYS, BAD_PUBLISH_DIFF)
    version = values[("test", _VERSION_PATH)]
    digest = values[("test", _DIGEST_PATH)]
    status = values[("replace", _STATUS_PATH)]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise _bad(BAD_PUBLISH_DIFF, "policy_version must be a positive integer")
    if not _is_digest(digest):
        raise _bad(BAD_PUBLISH_DIFF, "policy_digest must be a sha256 digest")
    if not isinstance(status, str) or status not in _STAGE_BY_STATUS:
        raise _bad(BAD_PUBLISH_DIFF, "status must be published or retired")
    return PublishDiff(
        stage=_STAGE_BY_STATUS[status], policy_version=version, policy_digest=cast(str, digest)
    )


# --- enforcement_mode_change --------------------------------------------------------------------


def binding_canonical_id(binding: EnforcementBinding) -> str:
    """``<cloud>:<customer>:neurosphere:enforcement_binding:<binding_id>``."""
    canonical = ":".join(
        (
            binding.cloud.root,
            binding.customer_id.root,
            NEUROSPHERE_SOURCE,
            ENFORCEMENT_BINDING_ENTITY_TYPE,
            binding.binding_id.root,
        )
    )
    return TargetRef(
        canonical_id=canonical, entity_type=ENFORCEMENT_BINDING_ENTITY_TYPE
    ).canonical_id


def mode_change_target(binding: EnforcementBinding) -> TargetRef:
    """The ``enforcement_binding`` target of a mode-change intent."""
    return TargetRef(
        canonical_id=binding_canonical_id(binding), entity_type=ENFORCEMENT_BINDING_ENTITY_TYPE
    )


def mode_change_target_version(admin_version: int) -> str:
    """``v<admin_config version>`` of the binding document the intent binds to."""
    if admin_version < 1:
        raise _bad(BAD_MODE_CHANGE_DIFF, "binding versions start at 1")
    return f"v{admin_version}"


def mode_change_diff(binding: EnforcementBinding, mode: EnforcementModeName) -> ProposedDiff:
    """The diff a maker confirms to move ``binding`` from its current mode to ``mode``."""
    current = binding.mode.root if binding.mode is not None else "audit"
    if mode not in _MODES:
        raise _bad(BAD_MODE_CHANGE_DIFF, "mode must be off, audit or enforce")
    if mode == current:
        raise _bad("mode_unchanged", "the binding is already in that mode")
    return _diff(
        [
            {"op": "test", "path": _MODE_PATH, "value": current},
            {"op": "replace", "path": _MODE_PATH, "value": mode},
        ]
    )


_MODE_KEYS: Final = frozenset({("test", _MODE_PATH), ("replace", _MODE_PATH)})


def parse_mode_change_diff(diff: ProposedDiff | Mapping[str, Any]) -> ModeChangeDiff:
    """Strict inverse of :func:`mode_change_diff` (test then replace of ``/mode``, once each)."""
    values = _values(_coerce(diff, BAD_MODE_CHANGE_DIFF), _MODE_KEYS, BAD_MODE_CHANGE_DIFF)
    current = values[("test", _MODE_PATH)]
    mode = values[("replace", _MODE_PATH)]
    if (
        not isinstance(current, str)
        or not isinstance(mode, str)
        or current not in _MODES
        or mode not in _MODES
    ):
        raise _bad(BAD_MODE_CHANGE_DIFF, "modes must be off, audit or enforce")
    if current == mode:
        raise _bad("mode_unchanged", "the diff does not change the mode")
    return ModeChangeDiff(
        current_mode=cast(EnforcementModeName, current), mode=cast(EnforcementModeName, mode)
    )
