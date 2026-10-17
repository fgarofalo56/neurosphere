"""TypeScript-produced manifest fixtures validate with the Python kit (PRP-09 acceptance 2).

The fixtures are written by ``connectors/sdk-ts`` (``buildManifest``). Both directories must be
non-empty so a missing checkout cannot pass vacuously, and both SDKs reject the same invalid
fixtures.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from neurosphere_connector import manifest_issues, validate_manifest
from neurosphere_contracts.connectors.v1.connector_manifest import ConnectorManifest
from neurosphere_core.errors import InvalidSchemaError

HERE = Path(__file__).resolve().parent
PY_DIR = HERE / "fixtures"
TS_DIR = HERE.parents[2] / "sdk-ts" / "tests" / "fixtures" / "manifests"
TS_VALID = sorted(TS_DIR.glob("*.json"))
INVALID_NAMES = sorted(p.name for p in (PY_DIR / "invalid").glob("*.json"))


def test_fixture_dirs_are_not_empty() -> None:
    assert TS_VALID, f"no TypeScript fixtures under {TS_DIR}"
    assert list(PY_DIR.glob("*.json")), f"no Python fixtures under {PY_DIR}"
    assert INVALID_NAMES


@pytest.mark.parametrize("path", TS_VALID, ids=lambda p: p.stem)
def test_ts_fixture_validates_in_python(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert manifest_issues(text) == []
    assert isinstance(validate_manifest(text), ConnectorManifest)


def test_shared_invalid_fixtures_present_on_both_sides() -> None:
    assert sorted(p.name for p in (TS_DIR / "invalid").glob("*.json")) == INVALID_NAMES


@pytest.mark.parametrize("name", INVALID_NAMES)
def test_shared_invalid_fixture_rejected(name: str) -> None:
    for directory in (PY_DIR / "invalid", TS_DIR / "invalid"):
        text = (directory / name).read_text(encoding="utf-8")
        assert manifest_issues(text)
        with pytest.raises(InvalidSchemaError):
            validate_manifest(text)
