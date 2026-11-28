"""PRP-104: records of another cloud (or customer) are refused on every path, even when the store
hands them back under this deployment's own customer and domain keys.

A Government record never answers a Commercial deployment: the hard constraint "never bridge
Government data to Commercial" applies to a mis-filed record as much as to a caller. The store
here holds a record whose ``cloud`` (or ``customer_id``) differs from the deployment's, filed
under the deployment's customer and the FINANCE domain, next to a normal record. The unexpired
FINANCE investigator then asks for it on every path: search and detail do not show it, the
content read is 404, the export never selects it, the replay payload branch attaches no body;
nothing of it is ever decrypted. The opposite direction (a caller of a deployment of another
cloud or customer) is the ``deployment-of-another-*`` rows of
``tests/security/authz/test_interaction_access.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import pytest

from ._world import (
    INVESTIGATOR,
    PURPOSE_PARAMS,
    World,
    canary,
    clean_env,
    new_id,
    payload_spans,
)

FOREIGN: Final = {
    "government-record": {"cloud": "government"},
    "other-customer-record": {"customer_id": "fabrikam"},
}


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    clean_env(monkeypatch)


def _world(tmp_path: Path, overrides: dict[str, Any]) -> tuple[World, str, str, str]:
    """A normal FINANCE record plus one whose index document claims another cloud or customer.

    The store refuses to WRITE a Government record under a Commercial key host, so the foreign
    record is written normally and its stored index document is then rewritten (as raw database
    access would): its sealed content still opens under its own keys, so only the explorer's
    cloud and customer checks stand between it and the investigator.
    """
    world = World(tmp_path)
    foreign_id, foreign_mark = new_id(), canary()
    world.put(foreign_id, foreign_mark)
    documents = world.store.index_backend.documents
    (key,) = [k for k in documents if k[2] == foreign_id]
    documents[key] = {**documents[key], **overrides}
    (own_id,), _ = world.seed_marked(1)
    return world, foreign_id, foreign_mark, own_id


def _decrypts_of(world: World, iid: str) -> int:
    return world.events.count(f"decrypt:{iid}")


@pytest.mark.parametrize("kind", sorted(FOREIGN))
def test_a_foreign_record_is_refused_on_every_path(tmp_path: Path, kind: str) -> None:
    world, foreign_id, mark, own_id = _world(tmp_path, FOREIGN[kind])

    listed = world.search(INVESTIGATOR)
    assert listed.status_code == 200, listed.text
    ids = [item["interaction_id"] for item in listed.json()["items"]]
    assert own_id in ids and foreign_id not in ids

    assert world.detail(INVESTIGATOR, foreign_id).status_code == 404
    read = world.read(INVESTIGATOR, foreign_id)
    assert read.status_code == 404, read.text
    assert read.json()["reason"] == "interaction_not_found"

    created = world.create(INVESTIGATOR)
    assert created.status_code == 201, created.text
    manifest = created.json()
    assert manifest["interaction_ids"] == [own_id]
    bundle = world.bundle(INVESTIGATOR, manifest["export_id"])
    assert bundle.status_code == 200
    assert foreign_id not in bundle.text

    replay = world.trace(INVESTIGATOR, include_payload="true", **PURPOSE_PARAMS)
    assert replay.status_code == 200, replay.text
    assert sum(p is not None for p in payload_spans(replay)) == 1  # the own record only

    for response in (listed, read, created, bundle, replay):
        assert mark not in response.text
    assert _decrypts_of(world, foreign_id) == 0
    assert _decrypts_of(world, own_id) == 2  # export + replay: the control really decrypts
    for record in world.all_audit_records():
        assert foreign_id not in record.model_dump_json()  # never listed as read or exported


def test_a_government_deployment_never_serves_a_commercial_record(tmp_path: Path) -> None:
    world, _, _, own_id = _world(tmp_path, FOREIGN["government-record"])
    world.retarget(cloud="government")
    before = world.counters()
    responses = [
        world.search(INVESTIGATOR),
        world.detail(INVESTIGATOR, own_id),
        world.read(INVESTIGATOR, own_id),
        world.create(INVESTIGATOR),
        world.trace(INVESTIGATOR, include_payload="true", **PURPOSE_PARAMS),
    ]
    statuses = [r.status_code for r in responses]
    assert statuses[2:4] == [403, 403], statuses
    assert all(s in (200, 403, 404) for s in statuses), statuses
    for response in responses:
        if response.status_code == 200 and "spans" in response.json():
            assert all(p is None for p in payload_spans(response))
        if response.status_code == 200 and "items" in response.json():
            assert response.json()["items"] == []
    assert world.counters()[:2] == before[:2]  # zero decrypts, zero unwraps
