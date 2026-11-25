"""The ``interaction`` lifecycle target: mapping, listing, export, pseudonymize, registration."""

from __future__ import annotations

import json
from typing import Any, cast

import pytest
from neurosphere_core.errors import CapabilityUnavailableError
from neurosphere_core.interactions import (
    DATA_CLASS_INTERACTION,
    InMemoryInteractionContent,
    InMemoryInteractionIndex,
    InteractionStoreError,
)
from neurosphere_core.interactions.lifecycle_delete import (
    KIND_INTERACTION,
    InteractionLifecycleBackend,
    interaction_record_id,
    interaction_target,
    parse_interaction_record_id,
)
from neurosphere_core.lifecycle import (
    ActionKind,
    Effect,
    ExportRequest,
    JobStatus,
    LawfulBasis,
    LifecycleRequest,
    TargetRef,
)
from neurosphere_core.lifecycle.targets import LifecycleTarget
from neurosphere_workers.lifecycle.assembly import build_targets

from .interaction_rig import (
    CAPTURED,
    CONTAINER,
    CUSTOMER,
    DOMAIN,
    SLASH_DOMAIN,
    Rig,
    canary,
    make_ctx,
    make_scope,
    principal,
)


def _ref(record_id: str) -> TargetRef:
    return TargetRef(target_kind=KIND_INTERACTION, container=CONTAINER, record_id=record_id)


# -- record ids and mapping -----------------------------------------------------------------------


def test_record_ids_round_trip_including_a_domain_with_a_slash() -> None:
    iid = "0b0f6c1e-1f2a-4c3d-8e9f-0a1b2c3d4e5f"
    for domain in (DOMAIN, SLASH_DOMAIN):
        assert parse_interaction_record_id(interaction_record_id(iid, domain)) == (iid, domain)
    for bad in ("", iid, iid + "/", "x" * 36 + "/" + DOMAIN, iid.upper() + "/" + DOMAIN, 7):
        assert parse_interaction_record_id(bad) is None
    with pytest.raises(ValueError):
        interaction_record_id("not-a-uuid", DOMAIN)


async def test_target_satisfies_the_protocol_and_maps_hold_selectors(rig: Rig) -> None:
    assert isinstance(rig.target, LifecycleTarget)
    assert (rig.target.target_kind, rig.target.container) == (KIND_INTERACTION, CONTAINER)
    alice = principal("alice")
    record_id = await rig.seed(domain_id=SLASH_DOMAIN, principal_id=alice)
    record = await rig.target.get(record_id)
    assert record is not None
    assert record.record_id == record_id
    assert record.data_class == DATA_CLASS_INTERACTION
    assert record.created_at == CAPTURED
    assert record.subject_id == alice
    assert (record.customer_id, record.domain_id) == (CUSTOMER, SLASH_DOMAIN)
    assert record.doc_type == "interaction"
    assert record.pseudonymized is False


async def test_unknown_malformed_and_foreign_ids_read_as_absent(rig: Rig) -> None:
    record_id = await rig.seed()
    assert await rig.target.get("not-a-record") is None
    missing = interaction_record_id("00000000-0000-4000-8000-000000000000", DOMAIN)
    assert await rig.target.get(missing) is None
    other = interaction_target(
        CONTAINER, InteractionLifecycleBackend(rig.index, rig.content, customer_id="globex")
    )
    assert await other.get(record_id) is None
    assert await other.list_records(data_class=DATA_CLASS_INTERACTION, limit=10, after=None) == []
    await other.delete(record_id)  # another customer's target cannot reach it
    assert rig.has_index(record_id)
    assert rig.has_blob(record_id)


def test_the_audit_container_and_a_bad_customer_are_refused() -> None:
    backend = InteractionLifecycleBackend(
        InMemoryInteractionIndex(), InMemoryInteractionContent(), customer_id=CUSTOMER
    )
    with pytest.raises(ValueError):
        interaction_target("audit", backend)
    for bad in ("", "a/b", "a\\b"):
        with pytest.raises(ValueError):
            InteractionLifecycleBackend(
                InMemoryInteractionIndex(), InMemoryInteractionContent(), customer_id=bad
            )


# -- listing ------------------------------------------------------------------------------------


async def test_list_records_pages_past_the_index_page_bound(rig: Rig) -> None:
    for _ in range(130):
        await rig.seed()
    assert await rig.target.list_records(data_class="telemetry", limit=10, after=None) == []
    first = await rig.target.list_records(data_class=DATA_CLASS_INTERACTION, limit=120, after=None)
    assert len(first) == 120  # more than one index page (max 100) was read
    ids = [r.record_id for r in first]
    assert ids == sorted(ids)
    rest = await rig.target.list_records(
        data_class=DATA_CLASS_INTERACTION, limit=120, after=ids[-1]
    )
    assert len(rest) == 10
    assert {r.record_id for r in first} | {r.record_id for r in rest} == set(rig.seeded)


async def test_list_by_subject_returns_only_that_principals_records(rig: Rig) -> None:
    alice, bob = principal("alice"), principal("bob")
    mine = {await rig.seed(principal_id=alice), await rig.seed(principal_id=alice)}
    await rig.seed(principal_id=bob)
    await rig.seed()
    found = await rig.target.list_by_subject(alice, limit=200, after=None)
    assert {r.record_id for r in found} == mine
    assert all(r.subject_id == alice for r in found)
    first = sorted(mine)[0]
    after = await rig.target.list_by_subject(alice, limit=200, after=first)
    assert [r.record_id for r in after] == sorted(mine)[1:]


