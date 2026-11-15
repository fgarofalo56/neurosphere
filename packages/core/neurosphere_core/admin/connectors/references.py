"""Credential references of connector configuration (PRP-42): checked, never resolved here.

A connector holds a pointer to its credential, never the credential (A7): either an Azure Key
Vault secret URI on the deployment's own cloud or the client id of a user-assigned managed
identity. This module checks the shape of a reference and parses a Key Vault URI into its parts;
reading the secret is the worker's job (``neurosphere_workers.connector_config``).

The vault host is compared as DNS labels with a fixed suffix (``vault.azure.net`` for Commercial,
``vault.usgovcloudapi.net`` for Government): ``evil-vault.azure.net`` and
``vault.azure.net.evil.test`` are refused because their label tails differ, not because of a
substring test. A URI with userinfo, a port, a query or a fragment is refused.

Every refusal is ``invalid_schema`` with a pointer and a value-free message: the URI is never
echoed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, NoReturn
from urllib.parse import urlsplit

from neurosphere_contracts.admin.v1.credential_reference import CredentialReference
from pydantic import ValidationError

from neurosphere_core.admin.models import CloudName
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue

__all__ = [
    "KeyVaultSecretRef",
    "check_credential_reference",
    "key_vault_labels",
    "parse_key_vault_secret",
]

#: DNS-label tail of a vault host, per cloud (compared as labels, never as a substring).
_VAULT_LABELS: Final[Mapping[str, tuple[str, ...]]] = {
    "commercial": ("vault", "azure", "net"),
    "government": ("vault", "usgovcloudapi", "net"),
}
POINTER: Final = "/credential"


@dataclass(frozen=True, slots=True)
class KeyVaultSecretRef:
    """The parts of a Key Vault secret URI. ``host`` is lower-case; ``version`` is optional."""

    host: str
    name: str
    version: str | None

    def __repr__(self) -> str:  # never print the vault or secret name
        return "KeyVaultSecretRef(...)"


def key_vault_labels(cloud: str) -> tuple[str, ...]:
    """The label tail every vault host of ``cloud`` ends with."""
    return _VAULT_LABELS[cloud]


def _refuse(pointer: str, detail: str, *, reason: str = "credential_reference_invalid") -> NoReturn:
    raise InvalidSchemaError(
        "credential reference is invalid",
        errors=[ValidationIssue(pointer, detail)],
        reason=reason,
    )


def parse_key_vault_secret(
    uri: str, cloud: str, *, pointer: str = f"{POINTER}/secret_uri"
) -> KeyVaultSecretRef:
    """``uri`` as a secret on ``cloud``'s vault suffix, else ``invalid_schema`` (value-free)."""
    try:
        parts = urlsplit(uri)
        port = parts.port
    except ValueError:
        _refuse(pointer, "not a Key Vault secret identifier")
    if parts.scheme != "https" or not parts.hostname:
        _refuse(pointer, "a Key Vault secret identifier is an https URL")
    if parts.username is not None or parts.password is not None or port is not None:
        _refuse(pointer, "a Key Vault secret identifier carries no userinfo or port")
    if parts.query or parts.fragment:
        _refuse(pointer, "a Key Vault secret identifier carries no query or fragment")
    labels = tuple(parts.hostname.lower().split("."))
    tail = _VAULT_LABELS[cloud]
    if len(labels) != len(tail) + 1 or labels[1:] != tail or not labels[0]:
        _refuse(pointer, "the vault is not on the deployment cloud", reason="cross_cloud")
    segments = parts.path.split("/")
    if len(segments) not in (3, 4) or segments[0] != "" or segments[1] != "secrets":
        _refuse(pointer, "not a Key Vault secret identifier")
    version = segments[3] if len(segments) == 4 else None
    return KeyVaultSecretRef(host=parts.hostname.lower(), name=segments[2], version=version)


def check_credential_reference(
    reference: CredentialReference | Mapping[str, Any], cloud: CloudName
) -> CredentialReference:
    """``reference`` validated for ``cloud``: the member its kind needs and nothing else.

    ``key_vault_secret`` needs ``secret_uri`` on the cloud's vault suffix; ``managed_identity``
    needs ``managed_identity_client_id`` only. Returns the parsed model.
    """
    if isinstance(reference, CredentialReference):
        model = reference
    else:
        try:
            model = CredentialReference.model_validate(reference)
        except ValidationError as exc:
            raise InvalidSchemaError(
                "credential reference is invalid",
                errors=[
                    ValidationIssue(POINTER + "".join(f"/{p}" for p in err["loc"]), err["type"])
                    for err in exc.errors(include_input=False, include_url=False)
                ],
                reason="credential_reference_invalid",
            ) from None
    if model.kind == "key_vault_secret":
        if model.secret_uri is None or model.managed_identity_client_id is not None:
            _refuse(POINTER, "key_vault_secret needs secret_uri and nothing else")
        parse_key_vault_secret(model.secret_uri, cloud)
    elif model.managed_identity_client_id is None or model.secret_uri is not None:
        _refuse(POINTER, "managed_identity needs managed_identity_client_id only")
    return model
