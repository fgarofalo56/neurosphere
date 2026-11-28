"""PRP-104 item 4: the bounded, audited interaction export (criteria 4, 5, 6; clarification 7).

Routes run over item 3's harness (``test_content_read.Api``: PRP-06 authz harness, fake clock,
:class:`InMemoryInteractionStore` with synthetic records) plus an in-memory export backend and a
key wrapper that both log into the SAME ``events`` list as the audit append and every decrypt.
That one list proves the order: the ``interaction.export`` record is durable before any content
is decrypted, and the download record before the bundle envelope is opened. Synthetic data only:
every canary is generated at runtime. ``test_export_held_content.py`` imports this harness.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import authz.authz_helpers as helpers  # pyright: ignore[reportMissingImports]
import pytest
from neurosphere_api.interactions import (
    EXPORT_TTL,
    MAX_EXPORT,
    MAX_OPEN_EXPORTS,
    PREFIX,
    InMemoryExportBackend,
    InteractionExplorer,
    InteractionExportStorage,
    bundle_aad,
    configure_interaction_explorer,
)
from neurosphere_api.interactions.export_storage import BlobExportBackend
from neurosphere_contracts.audit.v1.audit_record import AuditRecord
from neurosphere_contracts.interactions.v1.interaction_export_manifest import (
    InteractionExportManifest,
)
from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord
from neurosphere_contracts.interactions.v1.redacted_content import RedactedContent
from neurosphere_core.auth.scope import Role
from neurosphere_core.crypto import (
    Envelope,
    EnvelopeError,
    KeyWrapper,
    LocalFileKeyWrapper,
    WrappedKey,
    open_envelope,
)
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.interactions import InMemoryInteractionStore
from neurosphere_core.interactions.store import content_aad
from test_content_read import (  # pyright: ignore[reportMissingImports]
    ADMIN,
    AGENT,
    ANALYST,
    AUDITOR,
    CUSTOMER,
    EXPIRING,
    EXPIRY_SECONDS,
    FIN_CHAIN,
    FINANCE,
    GOV_FINANCE,
    INVESTIGATOR,
    INVESTIGATOR_ONLY,
    KEK_URI,
    OPERATIONS,
    OPS_INVESTIGATOR,
    OTHER_CUSTOMER_FINANCE,
    PURPOSE,
    STEWARD,
    T_CAPTURE,
    VIEWER,
    Api,
    canary,
    card_number,
    generated_secret,
    investigator_role,
    new_id,
    object_id,
    record_doc,
    redacted,
    stamp,
)

#: A second investigator of FINANCE (creator-only access to manifests and bundles).
OTHER_INVESTIGATOR = object_id()
OTHER_AGENT = f"commercial:{CUSTOMER}:foundry:agent:billing-bot"
FILTERS: dict[str, Any] = {
    "from": stamp(T_CAPTURE - timedelta(days=1)),
    "to": stamp(T_CAPTURE + timedelta(days=1)),
    "agent_ids": [],
    "detected_categories": [],
}
BODY: dict[str, Any] = {"purpose": PURPOSE, "filters": FILTERS}


class SpyWrapper:
    """The local file key wrapper, logging each wrap and unwrap into ``events``."""

    def __init__(self, inner: KeyWrapper, events: list[str]) -> None:
        self._inner = inner
        self.events = events
        self.wraps = 0
        self.unwraps = 0

    @property
    def key_id(self) -> str:
        return self._inner.key_id

    async def wrap(self, data_key: bytes) -> WrappedKey:
        self.wraps += 1
        self.events.append("wrap")
        return await self._inner.wrap(data_key)

    async def unwrap(self, wrapped: WrappedKey) -> bytes:
        self.unwraps += 1
        self.events.append("unwrap")
        return await self._inner.unwrap(wrapped)


class SpyBackend(InMemoryExportBackend):
    """The in-memory export backend, logging each write; ``fail_puts`` makes writes fail."""

    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events
        self.writes = 0
        self.fail_puts = False

    async def put(self, name: str, data: bytes) -> None:
        self.writes += 1
        if self.fail_puts:
            raise DependencyTransientError("down", reason="interaction_export_storage_unavailable")
        self.events.append("write:" + name.rsplit("/", 1)[1])
        await super().put(name, data)


class ExportApi(Api):
    def __init__(self, tmp_path: Path, *, exports: bool = True, **kwargs: Any) -> None:
        explorer_on = kwargs.pop("explorer", True)
        super().__init__(tmp_path, explorer=False, **kwargs)
        self.h.repo.put_principal(
            helpers.policy(
                OTHER_INVESTIGATOR,
                investigator_role(FINANCE, suffix="-other"),
                helpers.role(Role.VIEWER, FINANCE),
            )
        )
        self.backend = SpyBackend(self.events)
        self.wrapper = SpyWrapper(LocalFileKeyWrapper(tmp_path / "kek.bin"), self.events)
        storage = (
            InteractionExportStorage(backend=self.backend, wrapper=self.wrapper, kek_uri=KEK_URI)
            if exports
            else None
        )
        self.explorer = InteractionExplorer(
            store=self.store,
            audit=self.audit,
            cloud=self.explorer.cloud,
            customer_id=self.explorer.customer_id,
            exports=storage,
        )
        if explorer_on:
            configure_interaction_explorer(self.h.app, self.explorer)

    # --- requests ---------------------------------------------------------------------------------

    def create(self, who: str, *, domain: str = FINANCE, body: Any = BODY) -> Any:
        return self.h.client.post(
            f"{PREFIX}/{domain}/interaction-exports", json=body, headers=self.h.auth(who)
        )

    def manifest(self, who: str, export_id: str, *, domain: str = FINANCE) -> Any:
        return self.h.client.get(
            f"{PREFIX}/{domain}/interaction-exports/{export_id}", headers=self.h.auth(who)
        )

    def bundle(self, who: str, export_id: str, *, domain: str = FINANCE) -> Any:
        return self.h.client.get(
            f"{PREFIX}/{domain}/interaction-exports/{export_id}/bundle", headers=self.h.auth(who)
        )

    def created(self, who: str = INVESTIGATOR, **kwargs: Any) -> InteractionExportManifest:
        response = self.create(who, **kwargs)
        assert response.status_code == 201, response.text
        return InteractionExportManifest.model_validate(response.json())

    # --- data -------------------------------------------------------------------------------------

    def seed_records(self, *docs: dict[str, Any], marks: list[str] | None = None) -> list[str]:
        """Store each record doc with redacted content carrying a fresh canary mark."""
        out: list[str] = []

        async def put_all() -> None:
            for doc in docs:
                mark = canary()
                out.append(mark)
                record = InteractionRecord.model_validate(doc)
                iid = record.interaction_id.root
                await self.store.put(record, redacted(iid, mark), capture_retention_days=30)

        asyncio.run(put_all())
        if marks is not None:
            marks.extend(out)
        return out

    def seed_many(self, count: int, **overrides: Any) -> list[str]:
        """``count`` FINANCE records one second apart (index 0 oldest); returns their ids."""
        ids = [new_id() for _ in range(count)]
        docs = [
            record_doc(
                iid,
                captured_at=stamp(T_CAPTURE + timedelta(seconds=i)),
                occurred_at=stamp(T_CAPTURE + timedelta(seconds=i - 1)),
                **overrides,
            )
            for i, iid in enumerate(ids)
        ]
        self.seed_records(*docs)
        return ids

    def export_records(self, chain: str = FIN_CHAIN) -> list[AuditRecord]:
        return [r for r in self.records(chain) if r.operation.startswith("interaction.export")]

    def principal_id(self, who: str) -> str:
        principal = self.scope_of(who).to_contract().principal.principal_id
        return str(getattr(principal, "root", principal))

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.h.clock.now, UTC)


@pytest.fixture
def api(tmp_path: Path) -> ExportApi:
    return ExportApi(tmp_path)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --- create: the manifest and the bundle ---------------------------------------------------------


def test_create_appends_one_record_before_decrypting_then_seals_and_writes(api: ExportApi) -> None:
    ids = api.seed_many(3)
    api.seed_records(record_doc(new_id(), domain_id=OPERATIONS))  # another domain: never selected
    response = api.create(INVESTIGATOR)
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    manifest = InteractionExportManifest.model_validate(response.json())
    newest_first = list(reversed(ids))

    # Ordering: the record, then the decrypts, then the seal, then bundle and manifest writes.
    assert api.events == (
        ["audit:interaction.export"]
        + [f"decrypt:{i}" for i in newest_first]
        + ["wrap", "write:bundle.env", "write:manifest.json"]
    )

    # Manifest fields (PRP-99 contract, validated above).
    assert manifest.schema_version == "1.2.0"
    assert manifest.cloud.root == "commercial"
    assert manifest.customer_id.root == CUSTOMER
    assert [d.root for d in manifest.domain_ids] == [FINANCE]
    assert manifest.requested_by.root == api.principal_id(INVESTIGATOR)
    assert manifest.purpose.model_dump(mode="json") == PURPOSE
    assert manifest.filters.model_dump(mode="json", by_alias=True) == FILTERS
    assert manifest.interaction_count == 3
    assert [i.root for i in manifest.interaction_ids] == newest_first
    assert manifest.excluded_count == 0
    assert manifest.includes_held_content is False
    requested = _parse(manifest.requested_at.root)
    assert requested == api.now().replace(microsecond=0)
    assert _parse(manifest.expires_at.root) - requested == EXPORT_TTL == timedelta(hours=24)

    # The bundle reference points at the sealed blob under the export prefix.
    export_id = manifest.export_id.root
    prefix = f"exports/{CUSTOMER}/"
    assert manifest.bundle.pointer.startswith(prefix)
    assert manifest.bundle.pointer.endswith(f"/{export_id}/bundle.env")
    assert manifest.bundle.kek_uri == KEK_URI
    assert manifest.bundle.algorithm == "aes_256_gcm"
    sealed = api.backend.blobs[manifest.bundle.pointer]
    assert manifest.bundle.byte_length == len(sealed)
    stored_manifest = api.backend.blobs[
        manifest.bundle.pointer[: -len("bundle.env")] + "manifest.json"
    ]
    assert InteractionExportManifest.model_validate_json(stored_manifest) == manifest

    # One interaction.export record, content-free, whose id the manifest carries.
    (record,) = api.export_records()
    assert record.operation == "interaction.export"
    assert record.channel == "rest"
    assert manifest.audit_id.root == record.audit_id.root
    assert record.subject is not None
    assert record.subject.target.entity_type == "interaction_export"
    assert record.subject.target.canonical_id == (
        f"commercial:{CUSTOMER}:neurosphere:interaction_export:{export_id}"
    )
    dumped = record.model_dump_json()
    assert "INC-2026-0042" not in dumped
    assert api.store.content_reads == 3
    assert api.denials.attempts == []


def test_bundle_download_is_audited_before_the_envelope_is_opened(api: ExportApi) -> None:
    ids = api.seed_many(2)
    manifest = api.created()
    export_id = manifest.export_id.root
    api.events.clear()
    response = api.bundle(INVESTIGATOR, export_id)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("application/json")
    assert f"interaction-export-{export_id}.json" in response.headers["content-disposition"]
    # Ordering: the download record is durable before the one unwrap that opens the bundle.
    assert api.events == ["audit:interaction.export_download", "unwrap"]

    bundle = json.loads(response.content)
    assert bundle["format"] == "ns-interaction-export-bundle-1"
    assert (bundle["export_id"], bundle["customer_id"], bundle["domain_id"]) == (
        export_id,
        CUSTOMER,
        FINANCE,
    )
    assert list(bundle["interactions"]) == [i.root for i in manifest.interaction_ids]
    for iid in ids:
        content = RedactedContent.model_validate(bundle["interactions"][iid])
        stored = asyncio.run(
            InMemoryInteractionStore.read_content(api.store, CUSTOMER, FINANCE, iid)
        )
        assert content == stored  # the stored redacted content, unchanged

    create_record, download = api.export_records()
    assert create_record.operation == "interaction.export"
    assert download.operation == "interaction.export_download"
    assert download.subject is not None
    assert download.subject.target.canonical_id.endswith(f":interaction_export:{export_id}")
    assert manifest.model_dump_json() not in download.model_dump_json()


def test_bundle_envelope_opens_only_with_its_own_aad(api: ExportApi, tmp_path: Path) -> None:
    api.seed_many(1)
    manifest = api.created()
    export_id = manifest.export_id.root
    envelope = Envelope.from_bytes(api.backend.blobs[manifest.bundle.pointer])
    wrapper = LocalFileKeyWrapper(tmp_path / "kek.bin")

    plaintext = asyncio.run(
        open_envelope(envelope, bundle_aad(CUSTOMER, FINANCE, export_id), wrapper)
    )
    assert json.loads(plaintext)["export_id"] == export_id

    wrong = [
        bundle_aad(CUSTOMER, FINANCE, new_id()),
        bundle_aad(CUSTOMER, OPERATIONS, export_id),
        bundle_aad("fabrikam", FINANCE, export_id),
        content_aad(CUSTOMER, FINANCE, export_id),
        b"",
    ]
    for aad in wrong:
        with pytest.raises(EnvelopeError) as caught:
            asyncio.run(open_envelope(envelope, aad, wrapper))
        assert caught.value.reason == "content_integrity_failed"


def test_redacted_away_values_never_appear_in_the_bundle_or_the_manifest(api: ExportApi) -> None:
    card, secret = card_number(), generated_secret()
    # Capture redacted these before storing: only placeholders were ever written.
    (mark,) = api.seed_records(record_doc(new_id()))
    create = api.create(INVESTIGATOR)
    assert create.status_code == 201
    manifest = InteractionExportManifest.model_validate(create.json())
    download = api.bundle(INVESTIGATOR, manifest.export_id.root)
    assert download.status_code == 200
    assert mark in download.text  # the real (redacted) content is there...
    assert "[[ns-redacted:payment_card]]" in download.text
    assert "[[ns-redacted:generated_secret]]" in download.text
    for text in (
        download.text,
        create.text,
        *(b.decode("latin-1") for b in api.backend.blobs.values()),
    ):
        assert card not in text  # ...the redacted-away values are not
        assert secret not in text
    assert mark not in create.text  # the manifest is metadata only
    for blob in api.backend.blobs.values():
        assert mark.encode() not in blob  # the bundle is sealed at rest
    for record in api.export_records():
        assert mark not in record.model_dump_json()


# --- bounds ---------------------------------------------------------------------------------------


def test_at_most_500_interactions_are_bundled_and_the_excess_is_counted(api: ExportApi) -> None:
    assert MAX_EXPORT == 500
    ids = api.seed_many(MAX_EXPORT + 3)
    purged = api.seed_many(1)[0]
    api.store.purged.add(purged)  # no stored content: excluded, never decrypted
    manifest = api.created()
    assert manifest.interaction_count == MAX_EXPORT
    assert len(manifest.interaction_ids) == MAX_EXPORT
    # The newest 500 of the 503 with content (index 0 is the oldest).
    assert {i.root for i in manifest.interaction_ids} == set(ids[3:])
    assert manifest.excluded_count == 3 + 1
    assert api.store.content_reads == MAX_EXPORT
    assert purged not in api.events


def test_filters_select_by_window_agent_and_category(api: ExportApi) -> None:
    in_window = new_id()
    other_agent = new_id()
    other_category = new_id()
    too_old = new_id()
    api.seed_records(
        record_doc(in_window),
        record_doc(other_agent, agent_id=OTHER_AGENT),
        record_doc(
            other_category,
            findings_summary=[{"category": "email_address", "count": 1, "action": "replaced"}],
        ),
        record_doc(
            too_old,
            captured_at=stamp(T_CAPTURE - timedelta(days=3)),
            occurred_at=stamp(T_CAPTURE - timedelta(days=3, seconds=1)),
        ),
    )
    body = {
        "purpose": PURPOSE,
        "filters": {**FILTERS, "agent_ids": [AGENT], "detected_categories": ["payment_card"]},
    }
    manifest = api.created(body=body)
    assert [i.root for i in manifest.interaction_ids] == [in_window]

    both = {
        "purpose": PURPOSE,
        "filters": {**FILTERS, "agent_ids": [AGENT, OTHER_AGENT], "detected_categories": []},
    }
    manifest = api.created(body=both)
    assert {i.root for i in manifest.interaction_ids} == {in_window, other_agent, other_category}


def test_nothing_selected_is_404_with_no_record(api: ExportApi) -> None:
    response = api.create(INVESTIGATOR)
    assert response.status_code == 404
    assert response.json()["reason"] == "interaction_export_empty"
    assert api.audit.attempts == 0
    assert api.backend.writes == 0


def test_an_investigator_has_at_most_five_open_exports(api: ExportApi) -> None:
    assert MAX_OPEN_EXPORTS == 5
    api.seed_many(1)
    for _ in range(MAX_OPEN_EXPORTS):
        api.created()
    reads, appends, writes = api.store.content_reads, api.audit.attempts, api.backend.writes
    response = api.create(INVESTIGATOR)
    assert response.status_code == 429, response.text
    assert response.json()["reason"] == "interaction_export_limit_reached"
    assert int(response.headers["retry-after"]) == int(EXPORT_TTL.total_seconds())
    # Refused before any record, decrypt or write.
    assert (api.store.content_reads, api.audit.attempts, api.backend.writes) == (
        reads,
        appends,
        writes,
    )
    # Another investigator's exports do not count against this one.
    assert api.create(OTHER_INVESTIGATOR).status_code == 201


def test_expired_exports_no_longer_count_and_are_swept(api: ExportApi) -> None:
    api.seed_many(1)
    first = api.created()
    api.h.clock.advance(3600)
    for _ in range(MAX_OPEN_EXPORTS - 1):
        api.created()
    assert api.create(INVESTIGATOR).status_code == 429
    api.h.clock.advance(EXPORT_TTL.total_seconds() - 3600)  # the first one has expired now
    assert api.create(INVESTIGATOR).status_code == 201
    assert first.bundle.pointer not in api.backend.blobs  # swept on the way


# --- expiry ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("route", ["manifest", "bundle"])
def test_expired_export_is_404_and_its_blobs_are_deleted(api: ExportApi, route: str) -> None:
    api.seed_many(1)
    manifest = api.created()
    export_id = manifest.export_id.root
    api.h.clock.advance(EXPORT_TTL.total_seconds() - 1)
    assert getattr(api, route)(INVESTIGATOR, export_id).status_code == 200
    api.h.clock.advance(1)
    unwraps = api.wrapper.unwraps
    response = getattr(api, route)(INVESTIGATOR, export_id)
    assert response.status_code == 404
    assert response.json()["reason"] == "interaction_export_expired"
    assert api.backend.blobs == {}
    assert api.wrapper.unwraps == unwraps
    assert getattr(api, route)(INVESTIGATOR, export_id).json()["reason"] == (
        "interaction_export_not_found"
    )


def test_manifest_route_returns_the_manifest_to_its_creator(api: ExportApi) -> None:
    api.seed_many(1)
    manifest = api.created()
    response = api.manifest(INVESTIGATOR, manifest.export_id.root)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert InteractionExportManifest.model_validate(response.json()) == manifest
    assert api.manifest(INVESTIGATOR, new_id()).status_code == 404


# --- 422 / 403 ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"filters": FILTERS},
        {"purpose": {}, "filters": FILTERS},
        {"purpose": {"purpose_code": "curiosity", "case_ref": None}, "filters": FILTERS},
        {
            "purpose": {"purpose_code": "security_review", "case_ref": str(uuid.uuid4())},
            "filters": FILTERS,
        },
        {
            "purpose": {"purpose_code": "security_review", "case_ref": "see the ticket"},
            "filters": FILTERS,
        },
        {"purpose": PURPOSE},
        {"purpose": PURPOSE, "filters": {**FILTERS, "from": FILTERS["to"]}},
        {"purpose": PURPOSE, "filters": {**FILTERS, "principal_id": "x"}},
        {"purpose": PURPOSE, "filters": FILTERS, "note": "why"},
    ],
    ids=[
        "no-purpose",
        "empty-purpose",
        "unknown-code",
        "guid-case-ref",
        "prose-case-ref",
        "no-filters",
        "empty-window",
        "unknown-filter",
        "extra-field",
    ],
)
def test_invalid_purpose_or_filters_is_422_before_anything(api: ExportApi, body: Any) -> None:
    api.seed_many(1)
    response = api.create(INVESTIGATOR, body=body)
    assert response.status_code == 422, response.text
    assert api.store.content_reads == 0
    assert api.audit.attempts == 0
    assert api.backend.writes == 0
    assert api.denials.attempts == []


REFUSALS = [
    (ADMIN, FINANCE, "target_out_of_scope"),
    (AUDITOR, FINANCE, "target_out_of_scope"),
    (STEWARD, FINANCE, "target_out_of_scope"),
    (ANALYST, FINANCE, "target_out_of_scope"),
    (VIEWER, FINANCE, "target_out_of_scope"),
    (OPS_INVESTIGATOR, FINANCE, "target_out_of_scope"),
    (INVESTIGATOR, OTHER_CUSTOMER_FINANCE, "target_out_of_scope"),
    (INVESTIGATOR, GOV_FINANCE, "target_out_of_scope"),
    (INVESTIGATOR_ONLY, FINANCE, "domain_not_readable"),
]
REFUSAL_IDS = [
    "admin",
    "security-auditor",
    "steward",
    "analyst",
    "viewer",
    "investigator-of-another-domain",
    "another-customer",
    "another-cloud",
    "investigator-without-data-read",
]


@pytest.mark.parametrize(("who", "domain", "reason"), REFUSALS, ids=REFUSAL_IDS)
def test_refused_creators_get_403_with_a_denial_record(
    api: ExportApi, who: str, domain: str, reason: str
) -> None:
    api.seed_many(1)
    response = api.create(who, domain=domain)
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == reason
    (attempt,) = api.denials.attempts
    assert (attempt.permission, attempt.reason, attempt.domain_id) == (
        "interaction.export",
        reason,
        domain,
    )
    assert api.store.content_reads == 0
    assert api.audit.attempts == 0
    assert api.backend.writes == 0


@pytest.mark.parametrize("route", ["manifest", "bundle"])
@pytest.mark.parametrize(("who", "domain", "reason"), REFUSALS, ids=REFUSAL_IDS)
def test_refused_readers_get_403_with_a_denial_record(
    api: ExportApi, route: str, who: str, domain: str, reason: str
) -> None:
    api.seed_many(1)
    export_id = api.created().export_id.root
    appends, unwraps = api.audit.attempts, api.wrapper.unwraps
    response = getattr(api, route)(who, export_id, domain=domain)
    assert response.status_code == 403, response.text
    assert response.json()["reason"] == reason
    (attempt,) = api.denials.attempts
    assert (attempt.permission, attempt.reason) == ("interaction.export", reason)
    assert (api.audit.attempts, api.wrapper.unwraps) == (appends, unwraps)


@pytest.mark.parametrize("route", ["manifest", "bundle"])
def test_only_the_creator_reads_an_export(api: ExportApi, route: str) -> None:
    api.seed_many(1)
    export_id = api.created().export_id.root
    appends, unwraps = api.audit.attempts, api.wrapper.unwraps
    response = getattr(api, route)(OTHER_INVESTIGATOR, export_id)
    assert response.status_code == 403
    assert response.json()["reason"] == "export_not_owned"
    (attempt,) = api.denials.attempts
    assert (attempt.permission, attempt.reason, attempt.resource_id) == (
        "interaction.export",
        "export_not_owned",
        export_id,
    )
    assert (api.audit.attempts, api.wrapper.unwraps) == (appends, unwraps)


@pytest.mark.parametrize("route", ["create", "manifest", "bundle"])
def test_expired_investigator_gets_403_with_a_denial_record(api: ExportApi, route: str) -> None:
    api.seed_many(1)
    export_id = api.created(EXPIRING).export_id.root
    api.h.clock.advance(EXPIRY_SECONDS + 60)
    appends = api.audit.attempts
    if route == "create":
        response = api.create(EXPIRING)
    else:
        response = getattr(api, route)(EXPIRING, export_id)
    assert response.status_code == 403
    (attempt,) = api.denials.attempts
    assert attempt.permission == "interaction.export"
    assert api.audit.attempts == appends


@pytest.mark.parametrize(
    ("cloud", "customer_id"),
    [("government", CUSTOMER), ("commercial", "fabrikam")],
    ids=["deployment-of-another-cloud", "deployment-of-another-customer"],
)
def test_caller_outside_the_deployment_tenancy_is_403(
    tmp_path: Path, cloud: str, customer_id: str
) -> None:
    api = ExportApi(tmp_path, cloud=cloud, customer_id=customer_id)
    api.seed_many(1)
    response = api.create(INVESTIGATOR)
    assert response.status_code == 403
    assert response.json()["reason"] == "tenancy_mismatch"
    (attempt,) = api.denials.attempts
    assert (attempt.permission, attempt.reason) == ("interaction.export", "tenancy_mismatch")
    assert api.store.content_reads == 0
    assert api.audit.attempts == 0


# --- fail closed ----------------------------------------------------------------------------------


def test_create_fails_closed_when_the_record_cannot_be_appended(tmp_path: Path) -> None:
    api = ExportApi(tmp_path, audit_fails=True)
    (mark,) = api.seed_records(record_doc(new_id()))
    response = api.create(INVESTIGATOR)
    assert response.status_code == 503, response.text
    assert response.json()["reason"] == "audit_write_failed"
    assert mark not in response.text
    assert api.audit.attempts == 1
    assert api.store.content_reads == 0  # zero decrypts
    assert api.wrapper.wraps == 0  # nothing sealed
    assert api.backend.writes == 0  # zero blob writes
    assert api.backend.blobs == {}
    assert api.events == []


def test_download_fails_closed_when_its_record_cannot_be_appended(api: ExportApi) -> None:
    (mark,) = api.seed_records(record_doc(new_id()))
    export_id = api.created().export_id.root
    api.events.clear()
    api.audit.fail = True
    unwraps = api.wrapper.unwraps
    response = api.bundle(INVESTIGATOR, export_id)
    assert response.status_code == 503, response.text
    assert response.json()["reason"] == "audit_write_failed"
    assert mark not in response.text
    assert api.wrapper.unwraps == unwraps  # the envelope was never opened
    assert api.events == []


def test_failed_bundle_write_is_503_and_leaves_no_export(api: ExportApi) -> None:
    api.seed_many(1)
    api.backend.fail_puts = True
    response = api.create(INVESTIGATOR)
    assert response.status_code == 503
    assert response.json()["reason"] == "interaction_export_storage_unavailable"
    assert api.backend.blobs == {}


# --- off ------------------------------------------------------------------------------------------


def test_explorer_off_is_503(tmp_path: Path) -> None:
    api = ExportApi(tmp_path, explorer=False)
    response = api.create(INVESTIGATOR)
    assert response.status_code == 503
    assert response.json()["reason"] == "interaction_explorer_unconfigured"
    assert api.manifest(INVESTIGATOR, new_id()).status_code == 503
    assert api.bundle(INVESTIGATOR, new_id()).status_code == 503


def test_exports_unconfigured_is_503(tmp_path: Path) -> None:
    api = ExportApi(tmp_path, exports=False)
    api.seed_many(1)
    response = api.create(INVESTIGATOR)
    assert response.status_code == 503
    assert response.json()["reason"] == "interaction_export_unconfigured"
    assert api.audit.attempts == 0
    assert api.store.content_reads == 0


# --- blob backend ---------------------------------------------------------------------------------


class FakeContainer:
    """The ``ContainerClient`` slice the export backend uses, over a dict."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.created = 0

    async def create_container(self, **kwargs: Any) -> None:
        self.created += 1

    async def upload_blob(
        self, name: str, data: bytes, *, overwrite: bool = False, **kw: Any
    ) -> None:
        from azure.core.exceptions import ResourceExistsError

        if name in self.blobs and not overwrite:
            raise ResourceExistsError("exists")
        self.blobs[name] = data

    async def download_blob(self, blob: str, **kwargs: Any) -> Any:
        from azure.core.exceptions import ResourceNotFoundError

        if blob not in self.blobs:
            raise ResourceNotFoundError("absent")
        data = self.blobs[blob]

        class _Download:
            async def readall(self) -> bytes:
                return data

        return _Download()

    async def delete_blob(self, blob: str, **kwargs: Any) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        if self.blobs.pop(blob, None) is None:
            raise ResourceNotFoundError("absent")

    def list_blobs(self, name_starts_with: str | None = None, **kwargs: Any) -> Any:
        names = sorted(n for n in self.blobs if n.startswith(name_starts_with or ""))

        class _Blob:
            def __init__(self, name: str) -> None:
                self.name = name

        async def items() -> Any:
            for name in names:
                yield _Blob(name)

        return items()


