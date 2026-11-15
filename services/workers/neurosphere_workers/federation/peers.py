"""Peer cell registry loading (PRP-21 round 2 item 2).

``NS_FEDERATION_PEERS_FILE`` is a JSON document written by the operator::

    {
      "cells": [{"cell_id": "...", "cloud": "commercial", "boundary_id": "...",
                 "endpoint": "https://cell-b.example.org/"}],
      "boundaries": {"<boundary_id>": {"allowed_hosts": ["cell-b.example.org"]}}
    }

It never holds a credential: the caller's own bearer is forwarded to a cell. Loading is strict and
fails with ``ValueError`` (the caller turns it into a startup failure) when:

* a cell is not https, or its host is not an exact (case-insensitive) member of its boundary's
  ``allowed_hosts`` (no wildcards, no suffix match);
* a cell's cloud differs from the serving cloud (a Government peer is never registered in a
  Commercial deployment, or the reverse);
* two cells share an id, or a cell uses the id of this deployment's own cell.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from neurosphere_workers.federation.models import CellRef, CellRegistry, CloudLiteral

__all__ = ["MAX_PEERS_FILE_BYTES", "BoundaryHosts", "PeersFile", "load_peers", "parse_peers"]

MAX_PEERS_FILE_BYTES: Final = 256_000
_MAX_PEERS: Final = 64


class BoundaryHosts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_hosts: tuple[str, ...] = Field(default=(), max_length=64)


class PeersFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cells: tuple[CellRef, ...] = Field(default=(), max_length=_MAX_PEERS)
    boundaries: dict[str, BoundaryHosts] = Field(default_factory=dict)


def parse_peers(
    document: Mapping[str, Any], *, serving_cloud: CloudLiteral, local_cell_id: str
) -> tuple[CellRef, ...]:
    """Validate a peers document and return its cells; raise ``ValueError`` on any violation."""
    try:
        parsed = PeersFile.model_validate(document)
    except ValidationError:
        raise ValueError("peers file is not valid") from None
    allowed = {
        boundary: frozenset(host.strip().lower().rstrip(".") for host in conf.allowed_hosts)
        for boundary, conf in parsed.boundaries.items()
    }
    for cell in parsed.cells:
        if cell.cloud != serving_cloud:
            raise ValueError("peer cell is in another cloud than this deployment")
        if cell.cell_id == local_cell_id:
            raise ValueError("peer cell reuses this deployment's cell id")
        host = (urlsplit(cell.endpoint).hostname or "").lower().rstrip(".")
        if host not in allowed.get(cell.boundary_id, frozenset()):
            raise ValueError("peer cell host is not in its boundary's allowed_hosts")
    CellRegistry(cells=parsed.cells)  # unique ids
    return parsed.cells


def load_peers(
    path: Path | str, *, serving_cloud: CloudLiteral, local_cell_id: str
) -> tuple[CellRef, ...]:
    """Read and validate a peers file (``OSError`` / ``ValueError`` on a bad file)."""
    file = Path(path)
    if file.stat().st_size > MAX_PEERS_FILE_BYTES:
        raise ValueError("peers file is too large")
    try:
        loaded: object = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise ValueError("peers file is not valid JSON") from None
    if not isinstance(loaded, dict):
        raise ValueError("peers file must be a JSON object")
    return parse_peers(
        {str(k): v for k, v in loaded.items()},  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        serving_cloud=serving_cloud,
        local_cell_id=local_cell_id,
    )
