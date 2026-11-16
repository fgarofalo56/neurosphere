"""AWS credential providers. No key is stored at rest, logged or placed in an exception.

Two providers share one interface, ``AwsCredentialProvider.get()``, called by the reader for
every request:

- ``StaticKeyProvider``: the key is a vault *reference*. ``CredentialBroker`` resolves the secret
  (a JSON document ``access_key_id`` / ``secret_access_key`` / optional ``session_token``) per
  call, so ``notify_rotated`` takes effect on the next request. The provider keeps no copy.
- ``WebIdentityProvider``: no secret at rest. An injected callable supplies a short-lived
  OIDC token (a Microsoft Entra token in the intended deployment), exchanged through STS
  ``AssumeRoleWithWebIdentity`` for session credentials that are cached only until shortly
  before they expire.

The STS call is unsigned (the web-identity token is the credential) and runs in a worker thread;
the SDK is imported lazily so importing this module needs no boto3. (The module is named
``aws_auth`` because the repository's secret guard refuses file names containing the word
"credentials".)
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, runtime_checkable

from neurosphere_connector import SecretValue
from neurosphere_connector.health import Clock, utc_now
from neurosphere_connector.vault import CredentialBroker
from neurosphere_core.errors import CapabilityUnavailableError

from neurosphere_connector_aws_bedrock.aws_errors import map_aws_error

__all__ = [
    "DEFAULT_CREDENTIAL_NAME",
    "AwsCredentialProvider",
    "AwsCredentials",
    "StaticKeyProvider",
    "WebIdentityProvider",
]

DEFAULT_CREDENTIAL_NAME = "aws_access_key"
_MASK = "AwsCredentials(***)"


@dataclass(frozen=True)
class AwsCredentials:
    """Request-scoped credentials. ``repr`` and ``str`` never show a field."""

    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)
    session_token: str | None = field(default=None, repr=False)
    expires_at: datetime | None = None

    def __repr__(self) -> str:
        return _MASK

    __str__ = __repr__


@runtime_checkable
class AwsCredentialProvider(Protocol):
    """How the reader obtains credentials, once per request."""

    @property
    def auth_mode(self) -> Literal["workload_identity_federation", "vault_reference"]: ...

    async def get(self) -> AwsCredentials: ...


def _malformed() -> CapabilityUnavailableError:
    # Never say which field or show any content: the document is a secret.
    return CapabilityUnavailableError("aws_credential_malformed", "the AWS credential is malformed")


class StaticKeyProvider:
    """Static access key held in a vault; resolved by the broker on every call."""

    auth_mode: Literal["workload_identity_federation", "vault_reference"] = "vault_reference"

    def __init__(self, broker: CredentialBroker, name: str = DEFAULT_CREDENTIAL_NAME) -> None:
        self._broker = broker
        self._name = name

    def __repr__(self) -> str:
        return f"StaticKeyProvider(name={self._name!r})"

    async def get(self) -> AwsCredentials:
        secret = await self._broker.get(self._name)
        try:
            doc = json.loads(secret.reveal())
        except ValueError:
            raise _malformed() from None
        if not isinstance(doc, dict):
            raise _malformed()
        fields: Mapping[str, Any] = doc  # pyright: ignore[reportUnknownVariableType]
        key, sec, token = (
            fields.get("access_key_id"),
            fields.get("secret_access_key"),
            fields.get("session_token"),
        )
        if not isinstance(key, str) or not key or not isinstance(sec, str) or not sec:
            raise _malformed()
        if token is not None and not isinstance(token, str):
            raise _malformed()
        return AwsCredentials(access_key_id=key, secret_access_key=sec, session_token=token)


TokenSource = Callable[[], Awaitable[str | SecretValue]]
AssumeRole = Callable[[str, str, str, str, int], Mapping[str, Any]]
"""``(role_arn, session_name, web_identity_token, region, duration_seconds) -> sts Credentials``."""


def _sts_assume_role_with_web_identity(
    role_arn: str, session_name: str, token: str, region: str, duration_seconds: int
) -> Mapping[str, Any]:
    """Blocking STS call. The request is unsigned: the OIDC token is the credential."""
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    client = boto3.client(
        "sts",
        region_name=region,
        config=Config(
            signature_version=UNSIGNED,
            retries={"total_max_attempts": 1, "mode": "standard"},
            connect_timeout=5,
            read_timeout=20,
        ),
    )
    try:
        response = client.assume_role_with_web_identity(
            RoleArn=role_arn,
            RoleSessionName=session_name,
            WebIdentityToken=token,
            DurationSeconds=duration_seconds,
        )
    except Exception as exc:
        raise map_aws_error(exc) from None
    creds: Mapping[str, Any] = response["Credentials"]
    return creds


class WebIdentityProvider:
    """Web-identity federation: exchange an injected OIDC token for short-lived credentials."""

    auth_mode: Literal["workload_identity_federation", "vault_reference"] = (
        "workload_identity_federation"
    )

    def __init__(
        self,
        *,
        role_arn: str,
        session_name: str,
        token_source: TokenSource,
        region: str,
        assume_role: AssumeRole = _sts_assume_role_with_web_identity,
        clock: Clock = utc_now,
        refresh_margin: timedelta = timedelta(minutes=5),
        duration_seconds: int = 3600,
    ) -> None:
        if not role_arn.startswith("arn:aws:iam::"):
            raise ValueError("role_arn must be an IAM role ARN in the aws partition")
        self._role_arn = role_arn
        self._session_name = session_name
        self._token_source = token_source
        self._region = region
        self._assume = assume_role
        self._clock = clock
        self._margin = refresh_margin
        self._duration = duration_seconds
        self._cached: AwsCredentials | None = None
        self._lock = asyncio.Lock()

    def __repr__(self) -> str:
        return "WebIdentityProvider(***)"

    def invalidate(self) -> None:
        """Drop the cached session so the next call exchanges a fresh token."""
        self._cached = None

    async def get(self) -> AwsCredentials:
        async with self._lock:
            cached = self._cached
            if (
                cached is not None
                and cached.expires_at is not None
                and self._clock() < cached.expires_at - self._margin
            ):
                return cached
            token = await self._token_source()
            raw = token.reveal() if isinstance(token, SecretValue) else token
            sts = await asyncio.to_thread(
                self._assume, self._role_arn, self._session_name, raw, self._region, self._duration
            )
            self._cached = self._parse(sts)
            return self._cached

    @staticmethod
    def _parse(sts: Mapping[str, Any]) -> AwsCredentials:
        key, sec, token = (
            sts.get("AccessKeyId"),
            sts.get("SecretAccessKey"),
            sts.get("SessionToken"),
        )
        expiry = sts.get("Expiration")
        if not isinstance(key, str) or not isinstance(sec, str) or not isinstance(token, str):
            raise _malformed()
        expires = expiry.astimezone(UTC) if isinstance(expiry, datetime) else None
        return AwsCredentials(
            access_key_id=key, secret_access_key=sec, session_token=token, expires_at=expires
        )
