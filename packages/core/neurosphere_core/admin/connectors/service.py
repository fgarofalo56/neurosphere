"""Connector configuration administration over the ``admin_config`` store (PRP-42).

:class:`ConnectorConfigAdmin` validates a :class:`ConnectorConfig` and writes it as an
``admin_config`` document of kind ``connector_config`` whose id is the ``connector_id``. It checks,
before anything is stored:

* the contract and the PRP-65 core rules (``validate_admin_body``: customer, cloud, secret-like
  setting names, vault suffix);
* the credential reference (:func:`check_credential_reference`);
* bounded setting values: a string that is a URL carries no userinfo, query or fragment;
* the per-kind rules, through a :class:`ConnectorKindValidator` the worker package supplies (core
  must not import the workers), so a value the worker would refuse is refused here;
* the producer reference, when the config names a ``producer_id`` (see :meth:`_check_producer`);
* at most one active config per ``connector_kind`` (the worker reads one per kind).

Nothing here logs, and no message echoes a setting value or a reference.
"""

from __future__ import annotations

import builtins
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol
from urllib.parse import urlsplit

from neurosphere_contracts.admin.v1.admin_config_document import AdminConfigDocument
from neurosphere_contracts.admin.v1.connector_config import ConnectorConfig
from neurosphere_contracts.admin.v1.producer_record import ProducerRecord
from pydantic import BaseModel

from neurosphere_core.admin.connectors.references import check_credential_reference
from neurosphere_core.admin.models import CloudName, validate_admin_body
from neurosphere_core.admin.store import DEFAULT_LIST_LIMIT, AdminConfigRepository
from neurosphere_core.errors import (
    InvalidSchemaError,
    NotFoundError,
    StaleVersionError,
    ValidationIssue,
)

__all__ = [
    "CONNECTOR_KIND",
    "OBSERVATION_KINDS",
    "ConnectorConfigAdmin",
    "ConnectorKindValidator",
    "ConnectorWrite",
    "KindCheck",
]

CONNECTOR_KIND: Final = "connector_config"
#: Producer source kind each connector kind posts under (``producers.example.json``).
OBSERVATION_KINDS: Final[Mapping[str, str]] = {
    "gateway_poll": "gateway",
    "billing_export": "billing",
    "otel": "application",
}
PRODUCER_NOT_IN_STORE: Final = "producer_not_in_store"


@dataclass(frozen=True, slots=True)
class KindCheck:
    """What a per-kind validator learned: warnings and the producer identity it would post as."""

    warnings: tuple[str, ...] = ()
    producer_id: str | None = None
    source_id: str | None = None


class ConnectorKindValidator(Protocol):
    """Constructs the worker's own settings from ``config``; raises ``InvalidSchemaError``."""

    def __call__(self, config: ConnectorConfig, *, cloud: CloudName) -> KindCheck: ...


@dataclass(frozen=True, slots=True)
class ConnectorWrite:
    """An accepted write: the stored document and non-blocking warning codes."""

    document: AdminConfigDocument
    warnings: tuple[str, ...]


def _issue(pointer: str, detail: str, reason: str) -> InvalidSchemaError:
    return InvalidSchemaError(
        "connector configuration is invalid",
        errors=[ValidationIssue(pointer, detail)],
        reason=reason,
    )


def _check_setting_values(config: ConnectorConfig) -> None:
    for key, value in config.settings.items():
        text = getattr(value, "root", value)
        if not isinstance(text, str) or "://" not in text:
            continue
        pointer = f"/settings/{key}"
        try:
            parts = urlsplit(text)
            parts.port  # noqa: B018 - raises ValueError on a malformed port
        except ValueError:
            raise _issue(pointer, "not a valid URL", "connector_setting_invalid") from None
        if parts.username is not None or parts.password is not None:
            raise _issue(pointer, "a URL carries no userinfo", "connector_setting_invalid")
        if parts.query or parts.fragment:
            raise _issue(pointer, "a URL carries no query or fragment", "connector_setting_invalid")


def _as_config(
    body: Mapping[str, Any] | BaseModel, customer_id: str, cloud: CloudName
) -> ConnectorConfig:
    model = validate_admin_body(CONNECTOR_KIND, body, customer_id=customer_id, cloud=cloud)
    assert isinstance(model, ConnectorConfig)
    return model


