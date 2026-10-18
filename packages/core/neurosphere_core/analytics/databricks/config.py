"""Validated Azure Databricks adapter config and the cloud boundary (PRP-11 item 4).

Everything that reaches SQL text (catalog, schema) is regex-checked here. The workspace host
must belong to the configured cloud; a mismatch fails at construction, never at first query.
Auth is Entra only: managed identity, or a service principal whose client secret is a Key Vault
reference (``CredentialRef``), never a value. There is no token or password field and
``extra="forbid"`` rejects one if supplied.

Host suffixes (adapter-local table), observed 2026-10-18:
Commercial ``adb-<workspace-id>.<n>.azuredatabricks.net``;
Government ``adb-<workspace-id>.<n>.databricks.azure.us``
(https://learn.microsoft.com/azure/private-link/private-endpoint-dns#government).
Government Databricks rows exist for usgovvirginia and usgovarizona only.
"""

from __future__ import annotations

import re
from typing import Annotated, Final, Literal, Self

from neurosphere_contracts.connectors.v1.connector_manifest import CredentialRef
from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from neurosphere_core.analytics.base.models import Cloud

HOST_SUFFIX: Final[dict[str, str]] = {
    "commercial": ".azuredatabricks.net",
    "government": ".databricks.azure.us",
}
GOVERNMENT_REGIONS: Final = frozenset({"usgovvirginia", "usgovarizona"})
_HOST_RE = re.compile(
    r"^adb-[0-9]{1,20}\.[0-9]{1,3}\.(azuredatabricks\.net|databricks\.azure\.us)$"
)
_IDENT = r"^[A-Za-z_][A-Za-z0-9_]{0,63}$"
_COMMERCIAL_REGION = re.compile(r"^[a-z0-9]{2,32}$")

AuthMode = Literal["managed_identity", "service_principal"]


class DatabricksConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cloud: Cloud
    region: Annotated[StrictStr, Field(pattern=r"^[a-z0-9]{2,32}$")]
    workspace_host: Annotated[StrictStr, Field(max_length=120)]
    warehouse_id: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{16}$")]
    catalog: Annotated[StrictStr, Field(pattern=_IDENT)]
    schema_name: Annotated[StrictStr, Field(pattern=_IDENT)]
    auth_mode: AuthMode = "managed_identity"
    # Entra application (client) id; an identifier, not a secret.
    client_id: Annotated[
        StrictStr | None,
        Field(
            default=None,
            pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        ),
    ] = None
    # Key Vault reference to the service-principal client secret; never a value.
    credential: Annotated[CredentialRef | None, Field(repr=False)] = None

    @model_validator(mode="after")
    def _boundary(self) -> Self:
        host = self.workspace_host.lower()
        if host != self.workspace_host or not _HOST_RE.match(host):
            raise ValueError("workspace_host must be a lowercase adb-<id>.<n> Databricks host")
        if not host.endswith(HOST_SUFFIX[self.cloud]):
            raise ValueError(f"workspace_host does not belong to the {self.cloud} cloud")
        if self.cloud == "government":
            if self.region not in GOVERNMENT_REGIONS:
                raise ValueError("government region must be usgovvirginia or usgovarizona")
        elif self.region.startswith(("usgov", "usdod")) or not _COMMERCIAL_REGION.match(
            self.region
        ):
            raise ValueError("region is not a commercial region")
        if self.auth_mode == "service_principal":
            if self.credential is None or self.client_id is None:
                raise ValueError("service_principal auth needs client_id and a vault credential")
        elif self.credential is not None:
            raise ValueError("managed_identity auth takes no credential")
        return self
