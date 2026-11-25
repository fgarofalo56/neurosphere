"""PRP-102 item 3: Key Vault key wrapper over a fake httpx transport (no network, no Azure)."""

from __future__ import annotations

import base64
import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
import pytest
from neurosphere_core.cloud import CloudName
from neurosphere_core.crypto import (
    CONTENT_INTEGRITY_FAILED,
    KEY_HOST_REFUSED,
    KEY_WRAP_UNAVAILABLE,
    EnvelopeError,
    KeyVaultKeyWrapper,
    WrappedKey,
    canonical_aad,
    open_envelope,
    seal,
)

COMMERCIAL_HOST = "contoso-kv.vault.azure.net"
GOVERNMENT_HOST = "contoso-kv.vault.usgovcloudapi.net"
KEY_NAME = "ns-interaction-kek"
CANARY = "NS-CANARY-91be-prompt-body"


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass
class FakeVault:
    host: str = COMMERCIAL_HOST
    version: str = field(default_factory=lambda: os.urandom(16).hex())
    standard_alphabet: bool = False
    status: int = 200
    raw_body: bytes | None = None
    kid_override: str | None = None
    requests: list[httpx.Request] = field(default_factory=list)
    store: dict[bytes, bytes] = field(default_factory=dict)

    @property
    def kid(self) -> str:
        return f"https://{self.host}/keys/{KEY_NAME}/{self.version}"

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"code": "Throttled"}})
        if self.raw_body is not None:
            return httpx.Response(200, content=self.raw_body)
        kid = self.kid_override or self.kid
        if request.method == "GET":
            return httpx.Response(200, json={"key": {"kid": kid, "kty": "RSA"}})
        body = json.loads(request.content)
        value = _b64url_decode(body["value"])
        if request.url.path.endswith("/wrapkey"):
            handle = os.urandom(256)
            self.store[handle] = value
            encoded = (
                base64.b64encode(handle).decode() if self.standard_alphabet else _b64url(handle)
            )
            return httpx.Response(200, json={"kid": kid, "value": encoded})
        return httpx.Response(200, json={"kid": kid, "value": _b64url(self.store[value])})


class TokenSpy:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> str:
        self.calls += 1
        return "test-bearer-" + os.urandom(4).hex()


