"""Per-kind validators the admin API runs at creation time (PRP-42).

Each validator constructs the SAME settings class the worker role uses (through ``stored``) and
applies the role builder's own checks, so a value the worker would refuse is a 422 with a field
pointer and nothing is stored. Core cannot import the workers, so the API passes
:data:`VALIDATORS` to ``ConnectorConfigAdmin``.

Credential rules: ``gateway_poll`` and ``billing_export`` post to ingest with a producer secret, so
their credential must be a Key Vault secret reference. ``foundry_discovery`` and ``otel`` need no
secret; they accept a ``managed_identity`` reference, recorded and reported as
``credential_not_applied`` (``foundry_discovery``'s token provider takes no client id; nothing
consumes ``otel`` yet).
"""

from __future__ import annotations

from typing import Final

from neurosphere_contracts.admin.v1.connector_config import ConnectorConfig
from neurosphere_core.admin.connectors import ConnectorKindValidator, KindCheck
from neurosphere_core.admin.models import CloudName as CloudLiteral
from neurosphere_core.cloud import CloudName

from neurosphere_workers.connector_config import stored
from neurosphere_workers.connector_config.stored import refuse

__all__ = ["CREDENTIAL_NOT_APPLIED", "VALIDATORS"]

CREDENTIAL_NOT_APPLIED: Final = "credential_not_applied"


def _require_secret_reference(config: ConnectorConfig) -> None:
    credential = config.credential
    if credential is None or credential.kind != "key_vault_secret":
        raise refuse("/credential", f"{config.connector_kind}_credential_invalid")


def _require_identity_reference(config: ConnectorConfig) -> None:
    credential = config.credential
    if credential is None or credential.kind != "managed_identity":
        raise refuse("/credential", f"{config.connector_kind}_credential_invalid")


def _raise(problem: tuple[str, str] | None) -> None:
    if problem is not None:
        raise refuse(*problem)


def _gateway_poll(config: ConnectorConfig, *, cloud: CloudLiteral) -> KindCheck:
    _require_secret_reference(config)
    settings = stored.build_gateway_poll(config)
    _raise(stored.gateway_poll_problem(settings))
    return KindCheck(producer_id=settings.producer_id, source_id=settings.source_id)


def _foundry_discovery(config: ConnectorConfig, *, cloud: CloudLiteral) -> KindCheck:
    _require_identity_reference(config)
    settings = stored.build_foundry_discovery(config)
    _raise(stored.foundry_discovery_problem(settings, CloudName(cloud)))
    return KindCheck(warnings=(CREDENTIAL_NOT_APPLIED,))


def _billing_export(config: ConnectorConfig, *, cloud: CloudLiteral) -> KindCheck:
    _require_secret_reference(config)
    settings = stored.build_billing_export(config)
    _raise(stored.billing_export_problem(settings, CloudName(cloud)))
    return KindCheck(producer_id=settings.producer_id, source_id=settings.source_id)


def _otel(config: ConnectorConfig, *, cloud: CloudLiteral) -> KindCheck:
    _require_identity_reference(config)
    values = {k: getattr(v, "root", v) for k, v in config.settings.items()}
    for key in values:
        if key not in stored.ALLOWED_SETTINGS["otel"]:
            raise refuse(f"/settings/{key}", "connector_setting_unknown")
    for key in ("producer_id", "source_id"):
        value = values.get(key)
        if not isinstance(value, str) or not 1 <= len(value) <= 128:
            raise refuse(f"/settings/{key}", f"otel_{key}_missing")
    return KindCheck(
        warnings=(CREDENTIAL_NOT_APPLIED,),
        producer_id=str(values["producer_id"]),
        source_id=str(values["source_id"]),
    )


#: ``connector_kind`` -> validator, for ``ConnectorConfigAdmin(validators=...)``.
VALIDATORS: Final[dict[str, ConnectorKindValidator]] = {
    "gateway_poll": _gateway_poll,
    "foundry_discovery": _foundry_discovery,
    "billing_export": _billing_export,
    "otel": _otel,
}
