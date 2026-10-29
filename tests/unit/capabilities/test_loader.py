"""Loader: contract validation, naming file and row, duplicate detection."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from neurosphere_core.capabilities import MatrixLoadError, load_matrix
from rows import raw_row

TODAY = date(2026, 10, 29)


def write(tmp_path: Path, name: str, rows: list[dict[str, Any]]) -> None:
    (tmp_path / name).write_text(yaml.safe_dump(rows), encoding="utf-8")


def test_shipped_matrix_loads() -> None:
    matrix = load_matrix(today=TODAY)
    assert len(matrix) == 646
    assert len(matrix.services()) == 11


@pytest.mark.parametrize("missing", ["source_url", "observed_on"])
def test_row_missing_provenance_fails_naming_file_and_row(tmp_path: Path, missing: str) -> None:
    row = raw_row()
    del row[missing]
    write(tmp_path, "fabric.yaml", [raw_row(region="usgovtexas"), row])
    with pytest.raises(MatrixLoadError) as err:
        load_matrix(tmp_path, today=TODAY)
    message = str(err.value)
    assert "fabric.yaml" in message
    assert "row #2" in message
    assert missing in message


def test_contract_violation_fails(tmp_path: Path) -> None:
    write(tmp_path, "x.yaml", [raw_row(availability="maybe")])
    with pytest.raises(MatrixLoadError, match=r"x\.yaml.*availability"):
        load_matrix(tmp_path, today=TODAY)


def test_extra_member_fails(tmp_path: Path) -> None:
    write(tmp_path, "x.yaml", [raw_row(surprise=1)])
    with pytest.raises(MatrixLoadError, match="surprise"):
        load_matrix(tmp_path, today=TODAY)


def test_duplicate_id_across_files_fails(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", [raw_row()])
    write(tmp_path, "b.yaml", [raw_row()])
    with pytest.raises(MatrixLoadError, match="duplicate id"):
        load_matrix(tmp_path, today=TODAY)


def test_id_must_equal_derived_id(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", [raw_row(id="fabric.base.government.usgovvirginia.dup")])
    with pytest.raises(MatrixLoadError, match="derived id"):
        load_matrix(tmp_path, today=TODAY)


def test_future_observed_on_fails(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", [raw_row(observed_on="2026-12-01")])
    with pytest.raises(MatrixLoadError, match="future"):
        load_matrix(tmp_path, today=TODAY)


def test_government_row_with_commercial_region_fails(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", [raw_row(region="eastus")])
    with pytest.raises(MatrixLoadError, match="non-government region"):
        load_matrix(tmp_path, today=TODAY)


def test_commercial_row_with_government_region_fails(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", [raw_row(cloud="commercial", region="usgovvirginia")])
    with pytest.raises(MatrixLoadError, match="commercial row has government region"):
        load_matrix(tmp_path, today=TODAY)


def test_empty_directory_and_non_list_fail(tmp_path: Path) -> None:
    with pytest.raises(MatrixLoadError, match=r"no .*yaml"):
        load_matrix(tmp_path, today=TODAY)
    (tmp_path / "a.yaml").write_text("key: value\n", encoding="utf-8")
    with pytest.raises(MatrixLoadError, match="list of rows"):
        load_matrix(tmp_path, today=TODAY)


def test_duplicate_key_differing_only_in_sku_case_fails(tmp_path: Path) -> None:
    write(
        tmp_path,
        "a.yaml",
        [
            raw_row(sku="Standard_D4s_v5"),
            raw_row(sku="standard_d4s_v5"),
        ],
    )
    with pytest.raises(MatrixLoadError, match="duplicate"):
        load_matrix(tmp_path, today=TODAY)
