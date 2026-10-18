"""Fabric adapter configuration and the cloud boundary (PRP-11 clarification 9).

The config is frozen, ``extra="forbid"`` and has NO secret field at all: authentication is
Microsoft Entra / managed identity only, so there is nothing to leak into logs. An optional
``managed_identity_client_id`` names a user-assigned identity; it is an identifier, not a
credential.

Cloud boundary, enforced at construction (a validator), never at first call:

* Commercial hosts must end in ``.datawarehouse.fabric.microsoft.com``;
* Government (GCC High) hosts must end in ``.fabric.microsoft.us`` (INFERRED, UNVERIFIED, see
  below);
* the two suffix sets are disjoint, so a host valid for one cloud is rejected for the other;
* Government Fabric is available only in ``usgovvirginia`` / ``usgovtexas``; a Government config
  with any other region (or a Commercial region) is rejected, and so is the reverse.

Sources (observed 2026-10-18):

* Fabric in GCC High, REST host ``highapi.fabric.microsoft.us``, GA in US Gov Virginia and
  Texas: https://learn.microsoft.com/fabric/enterprise/us-government-community-cloud-high
* The Commercial SQL endpoint form ``<unique-id>.datawarehouse.fabric.microsoft.com`` is the
  form shown by the Fabric connectivity docs for warehouses and lakehouse SQL analytics
  endpoints (https://learn.microsoft.com/fabric/data-warehouse/how-to-connect and the
  ``*.datawarehouse.fabric.microsoft.com`` TCP 1433 row of
  https://learn.microsoft.com/fabric/security/fabric-allow-list-urls, observed 2026-10-18).
  Learn also shows ``<id>.<tenant>.fabric.microsoft.com`` for the SQL analytics endpoint of a
  Fabric SQL database; that item kind is out of scope here, so the form is not accepted.
* The Government SQL endpoint suffix ``.fabric.microsoft.us`` is INFERRED, UNVERIFIED: Learn
  documents only the REST host for GCC High. It is a G12 / G01 gap (see ``G12_PARITY_GAPS``) and
  must be confirmed against a real GCC High workspace before any Government use.

Availability is not authorization; nothing here is an ATO or FedRAMP claim.
"""

from __future__ import annotations

import re
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from neurosphere_core.analytics.base.models import Cloud

COMMERCIAL_HOST_SUFFIX: Final = ".datawarehouse.fabric.microsoft.com"
# inferred, unverified: Learn documents only the GCC High REST host (highapi.fabric.microsoft.us)
GOVERNMENT_HOST_SUFFIX: Final = ".fabric.microsoft.us"
HOST_SUFFIXES: Final[dict[str, str]] = {
    "commercial": COMMERCIAL_HOST_SUFFIX,
    "government": GOVERNMENT_HOST_SUFFIX,
}
GOVERNMENT_REGIONS: Final = ("usgovvirginia", "usgovtexas")
UNVERIFIED_HOST_SUFFIX_CLOUDS: Final = ("government",)

ItemKind = Literal["warehouse", "lakehouse_sql_endpoint"]
AuthMode = Literal["entra_managed_identity"]

_HOST_RE = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"
)
_REGION_RE = re.compile(r"^[a-z][a-z0-9]{2,39}$")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ -]{0,127}$")
_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class FabricConfig(BaseModel):
    """Everything needed to address one Fabric SQL endpoint, validated against its cloud."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cloud: Cloud
    region: str
    sql_endpoint_host: str
    database: str
    item_kind: ItemKind = "warehouse"
    auth_mode: AuthMode = "entra_managed_identity"
    managed_identity_client_id: str | None = None
    schema_name: str = Field(default="dbo")

    @model_validator(mode="after")
    def _validate_boundary(self) -> Self:
        host = self.sql_endpoint_host
        if host != host.strip().lower() or not _HOST_RE.match(host):
            raise ValueError(
                "sql_endpoint_host must be a lowercase bare hostname (no scheme, port or path)"
            )
        suffix = HOST_SUFFIXES[self.cloud]
        if not host.endswith(suffix) or host == suffix.lstrip("."):
            raise ValueError(f"sql_endpoint_host does not belong to the {self.cloud} cloud")
        other = HOST_SUFFIXES["government" if self.cloud == "commercial" else "commercial"]
        if host.endswith(other):  # unreachable while the suffixes stay disjoint; fail closed
            raise ValueError(f"sql_endpoint_host belongs to the other cloud than {self.cloud}")
        if not _REGION_RE.match(self.region):
            raise ValueError("region must be a lowercase ARM region name")
        if self.cloud == "government":
            if self.region not in GOVERNMENT_REGIONS:
                raise ValueError(
                    "Fabric in GCC High is available only in "
                    + " and ".join(GOVERNMENT_REGIONS)
                    + f"; region {self.region!r} is not"
                )
        elif self.region.startswith(("usgov", "usdod")) or self.region == "global":
            raise ValueError("region does not belong to the commercial cloud")
        if not _IDENT_RE.match(self.database):
            raise ValueError("database must be a plain Fabric item name")
        if not _SCHEMA_RE.match(self.schema_name):
            raise ValueError("schema_name must be a plain identifier")
        if self.managed_identity_client_id and not _GUID_RE.match(self.managed_identity_client_id):
            raise ValueError("managed_identity_client_id must be a GUID")
        return self

    @property
    def read_only(self) -> bool:
        """A lakehouse SQL analytics endpoint is read-only; only a warehouse takes DDL/DML."""
        return self.item_kind != "warehouse"


__all__ = [
    "COMMERCIAL_HOST_SUFFIX",
    "GOVERNMENT_HOST_SUFFIX",
    "GOVERNMENT_REGIONS",
    "HOST_SUFFIXES",
    "UNVERIFIED_HOST_SUFFIX_CLOUDS",
    "AuthMode",
    "FabricConfig",
    "ItemKind",
]