def _wrapper(
    vault: FakeVault,
    *,
    uri: str | None = None,
    cloud: CloudName = CloudName.COMMERCIAL,
    tokens: TokenSpy | None = None,
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> KeyVaultKeyWrapper:
    return KeyVaultKeyWrapper(
        uri if uri is not None else f"https://{vault.host}/keys/{KEY_NAME}/{vault.version}",
        cloud=cloud,
        token_provider=tokens or TokenSpy(),
        transport=httpx.MockTransport(handler or vault.handler),
        timeout_seconds=1.0,
    )


async def test_wrap_and_unwrap_requests_are_exact() -> None:
    vault = FakeVault()
    wrapper = _wrapper(vault)
    data_key = os.urandom(32)
    wrapped = await wrapper.wrap(data_key)
    assert wrapped.key_id == vault.kid
    assert wrapped.algorithm == "RSA-OAEP-256"
    assert await wrapper.unwrap(wrapped) == data_key

    wrap_req, unwrap_req = vault.requests
    for request, operation in ((wrap_req, "wrapkey"), (unwrap_req, "unwrapkey")):
        assert request.method == "POST"
        assert request.url.scheme == "https"
        assert request.url.host == COMMERCIAL_HOST
        assert request.url.path == f"/keys/{KEY_NAME}/{vault.version}/{operation}"
        assert dict(request.url.params) == {"api-version": "2025-07-01"}
        assert request.headers["authorization"].startswith("Bearer test-bearer-")
        body = json.loads(request.content)
        assert set(body) == {"alg", "value"}
        assert body["alg"] == "RSA-OAEP-256"
    assert _b64url_decode(json.loads(wrap_req.content)["value"]) == data_key
    assert _b64url_decode(json.loads(unwrap_req.content)["value"]) == wrapped.value


async def test_requests_never_carry_plaintext() -> None:
    vault = FakeVault()
    wrapper = _wrapper(vault)
    plaintext = f"the prompt mentions {CANARY}".encode()
    aad = canonical_aad({"interaction_id": "int-9"})
    envelope = await seal(plaintext, aad, wrapper)
    assert await open_envelope(envelope, aad, wrapper) == plaintext
    assert envelope.key_id == vault.kid
    assert len(vault.requests) == 2
    for request in vault.requests:
        raw = request.content + str(request.url).encode()
        assert CANARY.encode() not in raw
        assert plaintext not in raw
        assert _b64url(plaintext).encode() not in raw
        # Only the 32-byte data key (wrap) or the wrapped handle (unwrap) is sent.
        assert len(_b64url_decode(json.loads(request.content)["value"])) in (32, 256)


async def test_standard_base64_answer_is_accepted() -> None:
    vault = FakeVault(standard_alphabet=True)
    wrapper = _wrapper(vault)
    data_key = os.urandom(32)
    assert await wrapper.unwrap(await wrapper.wrap(data_key)) == data_key


async def test_unversioned_uri_resolves_once() -> None:
    vault = FakeVault()
    wrapper = _wrapper(vault, uri=f"https://{vault.host}/keys/{KEY_NAME}")
    assert wrapper.key_id == f"https://{vault.host}/keys/{KEY_NAME}"
    first = await wrapper.wrap(os.urandom(32))
    second = await wrapper.wrap(os.urandom(32))
    assert first.key_id == second.key_id == vault.kid
    assert wrapper.key_id == vault.kid
    methods = [(r.method, r.url.path) for r in vault.requests]
    assert methods == [
        ("GET", f"/keys/{KEY_NAME}"),
        ("POST", f"/keys/{KEY_NAME}/{vault.version}/wrapkey"),
        ("POST", f"/keys/{KEY_NAME}/{vault.version}/wrapkey"),
    ]
    assert dict(vault.requests[0].url.params) == {"api-version": "2025-07-01"}


async def test_old_key_version_unwraps_after_rotation() -> None:
    vault = FakeVault()
    wrapper = _wrapper(vault, uri=f"https://{vault.host}/keys/{KEY_NAME}")
    data_key = os.urandom(32)
    old = await wrapper.wrap(data_key)
    old_version = vault.version
    vault.version = os.urandom(16).hex()
    rotated = _wrapper(vault, uri=f"https://{vault.host}/keys/{KEY_NAME}")
    assert await rotated.unwrap(old) == data_key
    assert vault.requests[-1].url.path == f"/keys/{KEY_NAME}/{old_version}/unwrapkey"


@pytest.mark.parametrize(
    ("cloud", "host"),
    [(CloudName.GOVERNMENT, COMMERCIAL_HOST), (CloudName.COMMERCIAL, GOVERNMENT_HOST)],
)
async def test_cross_cloud_host_refused_before_token(cloud: CloudName, host: str) -> None:
    vault = FakeVault(host=host)
    tokens = TokenSpy()
    with pytest.raises(EnvelopeError) as caught:
        _wrapper(vault, cloud=cloud, tokens=tokens)
    assert str(caught.value) == KEY_HOST_REFUSED
    assert caught.value.__cause__ is None
    assert tokens.calls == 0
    assert vault.requests == []


async def test_government_host_accepted_in_government() -> None:
    vault = FakeVault(host=GOVERNMENT_HOST)
    wrapper = _wrapper(vault, cloud=CloudName.GOVERNMENT)
    data_key = os.urandom(32)
    assert await wrapper.unwrap(await wrapper.wrap(data_key)) == data_key


@pytest.mark.parametrize(
    "uri",
    [
        f"http://{COMMERCIAL_HOST}/keys/{KEY_NAME}",
        f"https://user@{COMMERCIAL_HOST}/keys/{KEY_NAME}",
        f"https://{COMMERCIAL_HOST}:443/keys/{KEY_NAME}",
        f"https://{COMMERCIAL_HOST}/keys/{KEY_NAME}?x=1",
        f"https://{COMMERCIAL_HOST}/keys/{KEY_NAME}#frag",
        f"https://{COMMERCIAL_HOST}.evil.example/keys/{KEY_NAME}",
        f"https://evil.example/{COMMERCIAL_HOST}/keys/{KEY_NAME}",
        f"https://a.b{'.vault.azure.net'}/keys/{KEY_NAME}",
        "https://vault.azure.net/keys/x",
        f"https://{COMMERCIAL_HOST}/secrets/{KEY_NAME}",
        f"https://{COMMERCIAL_HOST}/keys/{KEY_NAME}/notaversion",
        f"https://{COMMERCIAL_HOST}/keys/{KEY_NAME}/",
        f"https://{COMMERCIAL_HOST}/keys/{KEY_NAME}/{'0' * 32}/extra",
        "",
    ],
)
def test_malformed_kek_uri_refused(uri: str) -> None:
    tokens = TokenSpy()
    with pytest.raises(EnvelopeError, match=f"^{KEY_HOST_REFUSED}$"):
        _wrapper(FakeVault(), uri=uri, tokens=tokens)
    assert tokens.calls == 0


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503, 302])
async def test_non_200_is_unavailable(status: int) -> None:
    vault = FakeVault(status=status)
    wrapper = _wrapper(vault)
    with pytest.raises(EnvelopeError) as caught:
        await wrapper.wrap(os.urandom(32))
    assert str(caught.value) == KEY_WRAP_UNAVAILABLE
    # On unwrap a 400 means Key Vault refused the wrapped value or version: a tampered envelope.
    unwrap_reason = CONTENT_INTEGRITY_FAILED if status == 400 else KEY_WRAP_UNAVAILABLE
    with pytest.raises(EnvelopeError, match=f"^{unwrap_reason}$"):
        await wrapper.unwrap(WrappedKey(vault.kid, "RSA-OAEP-256", os.urandom(256)))
    assert len(vault.requests) == 2  # no retry loop, no redirect followed


