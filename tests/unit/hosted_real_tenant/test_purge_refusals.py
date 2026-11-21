"""PRP-139 item 2: every refusal of ``hosted_purge_synthetic.py apply`` (no network)."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from test_purge_selection import (
    ACTIVE,
    DEPLOYMENT,
    PURGE,
    gate,
    make_stores,
    real_docs,
    synthetic_docs,
)

NOW = datetime(2026, 11, 21, 12, 0, 0, tzinfo=UTC)


def _registration(tmp_path: Path, **extra: Any) -> Path:
    doc: dict[str, Any] = {
        "schema": 1,
        "deployment_id": DEPLOYMENT,
        "cloud": "AzureCloud",
        "cosmos_host": "nsdemo-cosmos.documents.azure.com",
        "eventhubs_host": "nsdemo-ehns.servicebus.windows.net",
        "blob_host": "nsdemoarchive.blob.core.windows.net",
        "key_vault_host": "nsdemo-kv.vault.azure.net",
        "database": "neurosphere",
        "archive_container": "ns-archive",
        "customer_id": ACTIVE,
        "data_mode": "real-tenant",
    }
    doc.update(extra)
    path = tmp_path / "registration.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _env(**extra: str) -> dict[str, str]:
    env = {"NS_LIVE_APPROVED": "1", "NS_SANDBOX_HOSTED_DEPLOYMENT_ID": DEPLOYMENT}
    env.update(extra)
    return env


def _data() -> dict[str, list[dict[str, Any]]]:
    data = {c: [d] for c, d in synthetic_docs().items()}
    for container, docs in real_docs().items():
        data[container].extend(docs)
    return data


class Harness:
    def __init__(self, tmp_path: Path, **registration: Any) -> None:
        self.tmp = tmp_path
        self.registration = _registration(tmp_path, **registration)
        self.stores = make_stores(_data(), [f"{PURGE}/a", f"{ACTIVE}/b"])
        self.factory_calls = 0

    def factory(self, _registration: Any) -> Any:
        self.factory_calls += 1
        return self.stores

    def run(
        self, command: str, *extra: str, env: dict[str, str] | None = None, now: datetime = NOW
    ) -> int:
        argv = [
            "--registration",
            str(self.registration),
            "--plan-file",
            str(self.tmp / "plan.json"),
            "--evidence-dir",
            str(self.tmp / "evidence"),
            command,
            *extra,
        ]
        return gate.main(argv, env=env or _env(), stores_factory=self.factory, now=now)

    def apply(self, *extra: str, **kw: Any) -> int:
        return self.run("apply", "--confirm", DEPLOYMENT, *extra, **kw)

    def deleted(self) -> int:
        return len(self.stores.documents.deleted) + len(self.stores.blobs.deleted)


@pytest.fixture
def h(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def test_plan_then_apply_deletes_only_synthetic(h: Harness) -> None:
    assert h.run("plan") == 0
    assert h.deleted() == 0
    assert h.apply() == 0
    assert h.deleted() > 0
    remaining = h.stores.documents.data
    for container, docs in real_docs().items():
        for doc in docs:
            if container == "price_snapshots" and doc["id"] == synthetic_docs()[container]["id"]:
                continue  # same id as the synthetic snapshot: fetched by id, replaced by design
            assert any(d["id"] == doc["id"] for d in remaining[container]), (container, doc)
    assert h.stores.blobs.names == [f"{ACTIVE}/b"]


def test_apply_without_approval_exits_2_before_any_store_is_built(h: Harness) -> None:
    env = _env()
    del env["NS_LIVE_APPROVED"]
    assert h.run("plan") == 0  # a valid plan exists; approval alone still refuses
    before = h.factory_calls
    assert h.apply(env=env) == 2
    assert h.factory_calls == before
    assert h.deleted() == 0


def test_refusal_imports_no_azure_client(h: Harness) -> None:
    names = ("azure.cosmos", "azure.identity", "azure.storage.blob")
    before = {n for n in names if n in sys.modules}
    env = _env()
    del env["NS_LIVE_APPROVED"]
    assert h.apply(env=env) == 2
    assert {n for n in names if n in sys.modules} == before


def test_confirm_must_equal_the_deployment_id(h: Harness) -> None:
    assert h.run("plan") == 0
    assert h.run("apply", "--confirm", "other") == 2
    assert h.run("apply") == 2
    assert h.deleted() == 0


def test_active_mode_must_be_real_tenant(tmp_path: Path) -> None:
    for mode in ("demo", None):
        h = Harness(tmp_path, data_mode=mode)
        assert h.run("plan") == 2 and h.apply() == 2
        assert h.factory_calls == 0 and h.deleted() == 0


def test_purge_customer_equal_to_active_customer_is_refused(tmp_path: Path) -> None:
    h = Harness(tmp_path, customer_id=PURGE)
    assert h.run("plan") == 2 and h.apply() == 2
    assert h.factory_calls == 0
    h = Harness(tmp_path, customer_id="other", previous_customer_id="other")
    assert h.apply() == 2 and h.factory_calls == 0


def test_previous_customer_id_changes_the_purge_customer(tmp_path: Path) -> None:
    h = Harness(tmp_path, previous_customer_id="legacyco")
    assert h.run("plan") == 0
    counts = json.loads((tmp_path / "plan.json").read_text("utf-8"))["counts"]
    assert counts["catalog"]["selected"] == 0  # synthco documents are not legacyco's


def test_endpoint_guard_refusals(tmp_path: Path) -> None:
    h = Harness(tmp_path, cosmos_host="localhost")
    assert h.run("plan") == 2 and h.apply() == 2 and h.factory_calls == 0
    h = Harness(tmp_path)
    assert h.run("plan", env=_env(NS_SANDBOX_HOSTED_DEPLOYMENT_ID="other")) == 2
    assert h.factory_calls == 0
    secret_env = _env(**{"NS_COSMOS_" + "KEY": "x"})
    assert h.run("plan", env=secret_env) == 2 and h.factory_calls == 0


def test_apply_without_a_plan_is_refused(h: Harness) -> None:
    assert h.apply() == 2 and h.factory_calls == 0


def test_plan_older_than_24_hours_is_refused(h: Harness) -> None:
    assert h.run("plan") == 0
    assert h.apply(now=NOW + timedelta(hours=24, minutes=1)) == 2
    assert h.deleted() == 0
    assert h.apply(now=NOW + timedelta(hours=23)) == 0


def test_edited_plan_is_refused(h: Harness) -> None:
    assert h.run("plan") == 0
    path = h.tmp / "plan.json"
    plan = json.loads(path.read_text("utf-8"))
    plan["counts"]["catalog"]["selected"] += 1
    path.write_text(json.dumps(plan), encoding="utf-8")
    assert h.apply() == 2 and h.deleted() == 0


def test_plan_for_another_audit_setting_is_refused(h: Harness) -> None:
    assert h.run("plan") == 0
    argv = [
        "--registration",
        str(h.registration),
        "--plan-file",
        str(h.tmp / "plan.json"),
        "--evidence-dir",
        str(h.tmp / "evidence"),
        "--include-audit",
        "apply",
        "--confirm",
        DEPLOYMENT,
    ]
    assert gate.main(argv, env=_env(), stores_factory=h.factory, now=NOW) == 2
    assert h.deleted() == 0


def test_counts_that_changed_since_the_plan_are_refused(h: Harness) -> None:
    assert h.run("plan") == 0
    h.stores.documents.data["catalog"].append(
        {
            "id": f"commercial:{PURGE}:sandbox:late",
            "customer_id": PURGE,
            "source": "sandbox",
        }
    )
    assert h.apply() == 2
    assert h.deleted() == 0


def test_a_document_that_stops_being_synthetic_stops_the_purge(h: Harness) -> None:
    assert h.run("plan") == 0
    docs = h.stores.documents

    original = docs.reread

    def flip(container: str, document: Any) -> Any:
        found = original(container, document)
        if container == "aggregates" and found is not None:
            found["source"] = "foundry"  # changed between plan and delete
        return found

    docs.reread = flip  # type: ignore[method-assign]
    assert h.apply() == 1
    assert ("aggregates", f"commercial:{PURGE}:sandbox:thing:0") not in docs.deleted
    evidence = json.loads(next((h.tmp / "evidence").glob("*-purge.json")).read_text("utf-8"))
    assert evidence["counts"]["aggregates"]["deleted"] == 0


def test_a_document_that_vanished_is_skipped_not_fatal(h: Harness) -> None:
    assert h.run("plan") == 0
    docs = h.stores.documents
    original = docs.reread

    def gone(container: str, document: Any) -> Any:
        return None if container == "catalog" else original(container, document)

    docs.reread = gone  # type: ignore[method-assign]
    assert h.apply() == 0
    evidence = json.loads(next((h.tmp / "evidence").glob("*-purge.json")).read_text("utf-8"))
    assert evidence["counts"]["catalog"]["skipped"] == 1


def test_batch_size_is_bounded(h: Harness) -> None:
    assert h.run("plan") == 0
    assert h.apply("--batch-size", "0") == 2
    assert h.apply("--batch-size", str(gate.MAX_BATCH + 1)) == 2
    assert h.deleted() == 0


def test_audit_chains_are_kept_unless_asked(h: Harness) -> None:
    assert h.run("plan") == 0
    assert h.apply() == 0
    assert all(c not in ("audit", "audit_tail") for c, _ in h.stores.documents.deleted)
    assert any(d["id"] == "a-0" for d in h.stores.documents.data["audit"])


def test_the_parser_accepts_no_key_or_connection_string_option() -> None:
    options = {o for a in gate.build_parser()._actions for o in a.option_strings}  # pyright: ignore[reportPrivateUsage]
    assert not {o for o in options if "key" in o or "connection" in o}
