"""PRP-62 item 4: credential providers (rotation, expiry refresh, no leaks)."""
# ruff: noqa: S106

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from neurosphere_connector import CredentialBroker, SecretValue, StaticCredentialResolver
from neurosphere_connector_aws_bedrock.aws_auth import (
    AwsCredentialProvider,
    AwsCredentials,
    StaticKeyProvider,
    WebIdentityProvider,
)
from neurosphere_contracts.connectors.v1.connector_manifest import CredentialRef
from neurosphere_core.errors import CapabilityUnavailableError, DependencyTransientError

_REF = CredentialRef(
    name="aws_access_key", vault_ref="https://ns-vault.vault.azure.net/secrets/aws-bedrock-reader"
)


def _doc(key: str, secret: str = "SECRETVALUE123", token: str | None = None) -> str:  # noqa: S107
    doc: dict[str, str] = {"access_key_id": key, "secret_access_key": secret}
    if token:
        doc["session_token"] = token
    return json.dumps(doc)


def _static(resolver: StaticCredentialResolver) -> tuple[CredentialBroker, StaticKeyProvider]:
    broker = CredentialBroker(resolver, [_REF])
    return broker, StaticKeyProvider(broker)


async def test_static_key_is_resolved_from_the_broker() -> None:
    _, provider = _static(StaticCredentialResolver({_REF.vault_ref: _doc("AKIAONE", token="tok")}))
    assert isinstance(provider, AwsCredentialProvider)
    creds = await provider.get()
    assert (creds.access_key_id, creds.session_token) == ("AKIAONE", "tok")
    assert provider.auth_mode == "vault_reference"


async def test_notify_rotated_takes_effect_on_the_next_call() -> None:
    resolver = StaticCredentialResolver({_REF.vault_ref: _doc("AKIAONE")})
    broker, provider = _static(resolver)
    assert (await provider.get()).access_key_id == "AKIAONE"
    resolver.rotate(_REF, _doc("AKIATWO"))  # RotationSource signal drops the broker cache
    assert (await provider.get()).access_key_id == "AKIATWO"
    resolver._values[_REF.vault_ref] = _doc("AKIATHREE")
    assert (await provider.get()).access_key_id == "AKIATWO"  # cached until notified
    await broker.notify_rotated("aws_access_key")
    assert (await provider.get()).access_key_id == "AKIATHREE"


@pytest.mark.parametrize(
    "bad",
    ["not json", "[]", "{}", json.dumps({"access_key_id": "A"}), json.dumps({"access_key_id": 1})],
)
async def test_malformed_secret_raises_typed_error_without_content(bad: str) -> None:
    _, provider = _static(StaticCredentialResolver({_REF.vault_ref: bad}))
    with pytest.raises(CapabilityUnavailableError) as err:
        await provider.get()
    assert err.value.reason == "aws_credential_malformed"
    assert bad not in str(err.value)
    assert err.value.__cause__ is None


async def test_unresolvable_secret_is_a_transient_error_with_no_chain() -> None:
    _, provider = _static(StaticCredentialResolver({}))
    with pytest.raises(DependencyTransientError):
        await provider.get()


async def test_secret_never_appears_in_repr_str_or_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, provider = _static(StaticCredentialResolver({_REF.vault_ref: _doc("AKIALEAKCHECK")}))
    with caplog.at_level(logging.DEBUG):
        creds = await provider.get()
    blob = " ".join([repr(creds), str(creds), f"{creds}", repr(provider), caplog.text])
    assert "AKIALEAKCHECK" not in blob
    assert "SECRETVALUE123" not in blob


# ------------------------------------------------------------------ web identity


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def _sts(clock: _Clock, calls: list[tuple[str, str, str, str, int]]) -> Any:
    def assume(
        role: str, session: str, token: str, region: str, duration: int
    ) -> Mapping[str, Any]:
        calls.append((role, session, token, region, duration))
        return {
            "AccessKeyId": f"ASIA{len(calls)}",
            "SecretAccessKey": "sts-secret",
            "SessionToken": "sts-token",
            "Expiration": clock.now + timedelta(hours=1),
        }

    return assume


def _web_identity(clock: _Clock, calls: list[Any], tokens: list[str]) -> WebIdentityProvider:
    async def source() -> SecretValue:
        tokens.append("asked")
        return SecretValue("entra-oidc-token")

    return WebIdentityProvider(
        role_arn="arn:aws:iam::111122223333:role/ns-bedrock-reader",
        session_name="neurosphere",
        token_source=source,
        region="us-east-1",
        assume_role=_sts(clock, calls),
        clock=clock,
    )


async def test_web_identity_exchanges_the_token_and_caches_until_near_expiry() -> None:
    clock, calls, asked = _Clock(), [], []
    provider = _web_identity(clock, calls, asked)
    first = await provider.get()
    assert first.access_key_id == "ASIA1"
    assert calls[0][2] == "entra-oidc-token"
    assert provider.auth_mode == "workload_identity_federation"
    clock.now += timedelta(minutes=30)
    assert (await provider.get()).access_key_id == "ASIA1"  # still fresh: no new exchange
    assert len(calls) == 1
    clock.now += timedelta(minutes=26)  # inside the 5 minute refresh margin
    assert (await provider.get()).access_key_id == "ASIA2"
    assert len(asked) == 2


async def test_web_identity_invalidate_forces_a_fresh_exchange() -> None:
    clock, calls = _Clock(), []
    provider = _web_identity(clock, calls, [])
    await provider.get()
    provider.invalidate()
    await provider.get()
    assert len(calls) == 2


async def test_web_identity_hides_token_and_session_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock, calls = _Clock(), []
    provider = _web_identity(clock, calls, [])
    with caplog.at_level(logging.DEBUG):
        creds = await provider.get()
    blob = " ".join([repr(creds), repr(provider), caplog.text])
    for secret in ("entra-oidc-token", "sts-secret", "sts-token", "ASIA1"):
        assert secret not in blob


async def test_web_identity_rejects_a_malformed_sts_answer() -> None:
    clock = _Clock()

    def bad(*_a: Any) -> Mapping[str, Any]:
        return {"AccessKeyId": "ASIA"}

    async def source() -> str:
        return "t"

    provider = WebIdentityProvider(
        role_arn="arn:aws:iam::111122223333:role/r",
        session_name="s",
        token_source=source,
        region="us-east-1",
        assume_role=bad,
        clock=clock,
    )
    with pytest.raises(CapabilityUnavailableError):
        await provider.get()


def test_web_identity_requires_an_aws_partition_role_arn() -> None:
    async def source() -> str:
        return "t"

    with pytest.raises(ValueError, match="role ARN"):
        WebIdentityProvider(
            role_arn="arn:aws-us-gov:iam::111122223333:role/r",
            session_name="s",
            token_source=source,
            region="us-east-1",
        )


def test_credentials_object_masks_every_field() -> None:
    creds = AwsCredentials(access_key_id="AKIAX", secret_access_key="sek", session_token="tok")
    assert "AKIAX" not in repr(creds) + str(creds)
    assert "sek" not in repr(creds) + str(creds)
