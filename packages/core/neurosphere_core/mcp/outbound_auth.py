"""Outbound credential port for external MCP servers (no token passthrough, clarification 5).

The client NEVER forwards an inbound user token. If an external server needs a credential, it
comes from an :class:`OutboundCredentialProvider` bound to the registered server (for example a
vault-referenced key or a managed-identity token for that server's own audience). The default is
:class:`NoOutboundCredentials`: no credential at all. Providers receive the registration only,
never the caller's request, token or scope.

Provider output is untrusted input to the HTTP layer: :func:`check_credential_headers` refuses
any header name that is not an RFC 9110 token and any value carrying CR, LF, NUL, another control
character or a non-ASCII character, so a provider (or a vault entry it reads) can never split a
request or smuggle a second header. Messages never echo the header value.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final, Protocol, runtime_checkable

from neurosphere_core.mcp.errors import INVALID_CREDENTIAL_HEADER, invalid
from neurosphere_core.mcp.models import RegisteredServer

__all__ = [
    "MAX_CREDENTIAL_HEADERS",
    "MAX_CREDENTIAL_HEADER_BYTES",
    "NoOutboundCredentials",
    "OutboundCredentialProvider",
    "check_credential_headers",
]

MAX_CREDENTIAL_HEADERS: Final = 8
MAX_CREDENTIAL_HEADER_BYTES: Final = 8192
#: RFC 9110 section 5.6.2 ``token`` (the only legal field-name syntax).
_TOKEN_RE: Final = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
#: RFC 9110 section 5.5 field value: visible ASCII, SP and HTAB, no leading/trailing whitespace.
_VALUE_RE: Final = re.compile(r"^(?:[\x21-\x7e](?:[\x20-\x7e\t]*[\x21-\x7e])?)?$")


@runtime_checkable
class OutboundCredentialProvider(Protocol):
    async def headers_for(self, server: RegisteredServer) -> Mapping[str, str]:
        """Headers carrying the platform's OWN credential for ``server`` (may be empty)."""
        ...


class NoOutboundCredentials:
    """Default provider: external servers receive no credential."""

    async def headers_for(self, server: RegisteredServer) -> Mapping[str, str]:
        return {}


def check_credential_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Syntax-check provider headers; returns them with lowercased names.

    Raises ``invalid_schema`` (``invalid_credential_header``) for a non-string, a name that is
    not an RFC 9110 token (CR, LF, colon, space, non-ASCII...), a value with a control or
    non-ASCII character, duplicate names after lowercasing, or more than
    :data:`MAX_CREDENTIAL_HEADERS` headers / :data:`MAX_CREDENTIAL_HEADER_BYTES` bytes. Which
    names are ALLOWED (``Host`` and friends are not) is the caller's policy.
    """
    if len(headers) > MAX_CREDENTIAL_HEADERS:
        raise invalid(INVALID_CREDENTIAL_HEADER, "too many outbound credential headers")
    checked: dict[str, str] = {}
    total = 0
    for name, value in headers.items():
        if not isinstance(name, str) or not _TOKEN_RE.fullmatch(name):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise invalid(
                INVALID_CREDENTIAL_HEADER, "an outbound credential header name is invalid"
            )
        if not isinstance(value, str) or not _VALUE_RE.fullmatch(value):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise invalid(
                INVALID_CREDENTIAL_HEADER, "an outbound credential header value is invalid"
            )
        lowered = name.lower()
        if lowered in checked:
            raise invalid(INVALID_CREDENTIAL_HEADER, "an outbound credential header is repeated")
        total += len(lowered) + len(value)
        if total > MAX_CREDENTIAL_HEADER_BYTES:
            raise invalid(INVALID_CREDENTIAL_HEADER, "outbound credential headers are too large")
        checked[lowered] = value
    return checked
