"""Key Vault key wrap and unwrap over REST with the workload identity (PRP-102 item 3).

Verified facts (``docs/runbooks/interaction-audit.md`` "Verification", U-1):
``POST https://<vault>/keys/<name>/<version>/wrapkey?api-version=2025-07-01`` and ``.../unwrapkey``
with ``{"alg": "RSA-OAEP-256", "value": <base64url>}``; the answer is ``{"kid", "value"}``.
``key-version`` is a required path segment, so a KEK URI without a version is resolved once via
Get Key (``GET https://<vault>/keys/<name>``, answer ``key.kid``). Unwrap always uses the version
recorded in the wrapped key, which is how old key versions keep unwrapping after rotation.

Pattern: ``services/workers/neurosphere_workers/connector_config/keyvault.py`` (no vendor SDK,
host check per cloud before any token, request-URL log filter). The vault host must be a
DNS-label match for the deployment cloud's suffix; anything else raises ``key_host_refused`` and
the token provider is never called. Every other failure (non-200 including 429, timeout,
transport error, malformed answer, token failure) raises ``key_wrap_unavailable``; there is no
retry loop here, callers decide whether to retry with backoff. Nothing is logged: no vault host,
key name, key identifier or key material.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, TypeVar
from urllib.parse import urlsplit

import httpx

from neurosphere_core.cloud import CloudName, profile_for
from neurosphere_core.crypto.envelope import WrappedKey
from neurosphere_core.crypto.errors import (
    CONTENT_INTEGRITY_FAILED,
    KEY_HOST_REFUSED,
    KEY_WRAP_UNAVAILABLE,
    EnvelopeError,
    EnvelopeReason,
    without_context,
)

__all__ = [
    "API_VERSION",
    "VAULT_SUFFIXES",
    "WRAP_ALGORITHM",
    "KeyVaultKeyWrapper",
    "TokenProvider",
    "default_key_vault_token_provider",
]

API_VERSION: Final = "2025-07-01"
WRAP_ALGORITHM: Final = "RSA-OAEP-256"
VAULT_SUFFIXES: Final = {
    CloudName.COMMERCIAL: ".vault.azure.net",
    CloudName.GOVERNMENT: ".vault.usgovcloudapi.net",
}
_SCOPES: Final = {
    CloudName.COMMERCIAL: "https://vault.azure.net/.default",
    CloudName.GOVERNMENT: "https://vault.usgovcloudapi.net/.default",
}
_VAULT_LABEL: Final = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_KEY_NAME: Final = re.compile(r"^[A-Za-z0-9-]{1,127}$")
_KEY_VERSION: Final = re.compile(r"^[0-9A-Fa-f]{32}$")
_B64: Final = re.compile(r"^[A-Za-z0-9+/_-]*={0,2}$")

TokenProvider = Callable[[], Awaitable[str]]
_T = TypeVar("_T")


class _DropKeyVaultKeyRecords(logging.Filter):
    """httpx logs every request URL; a Key Vault key URL (vault, key name, version) never leaves."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return False
        if "/keys/" in message:
            return False
        return not any(suffix in message for suffix in VAULT_SUFFIXES.values())


_FILTER: Final = _DropKeyVaultKeyRecords()
# httpx logs on "httpx" itself; httpcore logs connection hosts on its child loggers. Filters on a
# logger apply only to records created on that logger, so each name gets the filter.
for _name in (
    "httpx",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
):
    logging.getLogger(_name).addFilter(_FILTER)


def default_key_vault_token_provider(
    cloud: CloudName, *, client_id: str | None = None
) -> TokenProvider:
    """``DefaultAzureCredential`` (workload identity) with the cloud's Key Vault scope."""
    scope = _SCOPES[cloud]
    authority = profile_for(cloud).login_host

    async def provide() -> str:
        from azure.identity import DefaultAzureCredential

        options: dict[str, Any] = {"authority": authority}
        if client_id is not None:
            options["managed_identity_client_id"] = client_id
        credential = DefaultAzureCredential(**options)
        try:
            access = await asyncio.to_thread(credential.get_token, scope)
        finally:
            credential.close()
        return access.token

    return provide