def test_blob_backend_round_trip_and_name_rules() -> None:
    container = FakeContainer()
    backend = BlobExportBackend(container, local=True)
    name = f"exports/{CUSTOMER}/{FINANCE.replace('/', '%2F')}/{new_id()}/manifest.json"

    async def run() -> list[str]:
        await backend.put(name, b"{}")
        assert await backend.get(name) == b"{}"
        listed = [n async for n in backend.list_names(f"exports/{CUSTOMER}/")]
        assert await backend.delete(name) is True
        assert await backend.delete(name) is False
        assert await backend.get(name) is None
        with pytest.raises(DependencyTransientError):
            await _put_twice(backend, name)
        return listed

    assert asyncio.run(run()) == [name]
    assert container.created == 1
    content_name = f"{CUSTOMER}/x/2026/11/20/{new_id()}.env"  # a PRP-102 content blob name
    for bad in (content_name, f"exports/{CUSTOMER}/d/{new_id()}/other.bin", "exports/../x"):
        with pytest.raises(ValueError):
            asyncio.run(backend.put(bad, b"x"))
        with pytest.raises(ValueError):
            asyncio.run(backend.get(bad))


async def _put_twice(backend: BlobExportBackend, name: str) -> None:
    await backend.put(name, b"{}")
    await backend.put(name, b"{}")  # create-only: the second write fails


