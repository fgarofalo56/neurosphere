"""Records hold metadata and decisions only; SIEM export is redacted again (defence in depth)."""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_core.audit import (
    AuditContext,
    InMemoryAuditStore,
    JsonLinesFileSink,
    SiemExporter,
    StdoutSink,
    build_after,
    build_before,
    build_denied,
    find_sensitive_content,
    make_subject,
    to_siem_event,
)
from neurosphere_core.errors import InvalidSchemaError

from .audit_helpers import CHAIN, TARGET, make_ctx, make_repo, mixed_drafts, subject

# A fake, unsigned JWT-shaped string, assembled at runtime so the repo secret scan does not
# match a literal token in source (it is not a credential).
_JWT = ".".join(("eyJ" + "hbGciOiJSUzI1NiJ9", "eyJ" + "zdWIiOiIxMjM0NTY3ODkwIn0", "c2lnbmF0dXJl"))
_OBJECT_ID = "6f1d9a2e-3b4c-4d5e-8f60-718293a4b5c6"
_EMAIL = "jane.doe@contoso.com"
_PROMPT = "Summarize the confidential Q3 board memo for me please"


def _all_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [s for v in value.values() for s in _all_strings(v)]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    if isinstance(value, list):
        return [s for v in value for s in _all_strings(v)]  # pyright: ignore[reportUnknownVariableType]
    return []


def test_contract_has_no_body_or_token_fields() -> None:
    def names(model: Any, prefix: str = "") -> set[str]:
        found: set[str] = set()
        for name, field in model.model_fields.items():
            found.add(prefix + name)
            ann = field.annotation
            for candidate in getattr(ann, "__args__", (ann,)):
                if hasattr(candidate, "model_fields") and not hasattr(candidate, "root"):
                    found |= names(candidate, prefix + name + ".")
        return found

    leaves = {n.rsplit(".", 1)[-1] for n in names(AuditRecord)}
    assert not leaves & {"prompt", "response", "body", "token", "email", "upn", "oid", "messages"}


async def test_every_written_record_passes_the_scan() -> None:
    store = InMemoryAuditStore()
    repo = make_repo(store)
    for draft in mixed_drafts(12):
        await repo.append(CHAIN, draft)
    docs = store.raw_documents(CHAIN)
    assert len(docs) == 12
    for doc in docs:
        assert find_sensitive_content(doc) == []
        assert not {_JWT, _OBJECT_ID, _EMAIL, _PROMPT} & set(_all_strings(doc))


async def test_target_state_is_stored_as_digest_only() -> None:
    store = InMemoryAuditStore()
    state = {"system_prompt": _PROMPT, "owner": _EMAIL}
    sub = make_subject(TARGET, "model_deployment", target_version="etag-1", state=state)
    await make_repo(store).append(CHAIN, build_before(make_ctx(), sub))
    raw = json.dumps(store.raw_documents(CHAIN))
    assert _PROMPT not in raw and _EMAIL not in raw
    assert sub.state_digest is not None and sub.state_digest.root.startswith("sha256:")


def _ctx_with(**actor: Any) -> AuditContext:
    base = make_ctx()
    return base.model_copy(update={"actor": base.actor.model_copy(update=actor)})


_POISON: list[tuple[str, Any]] = [
    (
        "jwt_in_detail",
        lambda: build_after(make_ctx(), subject(), result="failed", verified=False, detail=_JWT),
    ),
    (
        "prompt_in_detail",
        lambda: build_after(make_ctx(), subject(), result="failed", verified=False, detail=_PROMPT),
    ),
    ("bearer_in_version", lambda: build_before(make_ctx(), subject(version="Bearer " + _JWT))),
    (
        "email_in_snapshot_ref",
        lambda: build_before(
            make_ctx(), make_subject(TARGET, "model_deployment", snapshot_ref=f"snap/{_EMAIL}")
        ),
    ),
    (
        "object_id_as_pseudonym",
        lambda: build_denied(
            _ctx_with(principal_pseudonym=_OBJECT_ID), code="forbidden", reason="x"
        ),
    ),
    (
        "object_id_on_behalf_of",
        lambda: build_denied(_ctx_with(on_behalf_of=_OBJECT_ID), code="forbidden", reason="x"),
    ),
    (
        "object_id_in_person_target",
        lambda: build_denied(
            make_ctx(),
            code="forbidden",
            reason="x",
            subject=make_subject(f"commercial:contoso:entra:person:{_OBJECT_ID}", "person"),
        ),
    ),
    (
        "account_key_in_snapshot_ref",
        lambda: build_before(
            make_ctx(), make_subject(TARGET, "model_deployment", snapshot_ref="x;AccountKey=abc123")
        ),
    ),
]


