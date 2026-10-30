"""Recording a Grant publication in the catalog (PRP-34 items 5 and 10): the shared rules.

Used by ``POST /api/v1/catalog/grants/{id}/publication`` and by the worker's post-success
recorder, so both write exactly the same thing for the same verified intent. Pure functions over
the Grant document and the stored intent, plus one apply-record read:

* :func:`check_grant_intent` accepts only a ``grant_publish`` / ``grant_unpublish`` of THIS grant
  that is not a dry run, reached ``succeeded`` and verified (``verify_matched``), and whose diff
  has the grammar of its kind (a ``grant_publish`` carrying an unpublish diff is never recorded
  as an unpublish, and the reverse: ``intent_not_verified`` reason ``action_kind_mismatch``).
* :func:`grant_publication_update` returns the new Grant document: ``provenance`` names the
  gateway, connector and time; the publication facts go in the scalar ``attributes``
  (``apim_*``), ownership from the publish apply record (``unrecorded`` without one).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, cast

from neurosphere_core.actions import StoredIntent
from neurosphere_core.errors import InvalidSchemaError

from neurosphere_workers.publication.records import ApplyRecordReader

__all__ = [
    "CONNECTOR_VERSION",
    "GRANT_ENTITY_TYPE",
    "GRANT_KINDS",
    "PUBLISH_KIND",
    "UNPUBLISH_KIND",
    "check_grant_intent",
    "created_names",
    "grant_attributes",
    "grant_publication_update",
    "grant_recorded",
    "publication_gateway",
]

PUBLISH_KIND: Final = "grant_publish"
UNPUBLISH_KIND: Final = "grant_unpublish"
GRANT_KINDS: Final = frozenset({PUBLISH_KIND, UNPUBLISH_KIND})
GRANT_ENTITY_TYPE: Final = "grant"
CONNECTOR_VERSION: Final = "apim-gateway/0.1.0"
_PUBLICATION: Final = "/publication"
_NOT_VERIFIED: Final = "intent_not_verified"


def grant_attributes(doc: Mapping[str, Any]) -> dict[str, Any]:
    raw = doc.get("attributes")
    return dict(cast(Mapping[str, Any], raw)) if isinstance(raw, Mapping) else {}


def _shape_kind(stored: StoredIntent) -> str | None:
    """The kind a diff's grammar belongs to (``/plan_digest`` aside), or None."""
    ops = [op for op in stored.intent.proposed_diff.operations if op.path != "/plan_digest"]
    if len(ops) == 1 and ops[0].path == _PUBLICATION and ops[0].op == "add":
        return PUBLISH_KIND
    removes = [op for op in ops if op.path == _PUBLICATION and op.op == "remove"]
    others = [op for op in ops if op.path != _PUBLICATION]
    if (
        len(removes) == 1
        and len(ops) == len(others) + 1
        and all(op.op == "test" and op.path.startswith(_PUBLICATION + "/") for op in others)
    ):
        return UNPUBLISH_KIND
    return None


def check_grant_intent(stored: StoredIntent, grant_id: str) -> None:
    """Refuse anything but a verified, succeeded publication intent of this grant."""
    intent = stored.intent
    execution = stored.execution
    if (
        intent.action_kind not in GRANT_KINDS
        or intent.target.canonical_id != grant_id
        or intent.target.entity_type != GRANT_ENTITY_TYPE
        or intent.dry_run
        or intent.state.root != "succeeded"
        or execution is None
        or execution.verify_matched is not True
    ):
        raise InvalidSchemaError(
            "the intent is not a verified publication of this grant", reason=_NOT_VERIFIED
        )
    if _shape_kind(stored) != intent.action_kind:
        raise InvalidSchemaError(
            "the intent's diff does not belong to its action kind", reason="action_kind_mismatch"
        )


def publication_gateway(stored: StoredIntent) -> str:
    for op in stored.intent.proposed_diff.operations:
        value = op.value
        if op.path == _PUBLICATION and isinstance(value, Mapping):
            gateway = cast(Mapping[str, Any], value).get("gateway_id")
            if isinstance(gateway, str):
                return gateway
        if op.path == _PUBLICATION + "/gateway_id" and isinstance(value, str):
            return value
    raise InvalidSchemaError("the intent names no gateway", reason=_NOT_VERIFIED)


def created_names(record: Any) -> tuple[list[str], list[str]]:
    """(all upserted names, names recorded ``created``) of an apply record."""
    every: list[str] = []
    created: list[str] = []
    for step in getattr(record, "steps", ()):
        if getattr(step, "operation", None) != "upsert":
            continue
        name = str(step.name)
        every.append(name)
        if str(step.ownership) == "created":
            created.append(name)
    return every, created


def grant_recorded(doc: Mapping[str, Any], intent_id: str) -> bool:
    """True when this intent is already the recorded publication (idempotent replay)."""
    return grant_attributes(doc).get("apim_intent_id") == intent_id


def _rollback_token(stored: StoredIntent) -> str | None:
    execution = stored.execution
    token = (execution.apply_result or {}).get("rollback_token") if execution else None
    return str(token) if token else None


async def grant_publication_update(
    doc: Mapping[str, Any],
    stored: StoredIntent,
    records: ApplyRecordReader | None,
    now: str,
) -> dict[str, Any]:
    """The Grant document recording ``stored`` (call :func:`check_grant_intent` first)."""
    attrs = grant_attributes(doc)
    intent_id = str(stored.intent.intent_id.root)
    gateway_id = publication_gateway(stored)
    publishing = stored.intent.action_kind == PUBLISH_KIND
    token = _rollback_token(stored)
    attrs.update(
        apim_published=publishing,
        apim_gateway_id=gateway_id,
        apim_intent_id=intent_id,
        apim_apply_record=token,
    )
    if publishing:
        found = await records.latest(token) if records is not None and token else None
        if found is None:
            attrs.update(apim_ownership="unrecorded", apim_resources=None, apim_created=None)
        else:
            every, created = created_names(found)
            attrs.update(
                apim_ownership="recorded",
                apim_resources=",".join(every),
                apim_created=",".join(created),
            )
    else:
        attrs.update(apim_ownership=None, apim_resources=None, apim_created=None)
    out = dict(doc)
    out["attributes"] = attrs
    out["provenance"] = {
        "method": "declared",
        "source_id": gateway_id,
        "connector_version": CONNECTOR_VERSION,
        "recorded_at": now,
    }
    return out