# --- the builder ----------------------------------------------------------------------------------


def test_explorer_builder_shares_the_store_key_wrapper_with_exports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from neurosphere_api.runtime.builders import BuildContext
    from neurosphere_api.runtime.builders import interactions as interactions_builder
    from test_search import Composition, _snapshot  # pyright: ignore[reportMissingImports,reportPrivateUsage]

    monkeypatch.setenv("NS_AUTH_CUSTOMER_ID", CUSTOMER)
    composed = Composition(tmp_path, snapshot=_snapshot(enabled=False))
    explorer = composed.app.state.interaction_explorer
    assert isinstance(explorer, InteractionExplorer)
    assert explorer.exports is not None
    assert composed.app.state.interaction_export_off_reason is None
    store = explorer.store
    assert isinstance(store, InMemoryInteractionStore)
    # ONE key wrapper: the store's is the export's.
    assert explorer.exports.wrapper is store._wrapper  # pyright: ignore[reportPrivateUsage]
    ctx = BuildContext(composed.state, interactions_builder.BUILDER)
    first = interactions_builder.interaction_content_storage(ctx)
    second = interactions_builder.interaction_content_storage(ctx)
    assert first.container is second.container  # memoized
    assert first.wrapper is explorer.exports.wrapper
    assert first.kek_uri == explorer.exports.kek_uri


def test_explorer_builder_without_the_setting_installs_no_exports(tmp_path: Path) -> None:
    from test_search import Composition  # pyright: ignore[reportMissingImports]

    composed = Composition(tmp_path, snapshot=None)
    assert composed.app.state.interaction_explorer is None
    assert composed.app.state.interaction_export_off_reason == "explorer_off"
