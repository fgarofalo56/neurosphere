"""Response models of the connector admin API (PRP-42).

Defined here, not the generated contract classes: a contract model used as ``response_model``
renames ``openapi.json`` components. A Key Vault secret URI is returned to the authorized admin
(it names which secret is used; it is not the secret); no value of any secret exists in the
store to return.
"""

from __future__ import annotations

from typing import Final, cast

from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_contracts.admin.v1.connector_config import ConnectorConfig
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ConnectorPage", "ConnectorView", "CredentialView", "view"]

MAX_PAGE_LIMIT: Final = 200


class CredentialView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    secret_uri: str | None = None
    managed_identity_client_id: str | None = None


class ConnectorView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_id: str
    connector_kind: str
    domain_ids: list[str]
    settings: dict[str, str | int | bool]
    credential: CredentialView | None
    enabled: bool
    status: str
    version: int
    updated_at: str
    updated_by: str
    #: Non-blocking findings of the write, e.g. ``producer_not_in_store``.
    warnings: list[str] = Field(default_factory=list)


class ConnectorPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ConnectorView]


def view(document: AdminConfigDocument, warnings: tuple[str, ...] = ()) -> ConnectorView:
    body = document.body
    assert isinstance(body, ConnectorConfig)
    credential = body.credential
    return ConnectorView(
        connector_id=body.connector_id.root,
        connector_kind=body.connector_kind,
        domain_ids=[d.root for d in body.domain_ids],
        settings={
            k: cast("str | int | bool", getattr(v, "root", v)) for k, v in body.settings.items()
        },
        credential=None
        if credential is None
        else CredentialView(
            kind=credential.kind,
            secret_uri=credential.secret_uri,
            managed_identity_client_id=credential.managed_identity_client_id,
        ),
        enabled=body.enabled,
        status=document.status,
        version=document.version.root,
        updated_at=document.updated_at.root,
        updated_by=document.updated_by.root,
        warnings=list(warnings),
    )
