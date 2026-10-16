"""Producer authentication for the ingest edge (decision C2).

The Event Hubs emulator has no Entra, so identity is enforced here: a producer presents
``Authorization: Bearer <producer_id>.<secret>``; the edge hashes the secret with SHA-256 and
compares it to the registered hash in constant time. The registry stores hashes only.

Seam for later: Entra-token producer auth is out of scope for this item. To add it, implement
another authenticator that returns a :class:`ProducerRegistration` (the ``Authenticator``
protocol below) and pass it to the service. This module deliberately does not import the
PRP-06 modules (``neurosphere_api.authz``, ``neurosphere_core.auth``).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Protocol

from neurosphere_core.errors import UnauthorizedError
from pydantic import BaseModel, ConfigDict, Field

ObservationKind = Literal["gateway", "application", "billing"]
_SECRET_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PRODUCER_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


class ProducerRegistration(BaseModel):
    """What a producer is allowed to publish. ``secret_sha256`` is a hash, never a secret."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    producer_id: str = Field(pattern=_PRODUCER_ID.pattern)
    secret_sha256: str = Field(pattern=_SECRET_SHA256.pattern)
    customer_id: str = Field(min_length=1, max_length=256)
    cloud: Literal["commercial", "government"]
    # Allowed source_id -> how that source's data is observed.
    sources: Mapping[str, ObservationKind] = Field(min_length=1)

    @property
    def allowed_source_ids(self) -> frozenset[str]:
        return frozenset(self.sources)


class ProducerRegistry(Protocol):
    def get(self, producer_id: str) -> ProducerRegistration | None: ...


class StaticProducerRegistry:
    """In-memory registry, loaded from a JSON file or built directly."""

    def __init__(self, registrations: list[ProducerRegistration]) -> None:
        self._by_id: dict[str, ProducerRegistration] = {}
        for reg in registrations:
            if reg.producer_id in self._by_id:
                raise ValueError(f"duplicate producer_id: {reg.producer_id}")
            self._by_id[reg.producer_id] = reg

    @classmethod
    def from_file(cls, path: Path) -> StaticProducerRegistry:
        """File shape: ``{"producers": [<ProducerRegistration JSON>, ...]}``."""
        doc = json.loads(path.read_text(encoding="utf-8"))
        return cls([ProducerRegistration.model_validate(p) for p in doc["producers"]])

    def get(self, producer_id: str) -> ProducerRegistration | None:
        return self._by_id.get(producer_id)


class Authenticator(Protocol):
    def authenticate(self, authorization: str | None) -> ProducerRegistration: ...


# Compared against when the producer is unknown so lookup misses cost the same as bad secrets.
_DUMMY_HASH = hash_secret("unknown-producer")


class RegisteredCredentialAuthenticator:
    def __init__(self, registry: ProducerRegistry) -> None:
        self._registry = registry

    def authenticate(self, authorization: str | None) -> ProducerRegistration:
        if not authorization:
            raise UnauthorizedError("Producer credential required.")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise UnauthorizedError("Producer credential required.")
        producer_id, sep, secret = token.strip().partition(".")
        registration = self._registry.get(producer_id) if sep and secret else None
        expected = registration.secret_sha256 if registration else _DUMMY_HASH
        presented = hash_secret(secret)
        ok = hmac.compare_digest(presented.encode("ascii"), expected.encode("ascii"))
        if registration is None or not ok:
            raise UnauthorizedError("Producer credential rejected.")
        return registration
