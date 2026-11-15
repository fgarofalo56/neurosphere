"""Build the existing connector settings classes from a stored ``ConnectorConfig`` (PRP-42).

The three settings classes read ``NS_*`` variables. A stored config must neither inherit a
variable the operator left set nor silently ignore one of its own fields, so each class is
subclassed here with ``settings_customise_sources`` reduced to the init source: the object is
built from the stored fields and field defaults only (a stored value wins, and an env
``NS_API_BASE_URL`` does not leak in). The subclasses are real ``GatewayPollSettings`` /
``FoundryDiscoverySettings`` / ``BillingExportSettings``, so the role builders and every check
they already make run unchanged.

``*_problem`` functions return the first ``(pointer, reason)`` a role builder would refuse the
settings for (the same reason codes as the factory's ``RoleConfigError``), so the API refuses at
creation time what the worker would refuse at start (a partial config is a 422, never saved).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Final

from neurosphere_connector_foundry import project_endpoint
from neurosphere_contracts.admin.v1.connector_config import ConnectorConfig
from neurosphere_core.cloud import CloudName
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue
from pydantic import SecretStr, ValidationError
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from neurosphere_workers.ingestion.billing_export import BillingExportSettings
from neurosphere_workers.ingestion.foundry_discovery import FoundryDiscoverySettings
from neurosphere_workers.ingestion.gateway_poll import GatewayPollSettings

__all__ = [
    "ALLOWED_SETTINGS",
    "StoredBillingExportSettings",
    "StoredFoundryDiscoverySettings",
    "StoredGatewayPollSettings",
    "billing_export_problem",
    "build_billing_export",
    "build_foundry_discovery",
    "build_gateway_poll",
    "foundry_discovery_problem",
    "gateway_poll_problem",
    "refuse",
]

#: Setting keys a stored config of each kind may carry (anything else is a 422).
ALLOWED_SETTINGS: Final[Mapping[str, frozenset[str]]] = {
    "gateway_poll": frozenset(
        {
            "interval_seconds",
            "window_seconds",
            "lookback_seconds",
            "allow_unverified_government",
            "producer_id",
            "source_id",
            "batch_size",
            "metrics_app_id",
            "api_base_url",
            "managed_identity_client_id",
        }
    ),
    "foundry_discovery": frozenset({"projects", "interval_seconds", "max_items", "max_pages"}),
    "billing_export": frozenset(
        {
            "storage_account_url",
            "container",
            "manifest_blob",
            "basis",
            "interval_seconds",
            "producer_id",
            "source_id",
            "batch_size",
            "api_base_url",
            "managed_identity_client_id",
        }
    ),
    "otel": frozenset({"producer_id", "source_id"}),
}
_GUID: Final = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}")


def _init_only(
    settings_cls: type[BaseSettings],
    init_settings: PydanticBaseSettingsSource,
    env_settings: PydanticBaseSettingsSource,
    dotenv_settings: PydanticBaseSettingsSource,
    file_secret_settings: PydanticBaseSettingsSource,
) -> tuple[PydanticBaseSettingsSource, ...]:
    return (init_settings,)


class StoredGatewayPollSettings(GatewayPollSettings):
    """``GatewayPollSettings`` built from init arguments only (no environment)."""

    #: Client id of the user-assigned identity the Key Vault read uses (an identifier).
    managed_identity_client_id: str | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return _init_only(
            settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
        )


class StoredFoundryDiscoverySettings(FoundryDiscoverySettings):
    """``FoundryDiscoverySettings`` built from init arguments only (no environment)."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return _init_only(
            settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
        )


class StoredBillingExportSettings(BillingExportSettings):
    """``BillingExportSettings`` built from init arguments only (no environment)."""

    #: Client id of the user-assigned identity the blob and Key Vault reads use.
    managed_identity_client_id: str | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return _init_only(
            settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
        )


def refuse(pointer: str, reason: str) -> InvalidSchemaError:
    """A value-free 422 with a field pointer and a machine reason."""
    return InvalidSchemaError(
        "connector configuration is invalid",
        errors=[ValidationIssue(pointer, reason)],
        reason=reason,
    )


def _plain(value: Any) -> Any:
    return getattr(value, "root", value)


