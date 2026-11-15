"""Audit chain naming for admin configuration writes (PRP-65).

Every accepted ``admin_config`` write (create, replace, retire) is recorded by the caller
(PRP-41, 42, 44, 45) on ONE customer-level chain, ``<customer>.admin-config``, in the catalog-shaped
customer-level form the other customer-wide chains use (``<customer>.gateway``,
``<customer>.execution-control``; see ``neurosphere_core.audit.chains``).

Known limit of that shared convention: a catalog-source domain literally named ``admin-config``
would decode to the same chain id through ``domain_from_audit_chain``. The domain-definition write
path (PRP-44) must refuse that reserved name, as it must ``gateway`` and ``execution-control``.
"""

from __future__ import annotations

import re
from typing import Final

from neurosphere_core.errors import InvalidSchemaError

__all__ = ["ADMIN_CONFIG_CHAIN_SUFFIX", "admin_config_chain_id"]

ADMIN_CONFIG_CHAIN_SUFFIX: Final = "admin-config"
_CUSTOMER: Final = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_CHAIN: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


def admin_config_chain_id(customer_id: str) -> str:
    """``<customer>.admin-config``; ``invalid_schema`` (``invalid_chain_id``) when unencodable."""
    chain = f"{customer_id}.{ADMIN_CONFIG_CHAIN_SUFFIX}"
    if not _CUSTOMER.fullmatch(customer_id) or not _CHAIN.fullmatch(chain):
        raise InvalidSchemaError(
            "customer id cannot name an audit chain", reason="invalid_chain_id"
        )
    return chain