class ConnectorConfigAdmin:
    """Create, replace, enable, disable, retire, get and list connector configurations."""

    def __init__(
        self,
        repository: AdminConfigRepository,
        *,
        cloud: CloudName,
        validators: Mapping[str, ConnectorKindValidator],
    ) -> None:
        self._repository = repository
        self._cloud: CloudName = cloud
        self._validators = dict(validators)

    # -- validation ---------------------------------------------------------------------------

    async def _validate(
        self, customer_id: str, body: Mapping[str, Any] | BaseModel
    ) -> tuple[ConnectorConfig, tuple[str, ...]]:
        config = _as_config(body, customer_id, self._cloud)
        _check_setting_values(config)
        if config.credential is None:
            # The contract allows null, but the shipped Cosmos twin drops null members on write
            # and then cannot read the row back (PRP-65 follow-up), so a null is refused here.
            raise _issue(
                "/credential", "a credential reference is required", "connector_credential_required"
            )
        check_credential_reference(config.credential, self._cloud)
        validator = self._validators.get(config.connector_kind)
        if validator is None:
            raise _issue("/connector_kind", "no validator for this kind", "connector_kind_unknown")
        check = validator(config, cloud=self._cloud)
        warnings = list(check.warnings)
        if "producer_id" in config.settings:
            warnings.extend(await self._check_producer(customer_id, config, check))
        return config, tuple(dict.fromkeys(warnings))

    async def _check_producer(
        self, customer_id: str, config: ConnectorConfig, check: KindCheck
    ) -> builtins.list[str]:
        """A stored producer must match cloud, source id and source kind; absent is a warning."""
        if check.producer_id is None:
            return []
        document = await self._repository.get(customer_id, "producer", check.producer_id)
        if document is None or document.status == "retired":
            return [PRODUCER_NOT_IN_STORE]
        producer = document.body
        if not isinstance(producer, ProducerRecord):
            return [PRODUCER_NOT_IN_STORE]
        pointer = "/settings/producer_id"
        if producer.cloud.root != self._cloud:
            raise _issue(pointer, "the producer is on another cloud", "cross_cloud")
        sources = {s.source_id: s.observation_kind for s in producer.sources}
        if check.source_id is None or check.source_id not in sources:
            raise _issue(
                "/settings/source_id", "the producer has no such source", "producer_source_missing"
            )
        expected = OBSERVATION_KINDS.get(config.connector_kind)
        if expected is not None and sources[check.source_id] != expected:
            raise _issue(
                "/settings/source_id",
                "the producer source has the wrong kind",
                "producer_source_kind_mismatch",
            )
        return []

    async def _one_per_kind(self, customer_id: str, kind: str, config_id: str) -> None:
        for doc in await self._repository.list_by_kind(customer_id, CONNECTOR_KIND):
            body = doc.body
            if (
                isinstance(body, ConnectorConfig)
                and body.connector_kind == kind
                and doc.id.root != config_id
            ):
                raise StaleVersionError(
                    "an active configuration of this connector kind exists",
                    reason="connector_kind_exists",
                )

    # -- writes -------------------------------------------------------------------------------

    async def create(
        self, customer_id: str, body: Mapping[str, Any] | BaseModel, *, updated_by: str
    ) -> ConnectorWrite:
        config, warnings = await self._validate(customer_id, body)
        await self._one_per_kind(customer_id, config.connector_kind, config.connector_id.root)
        document = await self._repository.create(
            customer_id, CONNECTOR_KIND, config.connector_id.root, config, updated_by=updated_by
        )
        return ConnectorWrite(document, warnings)

    async def replace(
        self,
        customer_id: str,
        config_id: str,
        body: Mapping[str, Any] | BaseModel,
        *,
        if_match: str,
        updated_by: str,
    ) -> ConnectorWrite:
        config, warnings = await self._validate(customer_id, body)
        if config.connector_id.root != config_id:
            raise _issue("/connector_id", "does not match the path", "connector_id_mismatch")
        current = await self._current(customer_id, config_id)
        if current.connector_kind != config.connector_kind:
            raise _issue("/connector_kind", "cannot change", "connector_kind_immutable")
        document = await self._repository.replace(
            customer_id, CONNECTOR_KIND, config_id, config, if_match=if_match, updated_by=updated_by
        )
        return ConnectorWrite(document, warnings)

    async def set_enabled(
        self, customer_id: str, config_id: str, enabled: bool, *, if_match: str, updated_by: str
    ) -> ConnectorWrite:
        current = await self._current(customer_id, config_id)
        changed = current.model_copy(update={"enabled": enabled})
        _config, warnings = await self._validate(customer_id, changed)
        document = await self._repository.replace(
            customer_id,
            CONNECTOR_KIND,
            config_id,
            changed,
            if_match=if_match,
            updated_by=updated_by,
        )
        return ConnectorWrite(document, warnings)

    async def retire(
        self, customer_id: str, config_id: str, *, if_match: str, updated_by: str
    ) -> AdminConfigDocument:
        return await self._repository.retire(
            customer_id, CONNECTOR_KIND, config_id, if_match=if_match, updated_by=updated_by
        )

    # -- reads --------------------------------------------------------------------------------

    async def get(self, customer_id: str, config_id: str) -> AdminConfigDocument:
        document = await self._repository.get(customer_id, CONNECTOR_KIND, config_id)
        if document is None:
            raise NotFoundError("no such connector configuration", reason="connector_not_found")
        return document

    async def _current(self, customer_id: str, config_id: str) -> ConnectorConfig:
        body = (await self.get(customer_id, config_id)).body
        assert isinstance(body, ConnectorConfig)
        return body

    async def list(
        self,
        customer_id: str,
        *,
        connector_kind: str | None = None,
        include_retired: bool = False,
        limit: int = DEFAULT_LIST_LIMIT,
    ) -> builtins.list[AdminConfigDocument]:
        docs = await self._repository.list_by_kind(
            customer_id, CONNECTOR_KIND, include_retired=include_retired, limit=limit
        )
        if connector_kind is None:
            return docs
        return [
            d
            for d in docs
            if isinstance(d.body, ConnectorConfig) and d.body.connector_kind == connector_kind
        ]
