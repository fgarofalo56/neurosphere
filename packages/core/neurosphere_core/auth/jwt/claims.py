"""``VerifiedClaims``: the only token-derived object scope derivation (item 2) may read.

It is built exclusively by ``JwtValidator`` after signature, issuer, audience, tenant and
lifetime checks pass. It deliberately carries no name, UPN or email claims (pseudonymization is
item 2's job, and those claims are not needed for authorization), and no raw token material.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from neurosphere_core.auth.jwt.config import TokenVersion
from neurosphere_core.cloud import CloudName

MAX_LIST_CLAIM_ITEMS = 256


class VerifiedClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    issuer_kind: Literal["entra", "dev"]
    cloud: CloudName
    issuer: str = Field(min_length=1, max_length=512)
    audience: str = Field(min_length=1, max_length=512)
    tenant_id: str = Field(min_length=36, max_length=36)
    object_id: str = Field(min_length=1, max_length=128)
    subject: str = Field(min_length=1, max_length=256)
    token_version: TokenVersion
    issued_at: AwareDatetime
    not_before: AwareDatetime
    expires_at: AwareDatetime
    client_app_id: str | None = Field(default=None, min_length=1, max_length=128)
    identity_type: Literal["user", "app"] | None = None
    roles: tuple[str, ...] = Field(default=(), max_length=MAX_LIST_CLAIM_ITEMS)
    scopes: tuple[str, ...] = Field(default=(), max_length=MAX_LIST_CLAIM_ITEMS)
    groups: tuple[str, ...] = Field(default=(), max_length=MAX_LIST_CLAIM_ITEMS)

    def is_expired_at(self, now: datetime) -> bool:
        return now >= self.expires_at
