"""Document layout and (de)serialization shared by every catalog backend.

Every stored document is an envelope around the validated contract body::

    {id, doc_type, ref, cloud, customer_id, domain_id, <partition key fields>,
     <allowlisted filter fields>, sort_key?, body: {...contract model JSON...}}

* ``id`` is the storage ID: ``<doc_type>:<ref>`` with ``/`` percent-encoded (Cosmos forbids
  ``/`` in IDs and canonical IDs may contain it). ``ref`` is the raw canonical/evidence ID.
* The partition key fields are named after ``partition_key_paths(shape)`` and valued by
  ``partition_key_values(...)``: the ONLY place a key shape is turned into document fields.
* ``cloud``, ``customer_id`` and ``domain_id`` are denormalized from the body so the scope
  predicate is a plain server-side filter. They are written from the validated body, which the
  engine has already checked against the caller's scope.
"""

from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime
from typing import Any, TypeGuard, get_args
from urllib.parse import quote

from neurosphere_contracts.catalog.v1.alias import Alias
from neurosphere_contracts.catalog.v1.edge_override import EdgeOverride
from pydantic import BaseModel, ValidationError

from neurosphere_core.catalog.partitioning import (
    DEFAULT_SHARD_COUNT,
    PartitionKeyShape,
    partition_key_paths,
    partition_key_values,
)
from neurosphere_core.catalog.protocol import (
    CANONICAL_ID_PATTERN,
    CatalogEdge,
    CatalogEntity,
    EdgeObservation,
)
from neurosphere_core.catalog.repo.backend import DocType
from neurosphere_core.catalog.rules import format_timestamp, parse_timestamp
from neurosphere_core.errors.taxonomy import InvalidSchemaError

_CANONICAL = re.compile(CANONICAL_ID_PATTERN)
_EVIDENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/=-]{0,255}")
_ID_SAFE = ":=.-_"


def _variant_map(union: object, discriminator: str) -> dict[str, type[BaseModel]]:
    result: dict[str, type[BaseModel]] = {}
    for cls in get_args(union):
        annotation = cls.model_fields[discriminator].annotation
        result[get_args(annotation)[0]] = cls
    return result


ENTITY_MODELS: dict[str, type[BaseModel]] = _variant_map(CatalogEntity, "entity_type")
EDGE_MODELS: dict[str, type[BaseModel]] = _variant_map(CatalogEdge, "relation_type")


# --------------------------------------------------------------------------- identifiers


def is_canonical_id(value: object) -> TypeGuard[str]:
    """True when ``value`` is a string that FULLY matches the canonical ID grammar.

    ``re.fullmatch`` (not ``search``): Python's ``$`` accepts a trailing newline.
    """
    return isinstance(value, str) and len(value) <= 512 and _CANONICAL.fullmatch(value) is not None


def id_segments(canonical_id: str) -> tuple[str, str, str, str, str]:
    """``(cloud, customer, source, type, id)``; raises ``InvalidSchemaError`` if malformed."""
    if not is_canonical_id(canonical_id):
        raise InvalidSchemaError("malformed canonical ID")
    cloud, customer, source, kind, rest = canonical_id.split(":", 4)
    return cloud, customer, source, kind, rest


def check_id(
    canonical_id: str, *, cloud: str, customer_id: str, type_segment: str | None = None
) -> None:
    """Grammar plus cloud/customer (and optionally type) segment agreement with the body."""
    seg_cloud, seg_customer, _, seg_type, _ = id_segments(canonical_id)
    if seg_cloud != cloud or seg_customer != customer_id:
        raise InvalidSchemaError("canonical ID cloud or customer segment does not match")
    if type_segment is not None and seg_type != type_segment:
        raise InvalidSchemaError("canonical ID type segment does not match")


def check_evidence_id(value: str) -> None:
    if _EVIDENCE.fullmatch(value) is None:
        raise InvalidSchemaError("malformed evidence or observation ID")


def storage_id(doc_type: DocType, ref: str) -> str:
    """Cosmos-safe, reversible document ID (``/`` becomes ``%2F``)."""
    return f"{doc_type}:{quote(ref, safe=_ID_SAFE)}"


# --------------------------------------------------------------------------- cursors


