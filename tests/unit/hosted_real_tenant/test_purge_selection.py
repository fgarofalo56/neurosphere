"""PRP-139 item 2: the closed rule table of ``is_synthetic`` and plan-time selection (no network).

This module also holds the in-memory store twins and document factories that the sibling
``test_purge_*`` modules import (the directory has no conftest: other lanes add files here).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "gates" / "hosted_purge_synthetic.py"
PURGE = "synthco"
ACTIVE = "contoso"
DEPLOYMENT = "demo-0001"


def load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("hosted_purge_synthetic_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = load_gate()
Doc = dict[str, Any]


# -- in-memory twins ----------------------------------------------------------------------------


class MemDocs:
    """Dict of container -> documents. Records every container that was opened."""

    def __init__(self, data: dict[str, list[Doc]]) -> None:
        self.data = {name: copy.deepcopy(docs) for name, docs in data.items()}
        self.opened: list[str] = []
        self.deleted: list[tuple[str, str]] = []
        self.scan_everything = True  # a real store may return a superset; so does the twin

    def scan(self, container: str, purge_customer: str) -> list[Doc]:
        self.opened.append(container)
        return copy.deepcopy(self.data.get(container, []))

    def fetch(self, container: str, doc_id: str) -> Doc | None:
        self.opened.append(container)
        found = [d for d in self.data.get(container, []) if d.get("id") == doc_id]
        return copy.deepcopy(found[0]) if found else None

    def reread(self, container: str, document: Any) -> Doc | None:
        self.opened.append(container)
        found = [d for d in self.data.get(container, []) if d.get("id") == document["id"]]
        return copy.deepcopy(found[0]) if found else None

    def delete(self, container: str, document: Any) -> None:
        self.deleted.append((container, str(document["id"])))
        self.data[container] = [d for d in self.data[container] if d.get("id") != document["id"]]


class MemBlobs:
    def __init__(self, names: list[str]) -> None:
        self.names = list(names)
        self.deleted: list[str] = []

    def list_prefix(self, prefix: str) -> list[str]:
        return [n for n in self.names if n.startswith(prefix)]

    def delete(self, name: str) -> None:
        self.deleted.append(name)
        self.names.remove(name)


def make_stores(data: dict[str, list[Doc]], blobs: list[str] | None = None) -> Any:
    return gate.Stores(documents=MemDocs(data), blobs=MemBlobs(blobs or []))


# -- document factories (synthetic, and real lookalikes that must survive) ------------------------


def _report_id(customer: str = PURGE) -> str:
    return sorted(gate.seed_markers(customer).report_ids)[0]


def _intent_key() -> str:
    return sorted(gate.seed_markers(PURGE).intent_keys)[0]


def synthetic_docs(n: int = 0) -> dict[str, Doc]:
    """One synthetic document per rule-table container (``n`` makes ids unique)."""
    sid = f"commercial:{PURGE}:sandbox:thing:{n}"
    base = {"customer_id": PURGE}
    return {
        **{c: {"id": sid, "source": "sandbox", **base} for c in gate.SOURCE_CONTAINERS},
        "policy": {
            "id": f"principal-{n}",
            "doc_type": "principal_policy",
            "role_assignments": [{"assignment_id": "operator-viewer"}],
            **base,
        },
        "price_snapshots": {"id": gate.SEED_PRICE_SNAPSHOT_ID, "synthetic": True},
        "gateways": {"id": f"gw-{n}", "arm_resource_id": gate.SEED_GATEWAY_ARM_ID, **base},
        "reports": {"id": _report_id(), **base},
        "action_intents": {"id": f"intent-{n}", "idempotency_key": _intent_key(), **base},
        "recommendations": {
            "id": f"rec-{n}",
            "created_at": "2026-10-19T12:00:00Z",
            **base,
        },
        "evaluation_runs": {"id": f"run-{n}", "run_id": "seed-offline-001", **base},
        "evaluation_results": {"id": f"res-{n}", "run_id": "seed-offline-002", **base},
        "mcp_servers": {"id": f"mcp-{n}", "url": "https://mcp-docs.synthetic.invalid/mcp"},
        "audit": {"id": f"a-{n}", "chain_id": f"chain-{n}", **base},
        "audit_tail": {"id": f"t-{n}", "chain_id": f"chain-{n}", **base},
    }


def real_docs(n: int = 0) -> dict[str, list[Doc]]:
    """Per container, documents the purge must never select."""
    out: dict[str, list[Doc]] = {}
    for container, doc in synthetic_docs(n).items():
        variants: list[Doc] = []
        other = {**doc, "customer_id": ACTIVE, "id": f"real-{container}-{n}"}
        if container in gate.SOURCE_CONTAINERS:
            other["id"] = f"commercial:{ACTIVE}:sandbox:thing:{n}"
            variants.append(other)
            variants.append(
                {
                    "id": f"commercial:{PURGE}:foundry:thing:{n}",
                    "customer_id": PURGE,
                    "source": "foundry",
                }
            )
        elif container == "price_snapshots":
            variants.append({"id": "prices-2026-11", "synthetic": False})
            variants.append({"id": gate.SEED_PRICE_SNAPSHOT_ID, "synthetic": False})
        elif container == "mcp_servers":
            variants.append({"id": f"mcp-real-{n}", "url": "https://mcp.contoso.com/mcp"})
        elif container in gate.AUDIT_CONTAINERS:
            variants.append(other)  # audit is selected by customer alone, and only on opt-in
        else:
            variants.append(other)
            # same customer, but not one of the seed's own records
            same = copy.deepcopy(doc)
            same["id"] = f"keep-{container}-{n}"
            for key, value in (
                ("role_assignments", [{"assignment_id": "entra-admin"}]),
                ("arm_resource_id", "/subscriptions/x/real"),
                ("idempotency_key", "user-key"),
                ("created_at", "2026-11-20T09:00:00Z"),
                ("run_id", "live-run-1"),
            ):
                if key in same:
                    same[key] = value
            if container == "reports":
                same["id"] = "a-user-report"
            variants.append(same)
        out[container] = variants
    return out


# -- tests -------------------------------------------------------------------------------------


def test_every_synthetic_factory_document_is_selected() -> None:
    for container, doc in synthetic_docs().items():
        assert gate.is_synthetic(container, doc, PURGE), container


def test_every_real_lookalike_is_rejected() -> None:
    for container, docs in real_docs().items():
        for doc in docs:
            assert not gate.is_synthetic(container, doc, PURGE), (container, doc)


def test_the_rule_table_is_closed() -> None:
    assert set(gate.RULE_CONTAINERS) == {
        *gate.SOURCE_CONTAINERS,
        *gate.SEED_CONTAINERS,
        *gate.AUDIT_CONTAINERS,
        gate.ARCHIVE,
    }
    for name in ("hitl_items", "admin_config", "copilot_conversations", "revocations", "nope"):
        assert name not in gate.RULE_CONTAINERS
        doc = {"id": "x", "customer_id": PURGE, "source": "sandbox", "name": f"{PURGE}/x"}
        assert not gate.is_synthetic(name, doc, PURGE)


def test_empty_purge_customer_selects_nothing() -> None:
    for container, doc in synthetic_docs().items():
        assert not gate.is_synthetic(container, doc, "")


def test_a_document_of_another_customer_is_never_synthetic_for_the_purge_customer() -> None:
    for container, doc in synthetic_docs().items():
        if container in ("price_snapshots", "mcp_servers"):
            continue  # global by id/host
        moved = {**doc, "customer_id": ACTIVE}
        moved.pop("source", None)
        if container in gate.SOURCE_CONTAINERS:
            moved["id"] = f"commercial:{ACTIVE}:sandbox:t"
            moved["source"] = "sandbox"
        assert not gate.is_synthetic(container, moved, PURGE), container


def test_source_field_wins_over_an_id_that_says_sandbox() -> None:
    doc = {"id": f"commercial:{PURGE}:sandbox:t", "customer_id": PURGE, "source": "foundry"}
    assert not gate.is_synthetic("catalog", doc, PURGE)


def test_archive_rule_is_the_customer_prefix() -> None:
    assert gate.is_synthetic("archive", {"name": f"{PURGE}/2026/a.json"}, PURGE)
    assert not gate.is_synthetic("archive", {"name": f"{PURGE}x/a.json"}, PURGE)
    assert not gate.is_synthetic("archive", {"name": f"{ACTIVE}/a.json"}, PURGE)


def test_plan_selection_counts_synthetic_and_keeps_real() -> None:
    data: dict[str, list[Doc]] = {}
    for container, doc in synthetic_docs().items():
        data[container] = [doc, *real_docs()[container]]
    stores = make_stores(data, [f"{PURGE}/a", f"{ACTIVE}/b"])
    counts, chosen = gate.count_selection(stores, PURGE, include_audit=True)
    assert set(counts) == {*gate.RULE_CONTAINERS}
    for container in gate.SOURCE_CONTAINERS:
        assert counts[container] == {"selected": 1, "kept": 2}
    assert counts["price_snapshots"] == {"selected": 1, "kept": 0}  # selected by id, not scan
    assert counts["archive"] == {"selected": 1, "kept": 0}
    assert [d["name"] for d in chosen["archive"]] == [f"{PURGE}/a"]
    assert stores.documents.deleted == []


def test_audit_containers_are_not_opened_without_include_audit() -> None:
    stores = make_stores({c: [d] for c, d in synthetic_docs().items()})
    counts, _ = gate.count_selection(stores, PURGE, include_audit=False)
    assert "audit" not in counts and "audit_tail" not in counts
    assert "audit" not in stores.documents.opened
    assert set(stores.documents.opened) <= set(gate.RULE_CONTAINERS) - set(gate.AUDIT_CONTAINERS)


def test_a_container_outside_the_table_is_never_opened() -> None:
    data = {c: [d] for c, d in synthetic_docs().items()}
    data["hitl_items"] = [{"id": "h", "customer_id": PURGE}]
    stores = make_stores(data)
    gate.count_selection(stores, PURGE, include_audit=True)
    assert "hitl_items" not in stores.documents.opened


def test_price_snapshot_is_fetched_by_id_never_scanned() -> None:
    class Spy(MemDocs):
        def scan(self, container: str, purge_customer: str) -> list[Doc]:
            assert container != "price_snapshots", "price snapshots must not be partition-scanned"
            return super().scan(container, purge_customer)

    stores = gate.Stores(
        documents=Spy({"price_snapshots": [synthetic_docs()["price_snapshots"]]}),
        blobs=MemBlobs([]),
    )
    counts, _ = gate.count_selection(stores, PURGE, include_audit=False)
    assert counts["price_snapshots"]["selected"] == 1


def test_seed_markers_are_the_ids_the_seed_computes() -> None:
    markers = gate.seed_markers(PURGE)
    assert len(markers.report_ids) == 3 and len(markers.intent_keys) == 4
    assert "mcp-docs.synthetic.invalid" in markers.mcp_hosts
    # another customer id yields other report ids (they are uuid5 over customer and slug)
    assert gate.seed_markers(ACTIVE).report_ids.isdisjoint(markers.report_ids)


@pytest.mark.parametrize(
    ("path", "needle"),
    [
        ("sandbox/config.py", 'PRICE_VERSION = "sandbox-prices-2026-10"'),
        ("scripts/sandbox/sbx_seed_stack.py", 'RUN_PREFIX: Final = "seed-offline-"'),
        (
            "scripts/sandbox/sbx_seed_stack.py",
            "CREATED_AT: Final = datetime(2026, 10, 19, 12, 0, 0",
        ),
        ("scripts/sandbox/sbx_grant_operator.py", 'ASSIGNMENT_PREFIX: Final = "operator-"'),
        ("scripts/sandbox/sbx_seed_stack.py", "rg-synthetic-sandbox"),
        ("scripts/sandbox/sbx_seed_stack.py", "apim-synthetic-sandbox"),
        ("scripts/sandbox/sbx_seed_stack.py", "00000000-0000-4000-8000-000000000001"),
    ],
)
def test_hardcoded_seed_constants_still_match_their_source(path: str, needle: str) -> None:
    assert needle in (REPO / path).read_text(encoding="utf-8")


def test_seed_constants_in_the_gate_equal_the_documented_values() -> None:
    assert gate.SEED_PRICE_SNAPSHOT_ID == "sandbox-prices-2026-10"
    assert gate.SEED_RUN_PREFIX == "seed-offline-"
    assert gate.SEED_ASSIGNMENT_PREFIX == "operator-"
    assert gate.SEED_CREATED_AT_PREFIX == "2026-10-19T12:00:00"
    assert re.fullmatch(r"/subscriptions/0{8}-.*apim-synthetic-sandbox", gate.SEED_GATEWAY_ARM_ID)


def test_policy_head_is_synthetic_only_with_a_seed_version() -> None:
    head = {"id": "policy-head", "doc_type": "policy_head", "customer_id": PURGE}
    assert gate.is_synthetic("policy", {**head, "policy_version": "local-3"}, PURGE)
    assert not gate.is_synthetic("policy", {**head, "policy_version": "v2026-11"}, PURGE)
    json.dumps(head)  # plain data
