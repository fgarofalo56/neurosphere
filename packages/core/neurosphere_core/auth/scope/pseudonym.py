"""Pseudonymous principal ids (PRP-06 C15).

``pseudonym = "p-" + HMAC-SHA256(key, tenant_id + ":" + object_id)`` in lowercase hex. The key is
resolved from a vault by the caller (managed identity in production) and injected as a
``PseudonymKey``; it is never read from a file here, and neither the key material nor the raw
object id is ever logged, rendered by ``repr`` or placed in an exception message. The ``:``
separator keeps the input unambiguous even though tenant ids are fixed-length GUIDs.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Final, Literal, NoReturn

from neurosphere_core.cloud import CloudName

__all__ = ["MIN_KEY_BYTES", "PrincipalKind", "PrincipalPseudonymizer", "PseudonymKey"]

MIN_KEY_BYTES: Final = 32

# A Key Vault secret reference on the deployment's own cloud (Commercial or Government).
_VAULT_REFERENCE_RE: Final = re.compile(
    r"https://[a-z0-9-]{3,24}\.vault\.(azure\.net|usgovcloudapi\.net)"
    r"/secrets/[A-Za-z0-9-]{1,127}(/[0-9a-f]{32})?"
)
_SEGMENT_RE: Final = re.compile(r"[a-z0-9._-]{1,128}")

PrincipalKind = Literal["user", "service_principal"]
_TYPE_SEGMENT: Final[dict[PrincipalKind, str]] = {
    "user": "person",
    "service_principal": "principal",
}


class PseudonymKey:
    """HMAC key material plus the vault reference it was resolved from. Opaque by design."""

    __slots__ = ("_material", "_reference")

    def __init__(self, material: bytes, *, reference: str) -> None:
        if not isinstance(material, bytes) or len(material) < MIN_KEY_BYTES:
            raise ValueError(f"pseudonym key must be at least {MIN_KEY_BYTES} bytes")
        if _VAULT_REFERENCE_RE.fullmatch(reference) is None:
            raise ValueError("pseudonym key reference must be a Key Vault secret URI")
        self._material = material
        self._reference = reference

    @property
    def reference(self) -> str:
        return self._reference

    def digest(self, message: bytes) -> str:
        return hmac.new(self._material, message, hashlib.sha256).hexdigest()

    def __repr__(self) -> str:
        return f"PseudonymKey(reference={self._reference!r})"

    __str__ = __repr__

    def __reduce__(self) -> NoReturn:
        raise TypeError("PseudonymKey cannot be pickled")

    def __copy__(self) -> NoReturn:
        raise TypeError("PseudonymKey cannot be copied")

    def __deepcopy__(self, memo: object) -> NoReturn:
        raise TypeError("PseudonymKey cannot be copied")


class PrincipalPseudonymizer:
    """Maps (tenant id, object id) to a stable pseudonym and canonical principal id."""

    __slots__ = ("_key",)

    def __init__(self, key: PseudonymKey) -> None:
        if not isinstance(key, PseudonymKey):
            raise TypeError("expected a PseudonymKey resolved from a vault reference")
        self._key = key

    def pseudonym(self, tenant_id: str, object_id: str) -> str:
        if not tenant_id or not object_id:
            raise ValueError("tenant_id and object_id are required")
        return "p-" + self._key.digest(f"{tenant_id}:{object_id}".encode())

    def principal_id(
        self,
        *,
        cloud: CloudName,
        customer_id: str,
        tenant_id: str,
        object_id: str,
        kind: PrincipalKind,
    ) -> str:
        """Canonical id ``<cloud>:<customer>:entra:<person|principal>:<pseudonym>``."""
        if _SEGMENT_RE.fullmatch(customer_id) is None:
            raise ValueError("customer_id is not a canonical id segment")
        pseudonym = self.pseudonym(tenant_id, object_id)
        return f"{CloudName(cloud).value}:{customer_id}:entra:{_TYPE_SEGMENT[kind]}:{pseudonym}"

    def __repr__(self) -> str:
        return f"PrincipalPseudonymizer(key={self._key!r})"
