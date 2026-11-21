"""PRP-139 item 2: random mixed stores never lose a real document (seeded, no network)."""

from __future__ import annotations

import copy
import random
from typing import Any

from test_purge_selection import ACTIVE, PURGE, gate, make_stores, real_docs, synthetic_docs

ITERATIONS = 150


def _mixed_store(
    rng: random.Random,
) -> tuple[dict[str, list[dict[str, Any]]], set[tuple[str, str]], set[tuple[str, str]]]:
    """Random store plus the (container, id) sets that are synthetic and real by construction."""
    data: dict[str, list[dict[str, Any]]] = {}
    synthetic: set[tuple[str, str]] = set()
    real: set[tuple[str, str]] = set()
    for container in gate.RULE_CONTAINERS:
        if container == gate.ARCHIVE:
            continue
        docs: list[dict[str, Any]] = []
        for n in range(rng.randint(0, 4)):
            if rng.random() < 0.5:
                doc = copy.deepcopy(synthetic_docs(n)[container])
                if container == "price_snapshots" and any(d["id"] == doc["id"] for d in docs):
                    continue
                if container == "reports" and any(d["id"] == doc["id"] for d in docs):
                    continue  # report ids are fixed by the seed
                docs.append(doc)
                synthetic.add((container, str(doc["id"])))
            else:
                doc = copy.deepcopy(rng.choice(real_docs(n)[container]))
                if any(d["id"] == doc["id"] for d in docs):
                    continue
                docs.append(doc)
                real.add((container, str(doc["id"])))
        data[container] = docs
    # a container the rule table never names, full of same-customer documents
    data["hitl_items"] = [
        {"id": f"h{i}", "customer_id": PURGE, "source": "sandbox"} for i in range(3)
    ]
    return data, synthetic, real


def test_no_real_document_is_ever_in_the_delete_set() -> None:
    rng = random.Random(139)
    for _ in range(ITERATIONS):
        data, synthetic, real = _mixed_store(rng)
        # drop synthetic/real id collisions (e.g. the shared price-snapshot id)
        real -= synthetic
        blobs = [f"{PURGE}/{i}" for i in range(rng.randint(0, 3))] + [
            f"{ACTIVE}/{i}" for i in range(rng.randint(0, 3))
        ]
        stores = make_stores(data, blobs)
        include_audit = rng.random() < 0.5
        counts, chosen = gate.count_selection(stores, PURGE, include_audit)

        selected = {
            (c, str(d.get("id", d.get("name")))) for c, docs in chosen.items() for d in docs
        }
        assert not selected & real
        audit = {k for k in synthetic if k[0] in gate.AUDIT_CONTAINERS}
        expected = (synthetic - (set() if include_audit else audit)) | {
            (gate.ARCHIVE, b) for b in blobs if b.startswith(PURGE + "/")
        }
        assert selected == expected

        result = gate.apply_purge(
            stores,
            chosen,
            purge_customer=PURGE,
            kept={c: v["kept"] for c, v in counts.items()},
            batch_size=rng.randint(1, 7),
        )
        assert not result.stopped
        deleted = {(c, i) for c, i in stores.documents.deleted} | {
            (gate.ARCHIVE, n) for n in stores.blobs.deleted
        }
        assert deleted == selected
        assert not deleted & real
        for container, ident in real:
            assert any(d["id"] == ident for d in stores.documents.data[container])
        assert [d["id"] for d in stores.documents.data["hitl_items"]] == ["h0", "h1", "h2"]
        assert all(n.startswith(ACTIVE + "/") for n in stores.blobs.names if n.startswith(ACTIVE))
        # real ones were counted kept (price snapshots and the archive are selected by id/prefix)
        for container, _ident in real:
            if container != "price_snapshots" and container in counts:
                assert counts[container]["kept"] >= 1


def test_mutating_any_one_marker_of_a_synthetic_document_unselects_it() -> None:
    markers = {
        "customer_id": ACTIVE,
        "source": "foundry",
        "arm_resource_id": "/x",
        "idempotency_key": "k",
        "created_at": "2027-01-01T00:00:00Z",
        "run_id": "live",
        "role_assignments": [{"assignment_id": "entra"}],
        "synthetic": False,
        "url": "https://example.com/mcp",
    }
    unselected = 0
    for container, doc in synthetic_docs().items():
        if container in gate.AUDIT_CONTAINERS or container == "reports":
            continue
        for key, value in markers.items():
            if key not in doc:
                continue
            mutated = {**doc, key: value}
            assert not gate.is_synthetic(container, mutated, PURGE), (container, key)
            unselected += 1
    assert unselected > 10
