"""Alias key, derived agent id and owned-agent check for telemetry agent identity (PRP-137)."""

from __future__ import annotations

import hashlib
import re
from typing import Final

from neurosphere_core.catalog.protocol import AliasKey

_CANONICAL: Final = re.compile(
    r"(commercial|government):[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._-]+:[a-z0-9._/=-]+"
)
_TOKEN: Final = re.compile(r"[a-z0-9][a-z0-9._-]*")
_UNSAFE: Final = re.compile(r"[^a-z0-9._-]+")
_MAX_ID: Final = 512
_HASH_CHARS: Final = 8
AGENT_TYPE: Final = "agent"


def slug(value: str, fallback: str) -> str:
    """Lowercase ``[a-z0-9._-]`` form of ``value``; ``fallback`` when nothing usable remains.

    The same rule ``AliasModelResolver`` (projections/catalog/mapping.py) uses.
    """
    cleaned = _UNSAFE.sub("-", value.lower()).strip("-._")
    return cleaned[:128] if _TOKEN.fullmatch(cleaned[:128]) else fallback


def agent_alias_key(source_id: str, external_id: str) -> AliasKey:
    """The ``external_id`` alias key of an agent in a telemetry source."""
    return AliasKey(
        alias_source_id=slug(source_id, "trace"), alias_kind="external_id", alias_value=external_id
    )


def derive_agent_id(cloud: str, customer: str, source: str, external_id: str) -> str:
    """``<cloud>:<customer>:<source>:agent:<slug>``, stable for one external id.

    When the slug differs from the lowercased external id (characters replaced, trimmed,
    truncated, or empty) ``-<first 8 hex of sha256(external id)>`` is appended, so two external
    ids that slug alike never share a derived id. The result always fits the canonical grammar
    and the 512 character limit.
    """
    prefix = f"{cloud}:{customer}:{slug(source, 'trace')}:{AGENT_TYPE}:"
    budget = max(_MAX_ID - len(prefix) - _HASH_CHARS - 1, 1)
    base = slug(external_id, "")[:budget].rstrip("-._")
    if base and base == external_id.lower():
        return prefix + base
    digest = hashlib.sha256(external_id.encode("utf-8")).hexdigest()[:_HASH_CHARS]
    return f"{prefix}{base}-{digest}" if base else f"{prefix}agent-{digest}"


def is_owned_agent(value: str | None, cloud: str, customer: str) -> bool:
    """True for a canonical id of type ``agent`` in the same cloud and customer."""
    if value is None or len(value) > _MAX_ID or not _CANONICAL.fullmatch(value):
        return False
    value_cloud, value_customer, _source, kind, _ident = value.split(":", 4)
    return value_cloud == cloud and value_customer == customer and kind == AGENT_TYPE
