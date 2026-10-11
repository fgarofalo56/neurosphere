"""Load the documentation-derived capability matrix into PRP-01 contract models.

Rules enforced here (the generated model alone does not express them):

* every row validates against ``CapabilityMatrixEntry`` (so a missing ``source_url`` or
  ``observed_on`` fails loading, naming the file and row);
* cloud/region consistency: Government rows use ``usgov*``/``usdod*``, ``global`` or ``*``;
  Commercial rows never use ``usgov*``/``usdod*``;
* ``id`` equals the derived convention ``<service>.<feature>.<cloud>.<region>.<sku-or-any>``
  (replicates ``capability_row_id`` in ``tests/contracts/validators.py``, which lives under
  tests and is not importable from the product package);
* ids and (service, feature, cloud, region, sku) keys are unique across the whole matrix;
* ``observed_on`` is a real date and not in the future.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml
from neurosphere_contracts.deployment.v1.capability_matrix_entry import CapabilityMatrixEntry
from pydantic import BaseModel, ConfigDict, ValidationError

DATA_DIR = Path(__file__).parent / "data"

_GOV_REGION_RE = re.compile(r"^(us(gov|dod)[a-z0-9]+|global|\*)$")
_GOV_PREFIX_RE = re.compile(r"^us(gov|dod)")

RowKey = tuple[str, str, str, str, str | None]


class MatrixLoadError(ValueError):
    """The matrix failed to load; the message names the file and row."""


def derive_row_id(entry: CapabilityMatrixEntry) -> str:
    """Derived row id (see ``capability_row_id`` in tests/contracts/validators.py)."""
    if entry.sku is None:
        sku_part = "any"
    else:
        sku_part = re.sub(r"[^a-z0-9_-]+", "-", entry.sku.lower()).strip("-") or "any"
    region_part = "any" if entry.region == "*" else entry.region
    return ".".join([entry.service, entry.feature, entry.cloud, region_part, sku_part]).lower()


def row_key(entry: CapabilityMatrixEntry) -> RowKey:
    # SKUs compare case-insensitively, consistent with resolution which lowercases them.
    sku = entry.sku.lower() if entry.sku is not None else None
    return (entry.service, entry.feature, entry.cloud, entry.region, sku)


def observed_date(entry: CapabilityMatrixEntry) -> date:
    """``observed_on`` as a date (the loader guarantees it parses)."""
    return date.fromisoformat(entry.observed_on)


class CapabilityMatrix(BaseModel):
    """An immutable, validated set of matrix rows."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rows: tuple[CapabilityMatrixEntry, ...]

    def __iter__(self) -> Iterator[CapabilityMatrixEntry]:  # type: ignore[override]
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)

    def services(self) -> frozenset[str]:
        return frozenset(r.service for r in self.rows)

    def by_id(self, row_id: str) -> CapabilityMatrixEntry | None:
        return next((r for r in self.rows if r.id == row_id), None)


def _check_row(entry: CapabilityMatrixEntry, today: date) -> list[str]:
    problems: list[str] = []
    if entry.cloud == "government" and not _GOV_REGION_RE.match(entry.region):
        problems.append(f"government row has non-government region {entry.region!r}")
    if entry.cloud == "commercial" and _GOV_PREFIX_RE.match(entry.region):
        problems.append(f"commercial row has government region {entry.region!r}")
    if entry.id != derive_row_id(entry):
        problems.append(f"id must equal derived id {derive_row_id(entry)!r}")
    try:
        observed = observed_date(entry)
    except ValueError:
        problems.append(f"observed_on {entry.observed_on!r} is not a real date")
    else:
        if observed > today:
            problems.append(f"observed_on {observed} is in the future (today {today})")
    return problems


def _read_file(path: Path) -> list[Any]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MatrixLoadError(f"{path.name}: cannot read YAML: {exc}") from exc
    if not isinstance(doc, list):
        raise MatrixLoadError(f"{path.name}: top level must be a list of rows")
    return doc


def _describe(index: int, raw: Any) -> str:
    row_id = raw.get("id") if isinstance(raw, dict) else None
    return f"row #{index + 1}" + (f" ({row_id})" if isinstance(row_id, str) else "")


def load_matrix(data_dir: Path | str | None = None, today: date | None = None) -> CapabilityMatrix:
    """Load every ``*.yaml`` under ``data_dir`` (default: the shipped data).

    Raises ``MatrixLoadError`` on the first file with a bad row, naming file and row, and on
    duplicate ids or keys across files. An empty directory is an error: an empty matrix would
    silently make every capability ``unverified``.
    """
    directory = Path(data_dir) if data_dir is not None else DATA_DIR
    today = today or datetime.now(UTC).date()
    files = sorted(directory.glob("*.yaml"))
    if not files:
        raise MatrixLoadError(f"{directory}: no *.yaml matrix files found")
    rows: list[CapabilityMatrixEntry] = []
    where: dict[str, str] = {}
    keys: dict[RowKey, str] = {}
    for path in files:
        for index, raw in enumerate(_read_file(path)):
            label = f"{path.name} {_describe(index, raw)}"
            try:
                entry = CapabilityMatrixEntry.model_validate(raw)
            except ValidationError as exc:
                detail = "; ".join(
                    f"{'.'.join(str(p) for p in e['loc']) or '<row>'}: {e['msg']}"
                    for e in exc.errors()
                )
                raise MatrixLoadError(f"{label}: invalid row: {detail}") from exc
            problems = _check_row(entry, today)
            if problems:
                raise MatrixLoadError(f"{label}: " + "; ".join(problems))
            if entry.id in where:
                raise MatrixLoadError(
                    f"{label}: duplicate id {entry.id!r} (also {where[entry.id]})"
                )
            key = row_key(entry)
            if key in keys:
                raise MatrixLoadError(f"{label}: duplicate row key {key} (also {keys[key]})")
            where[entry.id] = label
            keys[key] = label
            rows.append(entry)
    return CapabilityMatrix(rows=tuple(rows))


def matrix_from_rows(rows: Sequence[CapabilityMatrixEntry]) -> CapabilityMatrix:
    """Build a matrix from in-memory rows (tests, PRP-08 what-if), with the same checks."""
    today = datetime.now(UTC).date()
    ids: set[str] = set()
    keys: set[RowKey] = set()
    for entry in rows:
        problems = _check_row(entry, today)
        if entry.id in ids:
            problems.append("duplicate id")
        if row_key(entry) in keys:
            problems.append("duplicate row key")
        if problems:
            raise MatrixLoadError(f"{entry.id}: " + "; ".join(problems))
        ids.add(entry.id)
        keys.add(row_key(entry))
    return CapabilityMatrix(rows=tuple(rows))