@pytest.mark.parametrize(("case", "make"), _POISON, ids=[c for c, _ in _POISON])
async def test_sensitive_content_is_refused_at_append(case: str, make: Any) -> None:
    store = InMemoryAuditStore()
    with pytest.raises(InvalidSchemaError) as info:
        await make_repo(store).append(CHAIN, make())
    assert info.value.reason == "audit_content_rejected", case
    assert store.raw_documents(CHAIN) == []  # nothing written: the caller aborts
    rendered = json.dumps(info.value.to_problem_details("corr-1").model_dump(mode="json"))
    for secret in (_JWT, _OBJECT_ID, _EMAIL, _PROMPT, "abc123"):
        assert secret not in rendered and secret not in str(info.value)


async def test_guid_shaped_versions_and_non_person_ids_are_allowed() -> None:
    store = InMemoryAuditStore()
    sub = make_subject(
        f"commercial:contoso:arm:subscription:{_OBJECT_ID}",
        "subscription",
        target_version=f'"{_OBJECT_ID}"',  # Cosmos ETags are quoted GUIDs
    )
    await make_repo(store).append(CHAIN, build_before(make_ctx(), sub))
    assert len(store.raw_documents(CHAIN)) == 1


# -- SIEM export ------------------------------------------------------------------------------


def _unguarded_record() -> AuditRecord:
    """A record carrying sensitive strings, built WITHOUT seal (models a pre-guard record)."""
    return AuditRecord.model_validate(
        {
            "schema_version": "1.0.0",
            "audit_id": "11111111-2222-4333-8444-555555555555",
            "chain_id": CHAIN,
            "sequence": 0,
            "previous_hash": None,
            "record_hash": "sha256:" + "0" * 64,
            "kind": "after",
            "recorded_at": "2026-10-10T17:05:20Z",
            "actor": {
                "principal_pseudonym": _OBJECT_ID,
                "principal_kind": "user",
                "on_behalf_of": None,
            },
            "scope_hash": "sha256:" + "1" * 64,
            "correlation_id": "corr-1",
            "operation": "action.execute",
            "channel": "rest",
            "intent_id": None,
            "subject": {
                "target": {"canonical_id": TARGET, "entity_type": "model_deployment"},
                "target_version": "Bearer " + _JWT,
                "state_digest": None,
                "snapshot_ref": f"snapshots/{_EMAIL}/after.json",
            },
            "outcome": {"result": "failed", "verified": False, "detail": f"{_EMAIL} {_JWT}"},
            "denial": None,
        }
    )


def test_siem_event_is_redacted() -> None:
    event = to_siem_event(_unguarded_record())
    text = json.dumps(event)
    for secret in (_JWT, _OBJECT_ID, _EMAIL):
        assert secret not in text
    assert event["record"]["subject"]["snapshot_ref"] == "[REDACTED]"
    assert event["record"]["audit_id"] == "11111111-2222-4333-8444-555555555555"
    assert event["record"]["record_hash"] == "sha256:" + "0" * 64
    assert event["event_type"] == "neurosphere.audit.v1"


async def test_stdout_and_file_sinks_emit_redacted_json_lines(tmp_path: Path) -> None:
    stream = io.StringIO()
    path = tmp_path / "siem.jsonl"
    exporter = SiemExporter([StdoutSink(stream), JsonLinesFileSink(path)])
    await exporter.export(_unguarded_record())
    await exporter.export(_unguarded_record())
    for text in (stream.getvalue(), path.read_text(encoding="utf-8")):
        lines = text.splitlines()
        assert len(lines) == 2
        assert all(json.loads(line)["event_type"] == "neurosphere.audit.v1" for line in lines)
        for secret in (_JWT, _OBJECT_ID, _EMAIL):
            assert secret not in text


class _BrokenSink:
    name = "broken"

    async def emit(self, event: Mapping[str, Any]) -> None:
        raise ConnectionError(f"siem down {_EMAIL}")


async def test_failing_sink_never_blocks_append_or_other_sinks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stream = io.StringIO()
    exporter = SiemExporter([_BrokenSink(), StdoutSink(stream)])
    store = InMemoryAuditStore()
    repo = make_repo(store, exporter=exporter)
    with caplog.at_level(logging.WARNING):
        for draft in mixed_drafts(3):
            await repo.append(CHAIN, draft)
    assert len(store.raw_documents(CHAIN)) == 3
    assert len(stream.getvalue().splitlines()) == 3
    assert exporter.failures == 3
    assert _EMAIL not in caplog.text
    assert any(getattr(r, "sink", None) == "broken" for r in caplog.records)