@pytest.mark.parametrize(
    "raw",
    [b"not json", b"[]", b'{"kid": 1}', b'{"value": "@@@"}', b'{"kid": "x", "value": ""}'],
)
async def test_malformed_answer_is_unavailable(raw: bytes) -> None:
    wrapper = _wrapper(FakeVault(raw_body=raw))
    with pytest.raises(EnvelopeError, match=f"^{KEY_WRAP_UNAVAILABLE}$"):
        await wrapper.wrap(os.urandom(32))


async def test_foreign_kid_in_answer_is_unavailable() -> None:
    vault = FakeVault()
    vault.kid_override = f"https://other-kv.vault.azure.net/keys/{KEY_NAME}/{vault.version}"
    with pytest.raises(EnvelopeError, match=f"^{KEY_WRAP_UNAVAILABLE}$"):
        await _wrapper(vault).wrap(os.urandom(32))


async def test_timeout_and_transport_errors_are_unavailable() -> None:
    vault = FakeVault()

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"timed out talking to {request.url}", request=request)

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    for handler in (timeout, broken):
        with pytest.raises(EnvelopeError) as caught:
            await _wrapper(vault, handler=handler).wrap(os.urandom(32))
        assert str(caught.value) == KEY_WRAP_UNAVAILABLE
        # No chain at all: the httpx error (which names the URL) is not even on __context__.
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        with pytest.raises(EnvelopeError) as sealed:
            await seal(CANARY.encode(), b"aad", _wrapper(vault, handler=handler))
        assert sealed.value.__context__ is None


async def test_token_failure_is_unavailable() -> None:
    async def failing() -> str:
        raise RuntimeError("token endpoint said no")

    vault = FakeVault()
    wrapper = KeyVaultKeyWrapper(
        vault.kid,
        cloud=CloudName.COMMERCIAL,
        token_provider=failing,
        transport=httpx.MockTransport(vault.handler),
    )
    with pytest.raises(EnvelopeError, match=f"^{KEY_WRAP_UNAVAILABLE}$"):
        await wrapper.wrap(os.urandom(32))
    assert vault.requests == []


@pytest.mark.parametrize(
    "key_id",
    [
        f"https://other-kv.vault.azure.net/keys/{KEY_NAME}/{'a' * 32}",
        f"https://{COMMERCIAL_HOST}/keys/other-key/{'a' * 32}",
        f"https://{COMMERCIAL_HOST}/keys/{KEY_NAME}",
        f"https://{GOVERNMENT_HOST}/keys/{KEY_NAME}/{'a' * 32}",
        "local:0123456789abcdef",
    ],
)
async def test_unwrap_with_foreign_key_id_refused(key_id: str) -> None:
    vault = FakeVault()
    tokens = TokenSpy()
    wrapper = _wrapper(vault, tokens=tokens)
    with pytest.raises(EnvelopeError, match=f"^{CONTENT_INTEGRITY_FAILED}$"):
        await wrapper.unwrap(WrappedKey(key_id, "RSA-OAEP-256", os.urandom(256)))
    assert tokens.calls == 0
    assert vault.requests == []


@pytest.mark.parametrize("algorithm", ["RSA-OAEP", "RSA1_5", "A256KW", "local-a256gcm"])
async def test_unwrap_other_algorithm_refused(algorithm: str) -> None:
    vault = FakeVault()
    with pytest.raises(EnvelopeError, match=f"^{CONTENT_INTEGRITY_FAILED}$"):
        await _wrapper(vault).unwrap(WrappedKey(vault.kid, algorithm, os.urandom(256)))
    assert vault.requests == []


async def test_nothing_identifying_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    vault = FakeVault()
    wrapper = _wrapper(vault, uri=f"https://{vault.host}/keys/{KEY_NAME}")
    data_key = os.urandom(32)
    with caplog.at_level(logging.DEBUG):
        wrapped = await wrapper.wrap(data_key)
        await wrapper.unwrap(wrapped)
        failing = _wrapper(FakeVault(status=429))
        with pytest.raises(EnvelopeError):
            await failing.wrap(data_key)
    text = "\n".join(
        [r.getMessage() for r in caplog.records] + [str(r.args) for r in caplog.records]
    )
    for needle in (
        COMMERCIAL_HOST,
        "vault.azure.net",
        KEY_NAME,
        vault.version,
        "/keys/",
        _b64url(data_key),
        base64.b64encode(data_key).decode(),
        _b64url(wrapped.value),
        base64.b64encode(wrapped.value).decode(),
    ):
        assert needle not in text
