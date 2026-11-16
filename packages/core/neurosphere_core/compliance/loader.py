"""Load and validate the compliance control library (PRP-56 item 2).

The library is YAML package data under ``compliance/library/`` (precedent:
``capabilities/loader.py``). Rules enforced here, beyond what the contract models express:

* every row validates against the ``Control`` and ``ControlMapping`` contract models, so a
  missing ``source_url``, ``source_retrieved`` or ``framework_version``, an unknown support
  status or an unknown evidence source fails loading and names the file and row;
* control ids are unique across the whole library, and a control's framework id equals its
  file's framework id;
* ``designed`` and ``implemented_tested`` support must cite at least one repository path (a test
  checks the paths exist in a checkout; an installed package has no checkout to look in);
* ``source_retrieved`` is a real date that is not in the future.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml
from neurosphere_contracts.compliance.v1.control import Control
from neurosphere_contracts.compliance.v1.control_framework import ControlFramework
from neurosphere_contracts.compliance.v1.control_mapping import ControlMapping
from pydantic import ValidationError

from neurosphere_core.compliance.models import (
    LIBRARY_VERSION,
    PATH_REQUIRED_STATUSES,
    ControlLibrary,
    LibraryFramework,
    MappedControl,
)

__all__ = ["LIBRARY_DIR", "LibraryLoadError", "load_library"]

LIBRARY_DIR = Path(__file__).parent / "library"
_SCHEMA_VERSION = "1.0.0"


class LibraryLoadError(ValueError):
    """The library failed to load; the message names the file and row."""


def _describe(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or '<row>'}: {e['msg']}" for e in error.errors()
    )


def _read(path: Path) -> dict[str, Any]:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise LibraryLoadError(f"{path.name}: cannot read YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise LibraryLoadError(f"{path.name}: top level must be a mapping")
    return doc


def _check_date(path: Path, value: object, today: date) -> None:
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError:
        raise LibraryLoadError(f"{path.name}: source_retrieved {value!r} is not a date") from None
    if parsed > today:
        raise LibraryLoadError(f"{path.name}: source_retrieved {parsed} is in the future")


def _load_file(path: Path, today: date, seen: dict[str, str]) -> LibraryFramework:
    doc = _read(path)
    fid = doc.get("framework_id")
    rows = doc.get("controls")
    if not isinstance(rows, list) or not rows:
        raise LibraryLoadError(f"{path.name}: controls must be a non-empty list")
    mapped: list[MappedControl] = []
    for index, row in enumerate(rows):
        label = f"{path.name} row #{index + 1}"
        if not isinstance(row, dict):
            raise LibraryLoadError(f"{label}: row must be a mapping")
        cid = row.get("control_id")
        label = f"{label} ({cid})" if isinstance(cid, str) else label
        _check_date(path, doc.get("source_retrieved"), today)
        try:
            control = Control.model_validate(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "control_id": cid,
                    "framework_id": fid,
                    "title": row.get("title"),
                    "source_url": row.get("source_url", doc.get("source_url")),
                    "source_retrieved": str(doc.get("source_retrieved")),
                    "framework_version": str(doc.get("framework_version")),
                }
            )
            mapping = ControlMapping.model_validate(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "control_id": cid,
                    "framework_id": fid,
                    "support_status": row.get("support_status"),
                    "evidence_sources": row.get("evidence_sources", []),
                    "repo_paths": row.get("repo_paths", []),
                }
            )
        except ValidationError as exc:
            raise LibraryLoadError(f"{label}: invalid row: {_describe(exc)}") from exc
        if control.control_id in seen:
            raise LibraryLoadError(
                f"{label}: duplicate control id (also in {seen[control.control_id]})"
            )
        seen[control.control_id] = path.name
        status = mapping.support_status.root
        if status in PATH_REQUIRED_STATUSES and not mapping.repo_paths:
            raise LibraryLoadError(f"{label}: {status} support must cite a repository path")
        mapped.append(MappedControl(control=control, mapping=mapping))
    try:
        framework = ControlFramework.model_validate(
            {
                "schema_version": _SCHEMA_VERSION,
                "framework_id": fid,
                "title": doc.get("title"),
                "framework_version": str(doc.get("framework_version")),
                "source_url": doc.get("source_url"),
                "source_retrieved": str(doc.get("source_retrieved")),
                "controls": [m.control.model_dump(mode="json") for m in mapped],
            }
        )
    except ValidationError as exc:
        raise LibraryLoadError(f"{path.name}: invalid framework: {_describe(exc)}") from exc
    return LibraryFramework(framework=framework, controls=tuple(mapped))


def load_library(
    library_dir: Path | str | None = None, today: date | None = None
) -> ControlLibrary:
    """Load every ``*.yaml`` under ``library_dir`` (default: the shipped library).

    Raises ``LibraryLoadError`` on the first bad file or row, on duplicate control ids and on a
    repeated framework id. An empty directory is an error.
    """
    directory = Path(library_dir) if library_dir is not None else LIBRARY_DIR
    today = today or datetime.now(UTC).date()
    files = sorted(directory.glob("*.yaml"))
    if not files:
        raise LibraryLoadError(f"{directory}: no *.yaml library files found")
    seen: dict[str, str] = {}
    frameworks: list[LibraryFramework] = []
    for path in files:
        fw = _load_file(path, today, seen)
        if any(f.framework.framework_id.root == fw.framework.framework_id.root for f in frameworks):
            raise LibraryLoadError(f"{path.name}: duplicate framework id")
        frameworks.append(fw)
    return ControlLibrary(version=LIBRARY_VERSION, frameworks=tuple(frameworks))
