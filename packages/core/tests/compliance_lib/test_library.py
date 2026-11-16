"""Control library and loader (PRP-56 item 2)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from neurosphere_core.compliance import LibraryLoadError, load_library
from neurosphere_core.compliance.loader import LIBRARY_DIR
from neurosphere_core.compliance.models import EVIDENCE_SOURCE_IDS, PATH_REQUIRED_STATUSES

from .helpers import REPO_ROOT


def test_four_frameworks_ship() -> None:
    library = load_library()
    ids = {f.framework.framework_id.root for f in library.frameworks}
    assert ids == {"nist_ai_rmf", "sr_11_7", "hipaa_technical_safeguards", "omb_m_25_21"}


def test_control_ids_are_unique_and_stable_shape() -> None:
    library = load_library()
    ids = library.control_ids()
    assert len(ids) == len(set(ids))
    assert library.control("nist-ai-rmf.govern-2") is not None
    assert library.control("hipaa.164.312.b") is not None


def test_every_control_carries_the_required_fields() -> None:
    for fw in load_library().frameworks:
        for mapped in fw.controls:
            c = mapped.control
            assert c.control_id and c.title and c.source_url and c.source_retrieved
            assert c.framework_version == fw.framework.framework_version
            assert len(c.title) <= 200


def test_cited_repo_paths_exist_for_designed_and_implemented_tested() -> None:
    missing: list[str] = []
    for fw in load_library().frameworks:
        for mapped in fw.controls:
            status = mapped.mapping.support_status.root
            paths = [p.root for p in mapped.mapping.repo_paths]
            if status in PATH_REQUIRED_STATUSES:
                assert paths, mapped.control.control_id
            missing += [p for p in paths if not (REPO_ROOT / p).exists()]
    assert not missing, missing


def test_evidence_sources_are_known() -> None:
    for fw in load_library().frameworks:
        for mapped in fw.controls:
            assert {s.root for s in mapped.mapping.evidence_sources.root} <= set(
                EVIDENCE_SOURCE_IDS
            )


def _copy_library(tmp_path: Path) -> Path:
    target = tmp_path / "library"
    shutil.copytree(LIBRARY_DIR, target)
    return target


def test_duplicate_control_id_is_rejected(tmp_path: Path) -> None:
    lib = _copy_library(tmp_path)
    nist = (lib / "nist_ai_rmf.yaml").read_text(encoding="utf-8")
    other = lib / "omb_m_25_21.yaml"
    other.write_text(
        other.read_text(encoding="utf-8").replace("omb-m-25-21.3.a.i", "nist-ai-rmf.govern-1"),
        encoding="utf-8",
    )
    assert nist
    with pytest.raises(LibraryLoadError, match="duplicate control id"):
        load_library(lib)


def test_unknown_status_is_rejected(tmp_path: Path) -> None:
    lib = _copy_library(tmp_path)
    path = lib / "sr_11_7.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "support_status: customer", "support_status: ok", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(LibraryLoadError, match="support_status"):
        load_library(lib)


def test_unknown_evidence_source_is_rejected(tmp_path: Path) -> None:
    lib = _copy_library(tmp_path)
    path = lib / "sr_11_7.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("[evaluation_results]", "[prompt_capture]", 1),
        encoding="utf-8",
    )
    with pytest.raises(LibraryLoadError, match="evidence_sources"):
        load_library(lib)


def test_designed_support_without_a_path_is_rejected(tmp_path: Path) -> None:
    lib = _copy_library(tmp_path)
    path = lib / "hipaa_technical_safeguards.yaml"
    text = path.read_text(encoding="utf-8")
    start = text.index("control_id: hipaa.164.312.a.2.i\n")
    end = text.index("control_id: hipaa.164.312.a.2.ii\n")
    block = text[start:end]
    changed = block.replace(
        "    repo_paths:\n      - packages/core/neurosphere_core/auth/scope/pseudonym.py\n",
        "    repo_paths: []\n",
    )
    assert changed != block
    path.write_text(text.replace(block, changed), encoding="utf-8")
    with pytest.raises(LibraryLoadError, match="must cite a repository path"):
        load_library(lib)


def test_missing_source_url_is_rejected(tmp_path: Path) -> None:
    lib = _copy_library(tmp_path)
    path = lib / "sr_11_7.yaml"
    lines = [
        ln
        for ln in path.read_text(encoding="utf-8").splitlines()
        if not ln.startswith("source_url")
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(LibraryLoadError):
        load_library(lib)


def test_empty_directory_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(LibraryLoadError, match=r"no \*\.yaml"):
        load_library(tmp_path)
