"""PRP-139 item 2: purge evidence holds counts only (no GUID, host, id or token)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from test_purge_refusals import NOW, Harness
from test_purge_selection import ACTIVE, DEPLOYMENT, PURGE, gate

GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
FORBIDDEN = (
    "http",
    ".azure.",
    ".windows.net",
    "subscriptions",
    "Bearer",
    "token",
    DEPLOYMENT,
    PURGE,
    ACTIVE,
    "chain-",
    "sandbox:",
    "nsdemo",
)


def _assert_clean(text: str) -> None:
    assert GUID.search(text) is None
    for word in FORBIDDEN:
        assert word not in text, word


def test_plan_and_apply_evidence_are_counts_only(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    assert h.run("plan") == 0
    assert h.apply() == 0
    files = sorted((tmp_path / "evidence").glob("*.json"))
    assert [f.name for f in files] == ["2026-11-21-purge-plan.json", "2026-11-21-purge.json"]
    for path in files:
        text = path.read_text(encoding="utf-8")
        _assert_clean(text)
        doc = json.loads(text)
        assert doc["gate"] == "hosted_purge_synthetic"
        for counts in doc["counts"].values():
            assert all(isinstance(v, int) for v in counts.values())
    applied = json.loads(files[1].read_text(encoding="utf-8"))
    assert applied["kind"] == "apply"
    for counts in applied["counts"].values():
        assert set(counts) == {"deleted", "kept", "skipped"}
    assert applied["counts"]["catalog"] == {"deleted": 1, "kept": 2, "skipped": 0}


def test_write_evidence_names_files_by_date_and_sorts_keys(tmp_path: Path) -> None:
    moment = datetime(2026, 12, 2, 8, 0, tzinfo=UTC)
    path = gate.write_evidence(
        tmp_path, kind="plan", counts={"b": {"selected": 1}, "a": {"selected": 2}}, now=moment
    )
    assert path.name == "2026-12-02-purge-plan.json"
    assert list(json.loads(path.read_text("utf-8"))["counts"]) == ["a", "b"]


def test_the_plan_file_carries_a_content_hash_and_is_counts_only(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    assert h.run("plan") == 0
    plan = json.loads((tmp_path / "plan.json").read_text("utf-8"))
    assert re.fullmatch(r"[0-9a-f]{64}", plan["content_hash"])
    assert plan["created"].startswith(NOW.strftime("%Y-%m-%d"))
    _assert_clean(json.dumps(plan["counts"]))


def test_a_stopped_purge_still_writes_counts_only_evidence(tmp_path: Path) -> None:
    h = Harness(tmp_path)
    assert h.run("plan") == 0
    original = h.stores.documents.reread

    def flip(container: str, document: object) -> object:
        found = original(container, document)
        if container == "cost-ledger" and found is not None:
            found["customer_id"] = ACTIVE
        return found

    h.stores.documents.reread = flip  # type: ignore[method-assign]
    assert h.apply() == 1
    text = next((tmp_path / "evidence").glob("*-purge.json")).read_text("utf-8")
    _assert_clean(text)
