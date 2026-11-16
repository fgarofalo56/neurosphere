"""PRP-59 item 3: the uninstall api-version table covers every Bicep top-level type (#38)."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from neurosphere_core.errors import NeuroSphereError

RG = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg"
ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "infra" / "scripts" / "uninstall.py"
BICEP_DIRS = ("infra/bicep", "infra/demo", "infra/appservice")
# `resource sym 'Provider/type@version'` (not `existing`, not commented out).
DECL = re.compile(
    r"^\s*resource\s+\w+\s+'([A-Za-z0-9.]+/[A-Za-z0-9/]+)@([0-9a-z-]+)'(?!\s+existing)"
)


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("ns_uninstall_versions_under_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


uninstall = _load()


def _declared() -> dict[str, set[str]]:
    """Lower-cased top-level ``provider/type`` -> versions used. Child types are skipped."""
    found: dict[str, set[str]] = {}
    for rel in BICEP_DIRS:
        for path in (ROOT / rel).rglob("*.bicep"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.lstrip().startswith("//"):
                    continue
                m = DECL.match(line)
                if m is None or " existing" in line:
                    continue
                full, version = m.group(1).lower(), m.group(2)
                if len(full.split("/")) != 2:  # child types are covered by their parent
                    continue
                found.setdefault(full, set()).add(version)
    return found


def test_the_scan_finds_the_known_types() -> None:
    declared = _declared()
    assert "microsoft.keyvault/vaults" in declared
    assert "microsoft.web/sites" in declared
    assert "microsoft.documentdb/databaseaccounts/sqldatabases" not in declared


def test_every_bicep_top_level_type_is_handled() -> None:
    table = uninstall._API_VERSIONS
    skipped = uninstall.NOT_DELETED_DIRECTLY
    missing = sorted(t for t in _declared() if t not in table and t not in skipped)
    assert missing == [], (
        f"Bicep types with no uninstall api-version or allow-list entry: {missing}"
    )


def test_allow_list_entries_carry_a_reason_and_are_not_also_deletable() -> None:
    for key, reason in uninstall.NOT_DELETED_DIRECTLY.items():
        assert reason.strip(), key
        assert key not in uninstall._API_VERSIONS, key


def test_api_versions_are_not_older_than_the_bicep_tree() -> None:
    declared = _declared()
    stale = {
        t: (v, max(declared[t]))
        for t, v in uninstall._API_VERSIONS.items()
        if t in declared and v < max(declared[t])
    }
    assert stale == {}, f"uninstall api-version older than Bicep: {stale}"


def test_unknown_type_is_still_refused() -> None:
    rid = f"{RG}/providers/Microsoft.Foo/bars/b"
    with pytest.raises(NeuroSphereError):
        uninstall.api_version_for(rid)


def test_app_service_ids_resolve() -> None:
    rid = f"{RG}/providers/Microsoft.Web/sites/app"
    assert uninstall.api_version_for(rid) == "2023-12-01"
