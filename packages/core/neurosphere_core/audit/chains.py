"""Per-domain audit chain ids: one reversible, source-qualified encoding (PRP-31 item 14b).

A canonical domain id is ``<cloud>:<customer>:<source>:domain:<name>``. Every per-domain audit
chain (catalog, curation, actions, HITL, reports, publication) is named by
:func:`domain_audit_chain_id`, and every reader maps a chain back with
:func:`domain_from_audit_chain`. Nothing here depends on which domains a caller holds.

Format
------

* ``source == "catalog"``: ``<customer>.<name>``. Byte-identical to the chain every writer used
  before item 14b, so existing catalog-source chains need no migration.
* any other source: ``<customer>._<len(source)>.<source>.<name>``, for example
  ``contoso._7.sandbox.dom-001``. ``<len(source)>`` is the decimal length of ``<source>`` with no
  leading zero.

Why it is unambiguous
---------------------

The inverse is given the caller's ``cloud`` and ``customer_id`` and strips ``<customer>.``. The
remainder starts either with ``[a-z0-9]`` (catalog form) or with ``_`` (source-qualified form):

* a catalog ``<name>`` must match ``^[a-z0-9][a-z0-9._-]{0,127}$`` (the writer refuses any other
  catalog name), so it can never start with the ``_`` marker, and a source-qualified chain can
  never parse as a catalog one;
* in the source-qualified form the length prefix says exactly where ``<source>`` ends, so dots,
  dashes and underscores inside ``<source>`` or ``<name>`` never shift the split;
* the inverse re-encodes its result and accepts only an exact match, so there is one encoding
  per domain id (no leading zeros, no ``_7.catalog.x`` alias of ``x``, no other spelling).

Encoding is a function and decoding is its left inverse, so two distinct domain ids never share a
chain. Two more rules keep that true across customers: the customer id must match
``^[a-z0-9][a-z0-9_-]*$`` (no ``.``: with a dotted customer, ``a.b`` + ``c`` and ``a`` + ``b.c``
would collide, and the audit mount already refused every dotted customer), and the whole id must
match the ``AuditRecord`` ``chain_id`` pattern ``^[a-z0-9][a-z0-9._-]{0,127}$``.

The cloud is not in the chain id: a deployment serves one cloud and has its own audit store, and
the reader takes the cloud from the caller's scope. Customer-level chains (``<customer>.gateway``,
``<customer>.execution-control`` and so on) are named elsewhere and keep the catalog-shaped form.

Fail closed: :func:`domain_audit_chain_id` raises ``InvalidSchemaError(reason="invalid_chain_id")``
(the same refusal ``AuditRepository.append`` gives an invalid chain) for any domain id it cannot
encode: wrong shape, another customer, a name outside the pattern (``/`` and ``=`` are legal in a
domain name but not in a chain id), or too long. :func:`domain_from_audit_chain` returns ``None``
for anything that is not an exact encoding.

Legacy limitation: before item 14b every writer named a chain ``<customer>.<last segment>`` for
every source. Records already written that way for a NON-catalog domain sit on a chain that now
decodes to the ``catalog`` domain of that name (or to nothing), so they stay unreadable through
the domain routes, exactly as they were before. They are not migrated.
"""

from __future__ import annotations

import re
from typing import Final

from neurosphere_core.errors import InvalidSchemaError

__all__ = [
    "CATALOG_SOURCE",
    "SOURCE_MARKER",
    "domain_audit_chain_id",
    "domain_from_audit_chain",
]

CATALOG_SOURCE: Final = "catalog"
#: First character of the source-qualified remainder; never the first character of a catalog name.
SOURCE_MARKER: Final = "_"

_CHAIN: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_CUSTOMER: Final = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SEGMENT: Final = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_CLOUDS: Final = frozenset({"commercial", "government"})
_QUALIFIED: Final = re.compile(r"^_([1-9][0-9]{0,2})\.(.*)$", re.DOTALL)


def _refuse(message: str) -> InvalidSchemaError:
    return InvalidSchemaError(message, reason="invalid_chain_id")


def domain_audit_chain_id(customer_id: str, domain_id: str) -> str:
    """The audit chain of ``domain_id`` (a canonical domain id of ``customer_id``).

    Raises ``InvalidSchemaError`` (``invalid_chain_id``) when the id cannot be encoded.
    """
    if not _CUSTOMER.fullmatch(customer_id):
        raise _refuse("customer id cannot name an audit chain")
    parts = domain_id.split(":")
    if (
        len(parts) != 5
        or parts[0] not in _CLOUDS
        or parts[1] != customer_id
        or parts[3] != "domain"
    ):
        raise _refuse("not a canonical domain id of this customer")
    source, name = parts[2], parts[4]
    if not _SEGMENT.fullmatch(source) or not _SEGMENT.fullmatch(name):
        raise _refuse("domain id segment cannot name an audit chain")
    if source == CATALOG_SOURCE:
        chain = f"{customer_id}.{name}"
    else:
        chain = f"{customer_id}.{SOURCE_MARKER}{len(source)}.{source}.{name}"
    if not _CHAIN.fullmatch(chain):
        raise _refuse("audit chain id too long")
    return chain


def domain_from_audit_chain(cloud: str, customer_id: str, chain_id: str) -> str | None:
    """The one domain id whose chain is exactly ``chain_id``, or ``None``.

    Independent of the caller's grants: the permission check on the returned domain decides
    access. ``None`` for another customer, a customer-wide chain, or any non-canonical spelling.
    """
    if cloud not in _CLOUDS or not _CUSTOMER.fullmatch(customer_id):
        return None
    if not _CHAIN.fullmatch(chain_id) or not chain_id.startswith(f"{customer_id}."):
        return None
    rest = chain_id[len(customer_id) + 1 :]
    if rest.startswith(SOURCE_MARKER):
        match = _QUALIFIED.fullmatch(rest)
        if match is None:
            return None
        length = int(match.group(1))
        body = match.group(2)
        source, dot, name = body[:length], body[length : length + 1], body[length + 1 :]
        if len(source) != length or dot != ".":
            return None
    else:
        source, name = CATALOG_SOURCE, rest
    candidate = f"{cloud}:{customer_id}:{source}:domain:{name}"
    try:
        encoded = domain_audit_chain_id(customer_id, candidate)
    except InvalidSchemaError:
        return None
    return candidate if encoded == chain_id else None