def encode_cursor(value: str) -> str:
    """Opaque keyset cursor: the last sort value only. Scope is re-applied on every page."""
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> str:
    try:
        return base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
    except (binascii.Error, UnicodeError, ValueError) as exc:
        raise InvalidSchemaError("invalid cursor") from exc


# --------------------------------------------------------------------------- body (de)serialization


def dump(model: BaseModel) -> dict[str, Any]:
    """JSON-mode dump of a contract model (RootModels collapse to plain values)."""
    return model.model_dump(mode="json")


def validate_model[M: BaseModel](cls: type[M], body: dict[str, Any]) -> M:
    """``model_validate`` that reports a contract violation as ``invalid_schema`` (no values)."""
    try:
        return cls.model_validate(body)
    except ValidationError as exc:
        raise InvalidSchemaError("the document does not satisfy its contract") from exc


def parse_entity(body: dict[str, Any]) -> CatalogEntity:
    cls = ENTITY_MODELS.get(str(body.get("entity_type")))
    if cls is None:
        raise InvalidSchemaError("unknown entity_type")
    return validate_model(cls, body)  # type: ignore[return-value]


def parse_edge(body: dict[str, Any]) -> CatalogEdge:
    cls = EDGE_MODELS.get(str(body.get("relation_type")))
    if cls is None:
        raise InvalidSchemaError("unknown relation_type")
    return validate_model(cls, body)  # type: ignore[return-value]


def revalidate_entity(entity: CatalogEntity) -> dict[str, Any]:
    """Round-trip through the contract so a ``model_construct``-built object cannot slip in."""
    body = dump(entity)
    parse_entity(body)
    return body


def revalidate_edge(edge: CatalogEdge) -> dict[str, Any]:
    body = dump(edge)
    parse_edge(body)
    return body


def entity_domain(body: dict[str, Any]) -> str | None:
    """Owning domain of an entity body: a Domain is its own scope anchor."""
    if body.get("entity_type") == "domain":
        return str(body["id"])
    domain = body.get("domain_id")
    return None if domain is None else str(domain)


# --------------------------------------------------------------------------- envelopes


def partition_fields(
    shape: PartitionKeyShape,
    customer_id: str,
    domain_id: str,
    ref: str,
    shard_count: int = DEFAULT_SHARD_COUNT,
) -> dict[str, str]:
    """Partition key fields for one document, named from the shape's key paths."""
    names = [path.lstrip("/") for path in partition_key_paths(shape)]
    values = partition_key_values(shape, customer_id, domain_id, ref, shard_count)
    return dict(zip(names, values, strict=True))


def make_doc(
    shape: PartitionKeyShape,
    doc_type: DocType,
    ref: str,
    body: dict[str, Any],
    *,
    cloud: str,
    customer_id: str,
    domain_id: str,
    filters: dict[str, str] | None = None,
    sort_key: str | None = None,
    shard_count: int = DEFAULT_SHARD_COUNT,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": storage_id(doc_type, ref),
        "doc_type": doc_type,
        "ref": ref,
        "cloud": cloud,
        "customer_id": customer_id,
        "domain_id": domain_id,
        **partition_fields(shape, customer_id, domain_id, ref, shard_count),
        **(filters or {}),
        "body": body,
    }
    if sort_key is not None:
        doc["sort_key"] = sort_key
    return doc


def observation_sort_key(observation: EdgeObservation) -> str:
    """Fixed-width UTC microsecond timestamp plus ID: one string orders newest-first reliably
    (the contract allows 1..9 fractional digits, which do not sort lexicographically).
    """
    return f"{format_timestamp(parse_timestamp(observation.observed_at.root))}|{observation.id}"


def override_sort_key(override: EdgeOverride) -> str:
    return f"{format_timestamp(parse_timestamp(override.decided_at.root))}|{override.id}"


def alias_filters(alias: Alias) -> dict[str, str]:
    return {
        "alias_source_id": alias.alias_source_id.root,
        "alias_kind": alias.alias_kind,
        "alias_value": alias.alias_value,
        "alias_status": alias.status,
    }


def is_expired(timestamp: str | None, now: datetime) -> bool:
    """True when an RFC 3339 expiry is not strictly after ``now`` (None never expires)."""
    return timestamp is not None and parse_timestamp(timestamp) <= now