@dataclass(frozen=True, slots=True)
class _KeyRef:
    host: str
    name: str
    version: str | None

    def same_key(self, other: _KeyRef) -> bool:
        return self.host == other.host and self.name.lower() == other.name.lower()

    def versioned_id(self) -> str:
        if self.version is None:
            raise EnvelopeError(KEY_WRAP_UNAVAILABLE)
        return f"https://{self.host}/keys/{self.name}/{self.version}"


def _parse_key_uri(uri: object, cloud: CloudName) -> _KeyRef:
    """``https://<vault><suffix>/keys/<name>[/<version>]``; else ``key_host_refused``."""
    if not isinstance(uri, str) or not uri or not uri.isascii() or not uri.isprintable():
        raise EnvelopeError(KEY_HOST_REFUSED)
    try:
        parts = urlsplit(uri)
        port = parts.port
    except ValueError:
        raise EnvelopeError(KEY_HOST_REFUSED) from None
    if (
        parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or "@" in parts.netloc
        or port is not None
        or parts.query
        or parts.fragment
        or uri.endswith(("?", "#"))
    ):
        raise EnvelopeError(KEY_HOST_REFUSED)
    host = parts.netloc.lower()
    suffix = VAULT_SUFFIXES[cloud]
    if host != (parts.hostname or "") or not host.endswith(suffix):
        raise EnvelopeError(KEY_HOST_REFUSED)
    if not _VAULT_LABEL.fullmatch(host[: -len(suffix)]):
        raise EnvelopeError(KEY_HOST_REFUSED)
    segments = parts.path.split("/")
    # "/keys/<name>" -> ["", "keys", name]; "/keys/<name>/<version>" adds one segment.
    if len(segments) not in (3, 4) or segments[0] != "" or segments[1] != "keys":
        raise EnvelopeError(KEY_HOST_REFUSED)
    if not _KEY_NAME.fullmatch(segments[2]):
        raise EnvelopeError(KEY_HOST_REFUSED)
    version: str | None = None
    if len(segments) == 4:
        if not _KEY_VERSION.fullmatch(segments[3]):
            raise EnvelopeError(KEY_HOST_REFUSED)
        version = segments[3]
    return _KeyRef(host=host, name=segments[2], version=version)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(text: object) -> bytes:
    """Accept base64url or standard base64, padded or not (the published sample shows both)."""
    if not isinstance(text, str) or not text or not _B64.fullmatch(text):
        raise EnvelopeError(KEY_WRAP_UNAVAILABLE)
    normalized = text.rstrip("=").replace("-", "+").replace("_", "/")
    normalized += "=" * (-len(normalized) % 4)
    try:
        decoded = base64.b64decode(normalized, validate=True)
    except (binascii.Error, ValueError):
        raise EnvelopeError(KEY_WRAP_UNAVAILABLE) from None
    if not decoded:
        raise EnvelopeError(KEY_WRAP_UNAVAILABLE)
    return decoded


