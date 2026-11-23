# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, StrictBool, StrictStr

from ...admin.v1 import common as common_1
from ...admin.v1 import credential_reference
from ...admin.v1.credential_reference import CredentialReference
from ...catalog.v1 import common


class LocalSinkUrl(RootModel[StrictStr]):
    root: Annotated[
        StrictStr,
        Field(
            max_length=256,
            pattern="^http://(127\\.0\\.0\\.1|localhost|[a-z][a-z0-9-]{0,62})(:[0-9]{1,5})?(/[A-Za-z0-9._~%-]{1,128})*/?$",
        ),
    ] = None
    """
    Plain-HTTP loopback or compose-service URL with no query string or userinfo. Present when and only when local_sink is true.
    """


class KeyVaultSecretReference(CredentialReference):
    """
    A CredentialReference narrowed to a Key Vault secret (a managed identity alone cannot hold an endpoint).
    """

    model_config = ConfigDict(
        extra="forbid",
    )


class NotificationChannel(BaseModel):
    """
    A notification channel (PRP-99; body of admin_kind notification_channel). The endpoint is never a property of this document: it lives in Key Vault and is referenced by endpoint_credential (key_vault_secret only). The one exception is local_sink_url, a plain-HTTP loopback or compose-service URL for local development (core refuses local_sink unless NS_ENV=local). Rules the Pydantic projection drops (if/then) are pinned by tests/contracts/test_governance_a_notifications.py: local_sink requires local_sink_url and local_sink_url requires local_sink; endpoint_credential is null only with local_sink; a webhook channel needs hmac_credential unless local_sink.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    schema_version: common.SchemaVersion
    channel_id: common_1.Slug
    """
    Channel id (slug).
    """
    cloud: common.Cloud
    customer_id: common.CustomerId
    domain_id: common.DomainId
    display_name: common_1.DisplayName
    kind: Literal["webhook", "teams_webhook", "email"]
    """
    Transport. Open-ended: readers must tolerate unknown values. email is declared; PRP-107 may ship it not_built.
    """
    allowed_host: Annotated[
        StrictStr,
        Field(
            max_length=253,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$",
        ),
    ]
    """
    The one host this channel may call: a lowercase bare hostname (no scheme, port or path), checked against the egress allow-list at send time.
    """
    endpoint_credential: KeyVaultSecretReference | None = None
    """
    Key Vault secret holding the endpoint URL or transport settings. Null only when local_sink is true.
    """
    hmac_credential: credential_reference.CredentialReference | None = None
    """
    Key Vault secret holding the webhook signing material. Required (non-null) for kind webhook unless local_sink.
    """
    local_sink: StrictBool | None = False
    """
    Deliver to local_sink_url instead of the vaulted endpoint. Core refuses it unless NS_ENV=local (PRP-107 clarification 7).
    """
    local_sink_url: LocalSinkUrl | None = None
    """
    Plain-HTTP loopback or compose-service URL with no query string or userinfo. Present when and only when local_sink is true.
    """
    enabled: StrictBool
