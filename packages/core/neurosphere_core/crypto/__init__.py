"""Envelope encryption for captured interaction content (PRP-102).

AES-256-GCM with a fresh data key per blob, the data key wrapped by a Key Vault key
(:class:`KeyVaultKeyWrapper`) or, under ``NS_ENV=local`` only, a local file key
(:class:`LocalFileKeyWrapper`). Failures raise :class:`EnvelopeError` whose text is one of the
reason codes ``key_wrap_unavailable``, ``content_integrity_failed`` or ``key_host_refused``.
"""

from neurosphere_core.crypto.envelope import (
    ENVELOPE_FORMAT_VERSION,
    Envelope,
    KeyWrapper,
    WrappedKey,
    canonical_aad,
    open_envelope,
    seal,
)
from neurosphere_core.crypto.errors import (
    CONTENT_INTEGRITY_FAILED,
    KEY_HOST_REFUSED,
    KEY_WRAP_UNAVAILABLE,
    EnvelopeError,
    EnvelopeReason,
)
from neurosphere_core.crypto.keyvault import (
    KeyVaultKeyWrapper,
    TokenProvider,
    default_key_vault_token_provider,
)
from neurosphere_core.crypto.local import LOCAL_WRAP_ALGORITHM, LocalFileKeyWrapper

__all__ = [
    "CONTENT_INTEGRITY_FAILED",
    "ENVELOPE_FORMAT_VERSION",
    "KEY_HOST_REFUSED",
    "KEY_WRAP_UNAVAILABLE",
    "LOCAL_WRAP_ALGORITHM",
    "Envelope",
    "EnvelopeError",
    "EnvelopeReason",
    "KeyVaultKeyWrapper",
    "KeyWrapper",
    "LocalFileKeyWrapper",
    "TokenProvider",
    "WrappedKey",
    "canonical_aad",
    "default_key_vault_token_provider",
    "open_envelope",
    "seal",
]
