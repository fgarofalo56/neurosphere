"""Secrecy of the producer admin routes (PRP-41 item 5): no secret or digest outside the one
show-once response, in logs, audit records, error bodies or stored documents beyond the digest."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from .test_admin_producers import (
    BASE,
    CONTOSO_CONTROL_OID,
    CREATE,
    bearer_for,
    install,
)
from .world import World


@pytest.fixture
def pworld(world: World) -> World:
    world.repos = install(world)  # type: ignore[attr-defined]
    return world


def audit_text(world: World) -> str:
    dep = world["contoso"]
    docs: list[dict[str, Any]] = []
    for chain in sorted({chain for (chain, _doc) in dep.audit_store._docs}):  # pyright: ignore[reportPrivateUsage]
        docs.extend(dep.audit_store.raw_documents(chain))
    return json.dumps(docs, sort_keys=True)


def test_no_secret_or_digest_leaks_through_create_rotate_and_failures(
    pworld: World, caplog: pytest.LogCaptureFixture
) -> None:
    dep = pworld["contoso"]
    headers = bearer_for(dep, CONTOSO_CONTROL_OID)
    with caplog.at_level(logging.DEBUG):
        created = dep.client.post(BASE, headers=headers, json=CREATE)
        assert created.status_code == 201, created.text
        first = created.json()
        etag = created.headers["etag"]
        rotated = dep.client.post(f"{BASE}/poller-1/rotate", headers={**headers, "If-Match": etag})
        assert rotated.status_code == 200, rotated.text
        second = rotated.json()
        # Failing writes: duplicate create, stale rotate, missing If-Match, unknown producer.
        failures = [
            dep.client.post(BASE, headers=headers, json=CREATE),
            dep.client.post(f"{BASE}/poller-1/rotate", headers={**headers, "If-Match": etag}),
            dep.client.post(f"{BASE}/poller-1/rotate", headers=headers),
            dep.client.post(f"{BASE}/nope/rotate", headers={**headers, "If-Match": etag}),
            dep.client.get(f"{BASE}/nope", headers=headers),
        ]
        reads = [
            dep.client.get(f"{BASE}/poller-1", headers=headers),
            dep.client.get(BASE, headers=headers),
        ]
    assert [r.status_code for r in failures] == [409, 409, 422, 404, 404]
    secrets_and_digests = [first["secret"], first["secret_sha256"], second["secret"]]
    secrets_and_digests.append(second["secret_sha256"])
    outputs = {
        "log": caplog.text,
        "audit": audit_text(pworld),
        "failure bodies": " ".join(r.text for r in failures),
        "read bodies": " ".join(r.text for r in reads),
    }
    for label, text in outputs.items():
        for value in secrets_and_digests:
            assert value not in text, f"{label} leaked a secret or digest"
    # The first response (create) and the rotate response each carry their own secret once.
    assert first["secret"] != second["secret"]
    stored = json.dumps(
        [d.model_dump(mode="json") for d in pworld.repos["contoso"]._docs.values()]  # type: ignore[attr-defined]  # pyright: ignore[reportPrivateUsage]
    )
    assert first["secret"] not in stored and second["secret"] not in stored
    assert second["secret_sha256"] in stored and first["secret_sha256"] not in stored
