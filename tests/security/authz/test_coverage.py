"""Case-table coverage: a removed case needs a reason entry; every path kind has cases.

``case_manifest.json`` is the committed ledger. To add cases, append their ids to ``ids`` (and
bump nothing else). To remove a case, KEEP its id in ``ids`` and add ``removed[<id>] = <reason>``;
deleting an id from the ledger is itself a visible diff in review. Regenerate a ledger skeleton
with ``PYTHONPATH=tests python -m security.authz.manifest`` (prints JSON, never overwrites).
"""

import json
from pathlib import Path
from typing import Any

from .cases import CASES, KINDS, all_rows

MANIFEST_PATH = Path(__file__).with_name("case_manifest.json")


def _manifest() -> dict[str, Any]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _active_ids(manifest: dict[str, Any]) -> dict[str, set[str]]:
    removed = set(manifest["removed"])
    return {k: set(manifest["ids"][k]) - removed for k in KINDS}


def test_every_row_has_a_reason_and_audit_expectation() -> None:
    rows = all_rows()
    assert rows
    for row in rows:
        assert row.why.strip(), f"{row.id}: missing reason entry"
        assert row.audit in ("allow", "denied", "none"), row.id
        if row.audit == "none":
            assert row.gap.strip(), f"{row.id}: audit gap without a stated reason"


def test_case_ids_are_unique_and_prefixed_by_path_kind() -> None:
    seen: set[str] = set()
    for kind in KINDS:
        for row in CASES[kind]:
            assert row.id.startswith(f"{kind}."), row.id
            assert row.id not in seen, f"duplicate case id {row.id}"
            seen.add(row.id)


def test_no_case_removed_without_a_reason() -> None:
    manifest = _manifest()
    removed: dict[str, str] = manifest["removed"]
    for case_id, reason in removed.items():
        assert isinstance(reason, str) and len(reason.strip()) >= 20, (
            f"removed case {case_id} needs a real reason entry"
        )
        assert any(case_id in manifest["ids"][k] for k in KINDS), (
            f"removed case {case_id} is not in the ledger"
        )
    actual = {k: {r.id for r in CASES[k]} for k in KINDS}
    for kind in KINDS:
        resurrected = actual[kind] & set(removed)
        assert not resurrected, (
            f"cases listed as removed are still present: {sorted(resurrected)[:3]}"
        )
        missing = _active_ids(manifest)[kind] - actual[kind]
        assert not missing, (
            f"{len(missing)} {kind} case(s) vanished without a reason entry in "
            f"case_manifest.json: {sorted(missing)[:5]}"
        )
        added = actual[kind] - set(manifest["ids"][kind])
        assert not added, f"new {kind} case(s) are not in the ledger: {sorted(added)[:5]}"


def test_counts_per_path_kind_and_none_empty(capsys: Any) -> None:
    manifest = _manifest()
    counts = {k: len(CASES[k]) for k in KINDS}
    with capsys.disabled():
        print("\nABAC negative suite: cases per path")
        for kind in KINDS:
            print(f"  {kind:>7}: {counts[kind]}")
        print(f"  {'total':>7}: {sum(counts.values())}")
    for kind in KINDS:
        assert counts[kind] > 0, f"path kind {kind} has zero cases"
        assert counts[kind] == manifest["counts"][kind] - sum(
            1 for i in manifest["removed"] if i in manifest["ids"][kind]
        ), f"{kind}: case count differs from the committed manifest"
