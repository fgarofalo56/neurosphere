"""PRP-104 item 4: content under legal hold is exportable, and an export deletes nothing.

Criterion 5: "Held content is exportable; nothing in this PRP deletes content." An export of held
interactions carries their stored redacted content, says ``includes_held_content: true``, and
leaves every interaction record and content blob in place, also after the export itself expires
and its own blobs are deleted. Harness from ``test_export``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from neurosphere_api.interactions import EXPORT_TTL
from neurosphere_contracts.interactions.v1.interaction_export_manifest import (
    InteractionExportManifest,
)
from neurosphere_core.interactions import InMemoryInteractionStore
from test_content_read import (  # pyright: ignore[reportMissingImports]
    CUSTOMER,
    FINANCE,
    INVESTIGATOR,
    new_id,
    record_doc,
)
from test_export import ExportApi  # pyright: ignore[reportMissingImports]

HOLD = "hold-2026-0007"


@pytest.fixture
def api(tmp_path: Path) -> ExportApi:
    return ExportApi(tmp_path)


def test_held_content_is_exported_and_flagged(api: ExportApi) -> None:
    held, free = new_id(), new_id()
    held_mark, _ = api.seed_records(record_doc(held, legal_hold_ids=[HOLD]), record_doc(free))
    response = api.create(INVESTIGATOR)
    assert response.status_code == 201, response.text
    manifest = InteractionExportManifest.model_validate(response.json())
    assert manifest.includes_held_content is True
    assert {i.root for i in manifest.interaction_ids} == {held, free}
    assert manifest.excluded_count == 0  # held content is not excluded

    download = api.bundle(INVESTIGATOR, manifest.export_id.root)
    assert download.status_code == 200
    bundle = json.loads(download.content)
    assert held_mark in json.dumps(bundle["interactions"][held])


def test_export_without_held_content_says_so(api: ExportApi) -> None:
    api.seed_records(record_doc(new_id()))
    assert api.created().includes_held_content is False


def test_export_deletes_no_interaction_content(api: ExportApi) -> None:
    ids = [new_id(), new_id()]
    api.seed_records(record_doc(ids[0], legal_hold_ids=[HOLD]), record_doc(ids[1]))
    before = dict(api.store.content_backend.blobs)
    assert len(before) == 2

    manifest = api.created()
    assert api.bundle(INVESTIGATOR, manifest.export_id.root).status_code == 200
    # The export expires: its own blobs go, the interactions stay.
    api.h.clock.advance(EXPORT_TTL.total_seconds())
    assert api.manifest(INVESTIGATOR, manifest.export_id.root).status_code == 404
    assert api.backend.blobs == {}

    assert api.store.content_backend.blobs == before
    for iid in ids:
        record = asyncio.run(api.store.get_metadata(CUSTOMER, FINANCE, iid))
        assert record is not None and record.content_ref is not None
        content = asyncio.run(
            InMemoryInteractionStore.read_content(api.store, CUSTOMER, FINANCE, iid)
        )
        assert content.interaction_id.root == iid


def test_export_module_never_calls_a_delete_on_the_store() -> None:
    """Structural: the export code has no path to ``InteractionStore.delete``."""
    import inspect

    import neurosphere_api.interactions.export as export_module

    source = inspect.getsource(export_module)
    assert "store.delete" not in source
    assert ".purge" not in source
