"""PRP-06 item 4: the composed audit repository exports redacted SIEM events (NS_AUDIT_SIEM_*).

The REAL data builder composes ``AuditRepository(CosmosAuditStore(...))`` over an in-memory
Cosmos item fake (no emulator, no network); the sink is chosen only by environment settings.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from authz.authz_helpers import FakeClock  # pyright: ignore[reportMissingImports]
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError,
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from neurosphere_api.runtime.builders import data
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import (
    AuditContext,
    AuditDraft,
    AuditRepository,
    build_before,
    build_denied,
    find_sensitive_content,
    make_subject,
)
from neurosphere_core.scope import IdentityScope
from runtime_api.runtime_helpers import (  # pyright: ignore[reportMissingImports]
    Composed,
    compose,
    configure_auth_env,
)

from .data_helpers import builders_with_real_data, data_overrides

CHAIN = "contoso.domain-retail"
TARGET = "commercial:contoso:foundry:model_deployment:eastus2/chat-prod"
SCOPE_HASH = "sha256:" + hashlib.sha256(b"scope").hexdigest()
#: Allowed in a record (Cosmos ETags are quoted GUIDs) but scrubbed from every SIEM event.
_OBJECT_ID = "6f1d9a2e-3b4c-4d5e-8f60-718293a4b5c6"
#: Target state is stored as a digest only; the body must never reach the SIEM.
_PROMPT = "Summarize the confidential Q3 board memo for me please"


# -- an item-capable in-memory Cosmos client (the slice CosmosAuditStore uses) ---------------


@dataclass
class _ItemContainer:
    items: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    etags: int = 0

    def _stamp(self, body: Mapping[str, Any]) -> dict[str, Any]:
        self.etags += 1
        return {**body, "_etag": f'"etag-{self.etags}"', "_rid": "rid"}

    @staticmethod
    def _key(body: Mapping[str, Any]) -> tuple[str, str]:
        return (str(body["chain_id"]), str(body["id"]))

    async def read_item(self, item: str, partition_key: str, **_kw: Any) -> dict[str, Any]:
        found = self.items.get((partition_key, item))
        if found is None:
            raise CosmosResourceNotFoundError(message="not found")
        return dict(found)

    async def create_item(self, body: Mapping[str, Any], **_kw: Any) -> dict[str, Any]:
        key = self._key(body)
        if key in self.items:
            raise CosmosResourceExistsError(message="exists")
        self.items[key] = self._stamp(body)
        return dict(self.items[key])

    async def replace_item(
        self, item: str, body: Mapping[str, Any], etag: str | None = None, **_kw: Any
    ) -> dict[str, Any]:
        key = (str(body["chain_id"]), item)
        current = self.items.get(key)
        if current is None:
            raise CosmosResourceNotFoundError(message="not found")
        if etag is not None and current["_etag"] != etag:
            raise CosmosAccessConditionFailedError(message="precondition failed")
        self.items[key] = self._stamp(body)
        return dict(self.items[key])

    def query_items(
        self, query: str, parameters: list[dict[str, Any]], partition_key: str, **_kw: Any
    ) -> AsyncIterator[dict[str, Any]]:
        values = {p["name"]: p["value"] for p in parameters}

        async def _pages() -> AsyncIterator[dict[str, Any]]:
            for (chain, _id), doc in list(self.items.items()):
                if (
                    chain == partition_key
                    and doc.get("doc_type") == values["@doc_type"]
                    and values["@start"] <= doc.get("sequence", -1) < values["@stop"]
                ):
                    yield dict(doc)

        return _pages()


@dataclass
class _ItemDatabase:
    containers: dict[str, _ItemContainer] = field(default_factory=dict)

    def get_container_client(self, name: str) -> _ItemContainer:
        return self.containers.setdefault(name, _ItemContainer())


@dataclass
class _ItemCosmosClient:
    databases: dict[str, _ItemDatabase] = field(default_factory=dict)

    def get_database_client(self, name: str) -> _ItemDatabase:
        return self.databases.setdefault(name, _ItemDatabase())

    async def close(self) -> None:
        return None


# -- helpers ----------------------------------------------------------------------------------


def _ctx() -> AuditContext:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": "contoso",
            "principal": {
                "principal_id": "commercial:contoso:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": ["commercial:contoso:catalog:domain:retail"],
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": SCOPE_HASH,
        }
    )
    scope = IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]
    return AuditContext.from_scope(
        scope, correlation_id="corr-7c41e2", operation="action.execute", channel="rest"
    )


def _drafts() -> list[AuditDraft]:
    ctx = _ctx()
    before = make_subject(
        TARGET,
        "model_deployment",
        target_version=f'"{_OBJECT_ID}"',
        state={"system_prompt": _PROMPT},
    )
    return [build_before(ctx, before), build_denied(ctx, code="forbidden", reason="x")]


def _compose(monkeypatch: pytest.MonkeyPatch, **siem: str) -> tuple[Composed, _ItemCosmosClient]:
    configure_auth_env(monkeypatch)
    for name, value in siem.items():
        monkeypatch.setenv(f"NS_AUDIT_SIEM_{name}", value)
    client = _ItemCosmosClient()
    clock = FakeClock()
    overrides = data_overrides(clock, without=("audit",), cosmos_client_factory=lambda: client)
    composed = compose(overrides, builders=builders_with_real_data(), clock=clock)
    return composed, client


def _repository(composed: Composed) -> AuditRepository:
    assert composed.registry.get("audit").state == "ok"
    repository = composed.app.state.audit_repository
    assert isinstance(repository, AuditRepository)
    return repository


def _assert_redacted(lines: list[str]) -> None:
    for line in lines:
        event = json.loads(line)
        assert event["event_type"] == "neurosphere.audit.v1"
        # The record-level scan (server-assigned ``audit_id`` is exempt at the record root).
        assert find_sensitive_content(event["record"]) == []
        for secret in (_OBJECT_ID, _PROMPT, "Bearer", "eyJ"):
            assert secret not in line


# -- tests ------------------------------------------------------------------------------------


async def test_composed_append_emits_one_redacted_event_per_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "siem.jsonl"
    composed, client = _compose(monkeypatch, SINK="file", FILE_PATH=str(path))
    repository = _repository(composed)
    records = [await repository.append(CHAIN, draft) for draft in _drafts()]

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(records) == 2
    _assert_redacted(lines)
    exported = [json.loads(line)["record"] for line in lines]
    assert [e["audit_id"] for e in exported] == [r.audit_id.root for r in records]
    assert [e["record_hash"] for e in exported] == [r.record_hash.root for r in records]
    assert exported[0]["subject"]["target_version"] == '"[REDACTED]"'
    # The durable record kept the ETag; only the export scrubbed it.
    (database,) = client.databases.values()
    stored = database.containers[data.AUDIT_CHAIN_CONTAINER].items
    assert len(stored) == 2
    assert any(_OBJECT_ID in json.dumps(doc) for doc in stored.values())


async def test_stdout_sink_emits_redacted_json_lines(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    composed, _client = _compose(monkeypatch, SINK="stdout")
    repository = _repository(composed)
    capsys.readouterr()
    for draft in _drafts():
        await repository.append(CHAIN, draft)
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("{")]
    assert len(lines) == 2
    _assert_redacted(lines)


async def test_failing_sink_never_aborts_or_forks_the_audit_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # A directory is not appendable: every emit raises inside the sink.
    composed, _client = _compose(monkeypatch, SINK="file", FILE_PATH=str(tmp_path))
    repository = _repository(composed)
    with caplog.at_level(logging.WARNING):
        records = [await repository.append(CHAIN, draft) for draft in _drafts()]
    assert [r.sequence for r in records] == [0, 1]
    tail = await repository.tail(CHAIN)
    assert tail is not None and tail.sequence == 1
    assert tail.record_hash == records[-1].record_hash.root
    verification = await repository.verify(CHAIN)
    assert verification.ok, verification
    failures = [r for r in caplog.records if r.getMessage() == "siem sink failed"]
    assert len(failures) == 2
    assert _PROMPT not in caplog.text and _OBJECT_ID not in caplog.text


async def test_default_is_no_export(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NS_AUDIT_SIEM_SINK", raising=False)
    monkeypatch.delenv("NS_AUDIT_SIEM_FILE_PATH", raising=False)
    composed, _client = _compose(monkeypatch)
    repository = _repository(composed)
    assert repository._exporter is None  # pyright: ignore[reportPrivateUsage]
    await repository.append(CHAIN, _drafts()[0])


@pytest.mark.parametrize(
    "siem", [{"SINK": "file"}, {"SINK": "syslog"}], ids=["file_without_path", "unknown_sink"]
)
def test_invalid_siem_settings_name_the_audit_component(
    monkeypatch: pytest.MonkeyPatch, siem: dict[str, str]
) -> None:
    monkeypatch.delenv("NS_AUDIT_SIEM_FILE_PATH", raising=False)
    composed, _client = _compose(monkeypatch, **siem)
    audit = composed.registry.get("audit")
    assert audit.state == "failed"
    assert audit.reason == "audit_siem_settings_invalid"
