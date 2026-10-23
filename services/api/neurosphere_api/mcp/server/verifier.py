"""Bearer-token verification for the MCP resource server (PRP-22 item 1).

:class:`McpTokenVerifier` is the SDK ``TokenVerifier``. It delegates every check (size, shape,
``alg``, ``kid``, signature, issuer, AUDIENCE, tenant, version, lifetime) to the PRP-06
``JwtValidator`` built from the MCP ``JwtConfig`` (MCP audiences only), and returns ``None`` on
any rejection so the SDK answers 401 with a ``WWW-Authenticate`` header that points at the RFC
9728 metadata. Infrastructure failures (JWKS unreachable) are also ``None``: the request is
refused, never allowed.

The RESOURCE check is separate and happens in the SDK (``AuthSettings.validate_token_resource``):
the verifier reports ``AccessToken.resource`` as the MCP resource identifier only when the token's
verified audience is one of the configured MCP audiences, and as the raw audience otherwise. A
validator that was (mis)wired to accept another audience is therefore still refused by the SDK.

No token passthrough: the returned ``AccessToken`` never holds the raw token (``token`` is the
fixed :data:`REDACTED_TOKEN` marker). What downstream code needs is the validator-built
``VerifiedClaims`` (no token material), carried on :class:`McpAccessToken`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Final, Protocol, runtime_checkable

from mcp.server.auth.provider import AccessToken
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.errors import NeuroSphereError

__all__ = [
    "REDACTED_TOKEN",
    "ClaimsValidator",
    "McpAccessToken",
    "McpTokenVerifier",
]

_LOG = logging.getLogger("neurosphere_api.mcp.server")

#: Stored in ``AccessToken.token`` instead of the bearer: the raw token is never retained.
REDACTED_TOKEN: Final = "[redacted]"  # noqa: S105 - a fixed marker, not a credential
_UNIDENTIFIED_CLIENT: Final = "unidentified-client"


@runtime_checkable
class ClaimsValidator(Protocol):
    """The PRP-06 ``JwtValidator`` shape: a raw token in, ``VerifiedClaims`` out, or raise."""

    async def validate(self, token: str | None) -> VerifiedClaims: ...


class McpAccessToken(AccessToken):
    """SDK access token plus the verified claims scope derivation reads. Never rendered."""

    verified: VerifiedClaims


class McpTokenVerifier:
    """``mcp.server.auth.provider.TokenVerifier`` over a PRP-06 validator (MCP audiences)."""

    def __init__(
        self,
        validator: ClaimsValidator,
        *,
        resource_server_url: str,
        resource_audiences: Iterable[str],
    ) -> None:
        audiences = frozenset(resource_audiences)
        if not audiences:
            raise ValueError("resource_audiences must not be empty")
        self._validator = validator
        self._resource = resource_server_url
        self._audiences = audiences

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = await self._validator.validate(token)
        except NeuroSphereError as exc:
            _LOG.info("mcp bearer token rejected", extra={"reason": exc.reason or exc.code})
            return None
        except Exception:
            _LOG.warning("mcp bearer token could not be verified", exc_info=True)
            return None
        if not isinstance(claims, VerifiedClaims):
            return None
        resource = self._resource if claims.audience in self._audiences else claims.audience
        return McpAccessToken(
            token=REDACTED_TOKEN,
            client_id=claims.client_app_id or _UNIDENTIFIED_CLIENT,
            scopes=list(claims.scopes),
            expires_at=int(claims.expires_at.timestamp()),
            resource=resource,
            subject=claims.subject,
            claims={"iss": claims.issuer},
            verified=claims,
        )