async def test_subject_listing_fails_closed_on_an_unaddressable_record(rig: Rig) -> None:
    alice = principal("alice")
    long_domain = DOMAIN + "/" + "x" * (500 - len(DOMAIN))
    await rig.seed(principal_id=alice)
    await rig.seed(principal_id=alice, domain_id=long_domain)
    # Expiry paging may skip it (counted), but a subject request must not miss it silently.
    with pytest.raises(CapabilityUnavailableError) as caught:
        await rig.target.list_by_subject(alice, limit=200, after=None)
    assert caught.value.reason == "interaction_record_id_too_long"
    listed = await rig.target.list_records(data_class=DATA_CLASS_INTERACTION, limit=10, after=None)
    assert len(listed) == 1


# -- delete ---------------------------------------------------------------------------------------


async def test_delete_removes_blob_and_index_and_is_idempotent(rig: Rig) -> None:
    record_id = await rig.seed()
    await rig.target.delete(record_id)
    assert not rig.has_blob(record_id)
    assert not rig.has_index(record_id)
    await rig.target.delete(record_id)  # a rerun is a no-op
    await rig.target.delete("not-a-record")


# -- export ---------------------------------------------------------------------------------------


async def test_export_is_metadata_only_and_never_decrypts(rig: Rig) -> None:
    secret_text = canary()
    alice = principal("alice")
    record_id = await rig.seed(principal_id=alice, text="note " + secret_text)
    exported = dict(await rig.target.export(record_id))
    assert exported["interaction_id"] == rig.seeded[record_id].interaction_id.root
    assert exported["content_stored"] is True
    assert "content_ref" not in exported
    assert "parts" in exported  # sizes only (contract ContentParts)
    dumped = json.dumps(exported)
    assert secret_text not in dumped
    assert rig.blob_name(record_id) not in dumped
    assert "vault" not in dumped
    assert await rig.target.export("not-a-record") == {}

    result = await rig.engine.export(
        ExportRequest(
            lawful_basis=LawfulBasis.LEGAL_OBLIGATION,
            target_kind=KIND_INTERACTION,
            container=CONTAINER,
            record_ids=(record_id,),
        ),
        make_scope(),
        make_ctx(),
    )
    assert result.status is JobStatus.COMPLETED
    assert len(result.items) == 1
    assert secret_text not in json.dumps(result.items[0].content)
    assert rig.wrapper.unwrap_calls == 0


# -- pseudonymize ---------------------------------------------------------------------------------


async def test_pseudonymize_deletes_the_blob_and_clears_the_subject(rig: Rig) -> None:
    alice = principal("alice")
    record_id = await rig.seed(principal_id=alice)
    stored = rig.seeded[record_id]
    request = LifecycleRequest(action=ActionKind.PSEUDONYMIZE, target=_ref(record_id))
    outcome = await rig.engine.submit(request, make_ctx())
    assert outcome.status is JobStatus.COMPLETED
    assert outcome.effect is Effect.PSEUDONYMIZED
    assert outcome.verified is True
    assert not rig.has_blob(record_id)
    assert rig.has_index(record_id)
    after = await rig.target.get(record_id)
    assert after is not None
    assert after.pseudonymized is True
    assert after.subject_id is None
    doc: dict[str, Any] = rig.index.documents[(CUSTOMER, DOMAIN, stored.interaction_id.root)]
    assert doc["principal_id"] is None
    assert doc["content_ref"] is None
    assert alice not in json.dumps(doc)
    with pytest.raises(InteractionStoreError) as caught:
        await rig.store.read_content(CUSTOMER, DOMAIN, stored.interaction_id.root)
    assert caught.value.reason == "content_purged"
    assert await rig.target.list_by_subject(alice, limit=10, after=None) == []
    await rig.target.pseudonymize(record_id)  # idempotent
    assert rig.wrapper.unwrap_calls == 0


async def test_pseudonymize_without_a_principal_still_drops_the_content(rig: Rig) -> None:
    record_id = await rig.seed()
    request = LifecycleRequest(action=ActionKind.PSEUDONYMIZE, target=_ref(record_id))
    outcome = await rig.engine.submit(request, make_ctx())
    assert outcome.effect is Effect.PSEUDONYMIZED
    assert not rig.has_blob(record_id)
    after = await rig.target.get(record_id)
    assert after is not None and after.pseudonymized is True


# -- registration -------------------------------------------------------------------------------


def test_build_targets_without_interaction_backends_registers_nothing_new() -> None:
    registry = build_targets(cloud="commercial", customer_id=CUSTOMER)
    assert registry.targets() == []
    assert registry.get(KIND_INTERACTION, "interaction_index") is None


def test_build_targets_with_interaction_backends_registers_the_target() -> None:
    registry = build_targets(
        cloud="commercial",
        customer_id=CUSTOMER,
        interaction_index=InMemoryInteractionIndex(),
        interaction_blobs=InMemoryInteractionContent(),
    )
    target = registry.get(KIND_INTERACTION, "interaction_index")
    assert target is not None
    assert [t.target_kind for t in registry.targets()] == [KIND_INTERACTION]


def test_build_targets_refuses_half_an_interaction_store() -> None:
    with pytest.raises(ValueError):
        build_targets(
            cloud="commercial", customer_id=CUSTOMER, interaction_index=InMemoryInteractionIndex()
        )
    with pytest.raises(ValueError):
        build_targets(
            cloud="commercial",
            customer_id=CUSTOMER,
            interaction_blobs=cast(Any, InMemoryInteractionContent()),
        )


def test_build_targets_refuses_the_audit_container_for_interactions() -> None:
    with pytest.raises(ValueError):
        build_targets(
            cloud="commercial",
            customer_id=CUSTOMER,
            interaction_index=InMemoryInteractionIndex(),
            interaction_blobs=InMemoryInteractionContent(),
            interaction_name="audit",
        )
