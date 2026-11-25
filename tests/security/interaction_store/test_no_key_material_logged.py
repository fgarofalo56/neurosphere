"""PRP-102 item 6, acceptance criteria 3 and 4: nothing sensitive in logs or exceptions.

The whole flow runs under ``caplog`` at DEBUG for the root logger plus ``httpx`` and
``httpcore``: put, read, query, metadata, a tampered read, delete, a lifecycle purge through
the real engine, and every refusal. Afterwards no log record and no raised exception (``str``,
``repr``, ``args``, walked through ``__cause__`` and ``__context__``) carries a canary, the
replaced credential-shaped value, a secret-shaped refused text, the local key file contents, a
wrapped key, a data key (captured by spying the wrapper), a bearer token, the vault host, the
key name, the key version or the Key Vault URL. A Government wrapper refuses a Commercial vault
host and the reverse, with ``key_host_refused`` and the token provider never called.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.interactions.v1.redacted_content import RedactedContent
from neurosphere_core.cloud import CloudName
from neurosphere_core.crypto import (
    CONTENT_INTEGRITY_FAILED,
    KEY_HOST_REFUSED,
    KEY_WRAP_UNAVAILABLE,
    EnvelopeError,
    KeyVaultKeyWrapper,
    LocalFileKeyWrapper,
    WrappedKey,
)
from neurosphere_core.interactions import (
    DATA_CLASS_INTERACTION,
    InMemoryInteractionStore,
    InteractionQuery,
    InteractionStoreError,
)
from neurosphere_core.interactions.settings import local_kek_placeholder
from neurosphere_core.lifecycle import Effect, JobStatus
from neurosphere_core.lifecycle.policy import UNSET, PolicyState

from ._harness import (
    COMMERCIAL_SUFFIX,
    CUSTOMER,
    DOMAIN,
    GOVERNMENT_SUFFIX,
    FakeVault,
    SpyWrapper,
    TokenSpy,
    build_corpus,
    content_doc,
    exception_text,
    found,
    lifecycle_ctx,
    lifecycle_for,
    log_text,
    make_content,
    make_record,
    new_id,
    policy,
    secret_shaped_texts,
)

_LOGGERS = ("", "httpx", "httpcore", "httpcore.connection", "httpcore.http11", "neurosphere_core")


@dataclass
class _Policy:
    state: PolicyState = field(default_factory=policy)

    def __call__(self) -> PolicyState:
        return self.state


@dataclass
class _Flow:
    errors: list[BaseException] = field(default_factory=list)

    async def expect(self, reason: str, operation: Callable[[], Awaitable[Any]]) -> None:
        try:
            await operation()
        except (EnvelopeError, InteractionStoreError) as exc:
            assert exc.reason == reason, exc.reason
            self.errors.append(exc)
        else:  # pragma: no cover - a refusal that did not happen is the failure
            raise AssertionError(f"expected {reason}")


def _key_vault_store(vault: FakeVault, tokens: TokenSpy, gate: _Policy) -> InMemoryInteractionStore:
    wrapper = KeyVaultKeyWrapper(
        vault.key_uri,
        cloud=CloudName.COMMERCIAL,
        token_provider=tokens,
        transport=vault.transport(),
        timeout_seconds=1.0,
    )
    return InMemoryInteractionStore(SpyWrapper(wrapper), kek_uri=vault.key_uri, policy=gate)


@pytest.mark.parametrize("kind", ["local", "key_vault"])
async def test_whole_flow_logs_and_raises_nothing_sensitive(
    kind: str, key_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    for name in _LOGGERS:
        caplog.set_level(logging.DEBUG, logger=name)
    corpus = build_corpus()
    refused_texts = secret_shaped_texts()
    gate = _Policy()
    tokens = TokenSpy()
    vault = FakeVault()
    identifiers: list[str] = []
    key_file_bytes = b""
    if kind == "local":
        spy = SpyWrapper(LocalFileKeyWrapper(key_file))
        key_file_bytes = key_file.read_bytes()  # noqa: ASYNC240 - a tiny tmp file
        kek_uri = local_kek_placeholder(CloudName.COMMERCIAL)
        identifiers += [kek_uri, kek_uri.split("/")[2], str(key_file), key_file.name]
    else:
        wrapper = KeyVaultKeyWrapper(
            vault.key_uri,
            cloud=CloudName.COMMERCIAL,
            token_provider=tokens,
            transport=vault.transport(),
            timeout_seconds=1.0,
        )
        spy = SpyWrapper(wrapper)
        kek_uri = vault.key_uri
    identifiers += [vault.host, vault.label, vault.key_name, vault.version, vault.key_uri]
    store = InMemoryInteractionStore(spy, kek_uri=kek_uri, policy=gate)
    flow = _Flow()

    # --- happy path: put, read, metadata, query -------------------------------------------------
    ids = [new_id() for _ in range(3)]
    for iid in ids:
        await store.put(
            make_record(iid), make_content(iid, corpus.texts), capture_retention_days=30
        )
    for iid in ids:
        read = await store.read_content(CUSTOMER, DOMAIN, iid)
        assert tuple(part.text.root for part in read.parts) == corpus.texts
        assert await store.get_metadata(CUSTOMER, DOMAIN, iid) is not None
    page = await store.query_index(InteractionQuery(customer_id=CUSTOMER, domain_id=DOMAIN))
    assert len(page.items) == len(ids)

    # --- failures on the read side ----------------------------------------------------------------
    first, second, third = ids
    first_ref = (await store.get_metadata(CUSTOMER, DOMAIN, first)).content_ref  # type: ignore[union-attr]
    third_ref = (await store.get_metadata(CUSTOMER, DOMAIN, third)).content_ref  # type: ignore[union-attr]
    assert first_ref is not None and third_ref is not None
    blob = store.content_backend.blobs[third_ref.pointer]
    store.content_backend.blobs[third_ref.pointer] = blob[:-1] + bytes([blob[-1] ^ 1])
    await flow.expect(CONTENT_INTEGRITY_FAILED, lambda: store.read_content(CUSTOMER, DOMAIN, third))
    store.content_backend.blobs[third_ref.pointer] = blob
    await flow.expect(
        CONTENT_INTEGRITY_FAILED,
        lambda: spy.unwrap(WrappedKey(spy.key_id, "RSA-OAEP-256", b"\x01" * 256)),
    )
    await flow.expect(
        "interaction_not_found", lambda: store.read_content(CUSTOMER, DOMAIN, new_id())
    )

    # --- every write refusal --------------------------------------------------------------------
    gate.state = UNSET
    refused = new_id()
    await flow.expect(
        "content_retention_not_enabled",
        lambda: store.put(
            make_record(refused), make_content(refused, corpus.texts), capture_retention_days=30
        ),
    )
    gate.state = policy()
    for text in refused_texts.values():
        await flow.expect(
            "content_not_secret_free",
            lambda text=text: store.put(
                make_record(refused),
                make_content(refused, [corpus.texts[0], text]),
                capture_retention_days=30,
            ),
        )
    failed_state = RedactedContent.model_construct(
        **{**content_doc(refused, corpus.texts), "redaction_state": "redaction_failed"}
    )
    bad_bodies: list[Any] = [
        failed_state,
        content_doc(refused, corpus.texts),
        corpus.texts[0],
        b"x",
    ]
    for bad in bad_bodies:
        await flow.expect(
            "content_not_secret_free",
            lambda bad=bad: store.put(make_record(refused), bad, capture_retention_days=30),
        )
    gov_store = InMemoryInteractionStore(
        spy, kek_uri="https://" + vault.label + GOVERNMENT_SUFFIX + "/keys/k", policy=gate
    )
    await flow.expect(
        KEY_HOST_REFUSED,
        lambda: gov_store.put(
            make_record(refused), make_content(refused, corpus.texts), capture_retention_days=30
        ),
    )
    # Key Vault outage: the httpx error names the request URL and must not ride along.
    broken = FakeVault(
        label=vault.label, key_name=vault.key_name, version=vault.version, broken=True
    )
    outage = _key_vault_store(broken, tokens, gate)
    await flow.expect(
        KEY_WRAP_UNAVAILABLE,
        lambda: outage.put(
            make_record(refused), make_content(refused, corpus.texts), capture_retention_days=30
        ),
    )
    for cloud, suffix in (
        (CloudName.GOVERNMENT, COMMERCIAL_SUFFIX),
        (CloudName.COMMERCIAL, GOVERNMENT_SUFFIX),
    ):
        uri = "https://" + vault.label + suffix + "/keys/" + vault.key_name

        async def construct(uri: str = uri, cloud: CloudName = cloud) -> None:
            KeyVaultKeyWrapper(uri, cloud=cloud, token_provider=tokens, transport=vault.transport())

        await flow.expect(KEY_HOST_REFUSED, construct)

    # --- delete and lifecycle purge --------------------------------------------------------------
    assert await store.delete(CUSTOMER, DOMAIN, first) is True
    assert await store.delete(CUSTOMER, DOMAIN, first) is False
    await flow.expect("interaction_not_found", lambda: store.read_content(CUSTOMER, DOMAIN, first))
    engine, target = lifecycle_for(store)
    outcomes = await engine.sweep_expiry(
        lifecycle_ctx(), target=target, data_class=DATA_CLASS_INTERACTION
    )
    assert len(outcomes) == 2
    assert all(o.status is JobStatus.COMPLETED and o.effect is Effect.DELETED for o in outcomes)
    assert store.content_backend.blobs == {}
    assert store.index_backend.documents == {}
    await flow.expect("interaction_not_found", lambda: store.read_content(CUSTOMER, DOMAIN, second))

    # --- the assertions -------------------------------------------------------------------------
    assert store.refusals["content_not_secret_free"] == len(refused_texts) + 4
    # caplog really captured the run (else the log assertions would be vacuous).
    messages = [record.getMessage() for record in caplog.records]
    refusal_total = sum(sum(s.refusals.values()) for s in (store, gov_store, outage))
    assert refusal_total == len(refused_texts) + 7
    assert messages.count("interaction content write refused") == refusal_total
    assert spy.data_keys and spy.wrapped_values
    if kind == "key_vault":
        assert tokens.calls > 0 and vault.requests, "the fake vault was never exercised"

    sensitive_text: list[str] = [
        *corpus.forbidden,
        *corpus.texts,
        *refused_texts.values(),
        *tokens.issued,
    ]
    sensitive_bytes: list[bytes] = [*spy.data_keys, *spy.wrapped_values]
    if key_file_bytes:
        sensitive_bytes.append(key_file_bytes)

    logs = log_text(caplog.records)
    assert found(logs.encode("utf-8"), [*sensitive_text, *sensitive_bytes]) == []
    for identifier in identifiers:
        assert identifier not in logs, "identifier in logs"
    for suffix in (COMMERCIAL_SUFFIX, GOVERNMENT_SUFFIX, "/keys/"):
        assert suffix not in logs

    assert len(flow.errors) >= len(refused_texts) + 10
    for error in flow.errors:
        text = exception_text(error)
        assert found(text.encode("utf-8"), [*sensitive_text, *sensitive_bytes]) == []
        for identifier in identifiers:
            assert identifier not in text, (type(error).__name__, str(error))
        for suffix in (COMMERCIAL_SUFFIX, GOVERNMENT_SUFFIX, "/keys/", "http"):
            assert suffix not in text, (type(error).__name__, str(error))
        assert str(error) == error.reason  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("cloud", "foreign_suffix"),
    [(CloudName.GOVERNMENT, COMMERCIAL_SUFFIX), (CloudName.COMMERCIAL, GOVERNMENT_SUFFIX)],
)
async def test_cross_cloud_vault_host_refused_before_any_token(
    cloud: CloudName, foreign_suffix: str
) -> None:
    vault = FakeVault(suffix=foreign_suffix)
    tokens = TokenSpy()
    for uri in (vault.key_uri, vault.kid):
        with pytest.raises(EnvelopeError) as caught:
            KeyVaultKeyWrapper(uri, cloud=cloud, token_provider=tokens, transport=vault.transport())
        assert caught.value.reason == KEY_HOST_REFUSED
        assert caught.value.__cause__ is None
        assert vault.host not in exception_text(caught.value)
    assert tokens.calls == 0
    assert vault.requests == []

    # A wrapper on its own cloud never unwraps a key recorded on the other cloud's vault.
    home_suffix = GOVERNMENT_SUFFIX if cloud is CloudName.GOVERNMENT else COMMERCIAL_SUFFIX
    home = FakeVault(suffix=home_suffix, key_name=vault.key_name)
    wrapper = KeyVaultKeyWrapper(
        home.kid, cloud=cloud, token_provider=tokens, transport=home.transport()
    )
    with pytest.raises(EnvelopeError) as foreign:
        await wrapper.unwrap(WrappedKey(vault.kid, "RSA-OAEP-256", b"\x02" * 256))
    assert foreign.value.reason == CONTENT_INTEGRITY_FAILED
    assert tokens.calls == 0
    assert home.requests == []