def _values(config: ConnectorConfig) -> dict[str, Any]:
    allowed = ALLOWED_SETTINGS[config.connector_kind]
    values: dict[str, Any] = {}
    for key, value in config.settings.items():
        if key not in allowed:
            raise refuse(f"/settings/{key}", "connector_setting_unknown")
        values[key] = _plain(value)
    client_id = values.get("managed_identity_client_id")
    if client_id is not None and not _GUID.fullmatch(str(client_id)):
        raise refuse("/settings/managed_identity_client_id", "connector_setting_invalid")
    return values


def _construct[S: BaseSettings](model: type[S], values: dict[str, Any], prefix: str) -> S:
    try:
        return model(**values)
    except ValidationError as exc:
        raise InvalidSchemaError(
            "connector configuration is invalid",
            errors=[
                ValidationIssue(prefix + "".join(f"/{p}" for p in err["loc"]), str(err["type"]))
                for err in exc.errors(include_input=False, include_url=False)
            ],
            reason="connector_setting_invalid",
        ) from None


def _domains(config: ConnectorConfig) -> str:
    return ",".join(d.root for d in config.domain_ids)


def _single_domain(config: ConnectorConfig) -> str:
    if len(config.domain_ids) != 1:
        raise refuse("/domain_ids", f"{config.connector_kind}_single_domain_required")
    return config.domain_ids[0].root


def build_gateway_poll(
    config: ConnectorConfig, *, secret: SecretStr | None = None
) -> StoredGatewayPollSettings:
    values = _values(config)
    values["domain_ids"] = _domains(config)
    if secret is not None:
        values["producer_secret"] = secret
    return _construct(StoredGatewayPollSettings, values, "/settings")


def build_foundry_discovery(config: ConnectorConfig) -> StoredFoundryDiscoverySettings:
    values = _values(config)
    values["domain_id"] = _single_domain(config)
    return _construct(StoredFoundryDiscoverySettings, values, "/settings")


def build_billing_export(
    config: ConnectorConfig, *, secret: SecretStr | None = None
) -> StoredBillingExportSettings:
    values = _values(config)
    values["domain_id"] = _single_domain(config)
    if secret is not None:
        values["producer_secret"] = secret
    return _construct(StoredBillingExportSettings, values, "/settings")


def gateway_poll_problem(settings: GatewayPollSettings) -> tuple[str, str] | None:
    """First refusal ``build_gateway_poll`` (the role factory) would raise, as (pointer, reason)."""
    if not settings.domains:
        return "/domain_ids", "gateway_poll_domain_ids_missing"
    if settings.api_base_url is None:
        return "/settings/api_base_url", "gateway_poll_api_base_url_missing"
    return None


def foundry_discovery_problem(
    settings: FoundryDiscoverySettings, cloud: CloudName
) -> tuple[str, str] | None:
    if not settings.project_pairs_raw:
        return "/settings/projects", "foundry_discovery_projects_missing"
    if settings.domain_id is None or not settings.domain_id_valid:
        return "/domain_ids", "foundry_discovery_domain_id_invalid"
    try:
        projects = settings.parse_projects()
        for resource, project in projects:
            project_endpoint(cloud, resource, project)
    except ValueError:
        return "/settings/projects", "foundry_discovery_projects_invalid"
    return None


def billing_export_problem(
    settings: BillingExportSettings, cloud: CloudName
) -> tuple[str, str] | None:
    checks = (
        ("storage_account_url", settings.storage_account_url),
        ("container", settings.container),
        ("manifest_blob", settings.manifest_blob),
        ("domain_id", settings.domain_id),
        ("api_base_url", settings.api_base_url),
    )
    for name, value in checks:
        if value is None:
            pointer = "/domain_ids" if name == "domain_id" else f"/settings/{name}"
            return pointer, f"billing_export_{name}_missing"
    if not settings.domain_id_valid:
        return "/domain_ids", "billing_export_domain_id_invalid"
    if not settings.storage_url_valid:
        return "/settings/storage_account_url", "billing_export_storage_account_url_invalid"
    if cloud is not CloudName.COMMERCIAL:
        return "/connector_kind", "billing_export_cloud_unsupported"
    return None