class KeyVaultKeyWrapper:
    """Wraps data keys with an RSA Key Vault key (``RSA-OAEP-256``); holds no key material."""

    def __init__(
        self,
        kek_uri: str,
        *,
        cloud: CloudName,
        token_provider: TokenProvider,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._cloud = CloudName(cloud)
        self._configured = _parse_key_uri(kek_uri, self._cloud)
        self._resolved: _KeyRef | None = (
            self._configured if self._configured.version is not None else None
        )
        self._token = token_provider
        self._transport = transport
        self._timeout = timeout_seconds

    @property
    def key_id(self) -> str:
        """The versioned key identifier once known, otherwise the configured unversioned one."""
        ref = self._resolved or self._configured
        if ref.version is None:
            return f"https://{ref.host}/keys/{ref.name}"
        return ref.versioned_id()

    async def wrap(self, data_key: bytes) -> WrappedKey:
        return await without_context(self._checked_wrap(data_key))

    async def unwrap(self, wrapped: WrappedKey) -> bytes:
        return await without_context(self._checked_unwrap(wrapped))

    async def _checked_wrap(self, data_key: bytes) -> WrappedKey:
        if not isinstance(data_key, bytes) or not data_key:
            raise EnvelopeError(KEY_WRAP_UNAVAILABLE)
        return await self._bounded(self._wrap(data_key))

    async def _checked_unwrap(self, wrapped: WrappedKey) -> bytes:
        if not isinstance(wrapped, WrappedKey) or wrapped.algorithm != WRAP_ALGORITHM:
            raise EnvelopeError(CONTENT_INTEGRITY_FAILED)
        try:
            recorded = _parse_key_uri(wrapped.key_id, self._cloud)
        except EnvelopeError:
            raise EnvelopeError(CONTENT_INTEGRITY_FAILED) from None
        if recorded.version is None or not recorded.same_key(self._configured):
            raise EnvelopeError(CONTENT_INTEGRITY_FAILED)
        if not isinstance(wrapped.value, bytes) or not wrapped.value:
            raise EnvelopeError(CONTENT_INTEGRITY_FAILED)
        return await self._bounded(self._unwrap(recorded, wrapped.value))

    async def _bounded(self, operation: Awaitable[_T]) -> _T:
        try:
            return await asyncio.wait_for(operation, self._timeout + 5.0)
        except EnvelopeError:
            raise
        except Exception:
            # Timeouts, transport errors and token failures: one code, no detail.
            raise EnvelopeError(KEY_WRAP_UNAVAILABLE) from None

    async def _wrap(self, data_key: bytes) -> WrappedKey:
        async with self._client() as client:
            ref = self._resolved
            if ref is None:
                ref = await self._resolve(client)
            body = await self._post(client, ref, "wrapkey", data_key)
        kid = body.get("kid")
        try:
            answered = _parse_key_uri(kid, self._cloud)
        except EnvelopeError:
            raise EnvelopeError(KEY_WRAP_UNAVAILABLE) from None
        if answered.version is None or not answered.same_key(self._configured):
            raise EnvelopeError(KEY_WRAP_UNAVAILABLE)
        return WrappedKey(
            key_id=answered.versioned_id(),
            algorithm=WRAP_ALGORITHM,
            value=_b64decode(body.get("value")),
        )

    async def _unwrap(self, recorded: _KeyRef, value: bytes) -> bytes:
        async with self._client() as client:
            body = await self._post(
                client, recorded, "unwrapkey", value, rejected=CONTENT_INTEGRITY_FAILED
            )
        return _b64decode(body.get("value"))

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=False,
        )

    async def _headers(self) -> dict[str, str]:
        bearer = await self._token()
        if not isinstance(bearer, str) or not bearer:
            raise EnvelopeError(KEY_WRAP_UNAVAILABLE)
        return {"Authorization": f"Bearer {bearer}"}

    async def _resolve(self, client: httpx.AsyncClient) -> _KeyRef:
        ref = self._configured
        response = await client.get(
            f"https://{ref.host}/keys/{ref.name}",
            params={"api-version": API_VERSION},
            headers=await self._headers(),
        )
        body = _json_object(response)
        bundle = body.get("key")
        if not isinstance(bundle, dict):
            raise EnvelopeError(KEY_WRAP_UNAVAILABLE)
        try:
            resolved = _parse_key_uri(bundle.get("kid"), self._cloud)
        except EnvelopeError:
            raise EnvelopeError(KEY_WRAP_UNAVAILABLE) from None
        if resolved.version is None or not resolved.same_key(ref):
            raise EnvelopeError(KEY_WRAP_UNAVAILABLE)
        self._resolved = resolved
        return resolved

    async def _post(
        self,
        client: httpx.AsyncClient,
        ref: _KeyRef,
        operation: str,
        value: bytes,
        *,
        rejected: EnvelopeReason = KEY_WRAP_UNAVAILABLE,
    ) -> dict[str, Any]:
        response = await client.post(
            f"{ref.versioned_id()}/{operation}",
            params={"api-version": API_VERSION},
            headers=await self._headers(),
            json={"alg": WRAP_ALGORITHM, "value": _b64encode(value)},
        )
        if response.status_code == 400:
            # Key Vault refused the value or key version as given; on unwrap that is tampering.
            raise EnvelopeError(rejected)
        return _json_object(response)


def _json_object(response: httpx.Response) -> dict[str, Any]:
    if response.status_code != 200:
        raise EnvelopeError(KEY_WRAP_UNAVAILABLE)
    try:
        body = response.json()
    except ValueError:
        raise EnvelopeError(KEY_WRAP_UNAVAILABLE) from None
    if not isinstance(body, dict):
        raise EnvelopeError(KEY_WRAP_UNAVAILABLE)
    return body
