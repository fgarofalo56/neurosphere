"""Principal pseudonym key resolution (PRP-29 C14). The ONE resolver: the API and the operator
grant script (``scripts/sandbox/sbx_grant_operator.py``) both call :func:`resolve_pseudonym_key`,
so ``HMAC(tenant:oid)`` is identical on both sides (otherwise the operator is unknown to the
policy store).

Rules:

* ``NS_AUTH_PSEUDONYM_KEY`` (``SecretStr``) arrives from the platform's Key Vault reference
  (App Service / Helm CSI) together with ``NS_AUTH_PSEUDONYM_KEY_REFERENCE``, the vault secret
  URI ``PseudonymKey`` requires. A key without its reference is refused.
* ``NS_ENV=local`` with no key falls back to a fixed, PUBLIC, NON-SECRET development key under
  the placeholder reference :data:`LOCAL_DEV_PSEUDONYM_KEY_REFERENCE` (no vault of that name is
  ever contacted). Pseudonyms made with it are only meaningful on a local emulator.
* Any other environment without a key is a configuration error; the authz builder reports it
  as a readiness failure (``authz``), never a fallback.

The key material is the UTF-8 encoding of the secret value (at least 32 bytes). Neither the
value nor its length is logged or placed in an error message.
"""

from __future__ import annotations

import hashlib
from typing import Final

from neurosphere_core.auth.scope import PseudonymKey
from neurosphere_core.auth.scope.pseudonym import MIN_KEY_BYTES
from neurosphere_core.errors import InvalidSchemaError, ValidationIssue

from neurosphere_api.runtime.settings import AuthSettings

__all__ = [
    "LOCAL_DEV_PSEUDONYM_KEY_REFERENCE",
    "local_dev_pseudonym_key",
    "resolve_pseudonym_key",
]

#: Documented placeholder: a syntactically valid Key Vault secret URI that names no real
#: secret. It only labels the local development key.
LOCAL_DEV_PSEUDONYM_KEY_REFERENCE: Final = (
    "https://ns-local-dev-only.vault.azure.net/secrets/local-dev-principal-pseudonym-key"
)
# Derived at runtime from a fixed public label, so no key-shaped literal exists in the source.
_LOCAL_DEV_LABEL: Final = b"neurosphere/local-dev/principal-pseudonym/v1"


def local_dev_pseudonym_key() -> PseudonymKey:
    """The fixed public development key (``NS_ENV=local`` only; callers check the env)."""
    return PseudonymKey(
        hashlib.sha256(_LOCAL_DEV_LABEL).digest(), reference=LOCAL_DEV_PSEUDONYM_KEY_REFERENCE
    )


def _error(pointer: str, detail: str, reason: str) -> InvalidSchemaError:
    error = InvalidSchemaError(detail, reason=reason)
    error.errors = (ValidationIssue(pointer, detail),)
    return error


def resolve_pseudonym_key(settings: AuthSettings, *, env: str) -> PseudonymKey:
    """The configured key, the public dev key when ``env == "local"`` and none is configured,
    else ``invalid_schema`` with reason ``pseudonym_key_missing``,
    ``pseudonym_key_reference_missing`` or ``pseudonym_key_invalid``."""
    secret = settings.pseudonym_key
    value = secret.get_secret_value() if secret is not None else ""
    if not value:
        if env == "local":
            return local_dev_pseudonym_key()
        raise _error(
            "/pseudonym_key",
            "NS_AUTH_PSEUDONYM_KEY is required unless NS_ENV=local",
            "pseudonym_key_missing",
        )
    reference = settings.pseudonym_key_reference
    if reference is None:
        raise _error(
            "/pseudonym_key_reference",
            "NS_AUTH_PSEUDONYM_KEY_REFERENCE must name the Key Vault secret of the key",
            "pseudonym_key_reference_missing",
        )
    material = value.encode("utf-8")
    if len(material) < MIN_KEY_BYTES:
        raise _error(
            "/pseudonym_key",
            f"NS_AUTH_PSEUDONYM_KEY must be at least {MIN_KEY_BYTES} bytes",
            "pseudonym_key_invalid",
        )
    try:
        return PseudonymKey(material, reference=reference)
    except ValueError:
        raise _error(
            "/pseudonym_key_reference",
            "NS_AUTH_PSEUDONYM_KEY_REFERENCE must be a Key Vault secret URI",
            "pseudonym_key_invalid",
        ) from None
