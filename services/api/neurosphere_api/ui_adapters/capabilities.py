"""Capability matrix read for the browser (PRP-31 item 2), mounted at ``/api/v1/capabilities``.

| Method | Path   | Permission                  |
|--------|--------|-----------------------------|
| GET    | ``""`` | ``data.read`` (any domain)  |

The rows are the shipped PRP-02 matrix (``neurosphere_core.capabilities``), returned as the
contract ``CapabilityMatrixEntry`` without reinterpretation: ``availability``, ``ga_status`` and
``authorization_scope`` stay separate and an ``unverified`` row stays ``unverified``. The rows are
static, documentation-derived and carry no customer data.

Filters: ``cloud`` keeps rows of that cloud. ``region`` keeps the rows that speak for that region
the way capability resolution reads them: the exact region, the cloud-wide ``*`` row of a
matching cloud (a Government ``*`` never covers a Commercial region and vice versa) and
``global`` rows. A filter never turns a missing row into a supported one; it only narrows.

``app.state.capability_matrix`` (a ``CapabilityMatrix``) overrides the shipped data, for tests.
A matrix that fails to load is 503 ``capability_matrix_unavailable``, never an empty list.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

import hashlib
import json
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Query, Request
from neurosphere_contracts.deployment.v1.capability_matrix_entry import CapabilityMatrixEntry
from neurosphere_core.auth.scope import Permission
from neurosphere_core.capabilities import CapabilityMatrix, MatrixLoadError, default_matrix
from neurosphere_core.errors import DependencyTransientError
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import require
from neurosphere_api.ui_adapters.models import CapabilityMatrixView

__all__ = ["PREFIX", "build_router", "get_capability_matrix", "matrix_version"]

PREFIX: Final = "/api/v1/capabilities"
_GOV_PREFIXES: Final = ("usgov", "usdod")

ReadAnywhere = Annotated[IdentityScope, Depends(require(Permission.DATA_READ))]
CloudParam = Annotated[Literal["commercial", "government"] | None, Query()]
RegionParam = Annotated[str | None, Query(pattern=r"^[a-z][a-z0-9]{2,39}$")]


def get_capability_matrix(request: Request) -> CapabilityMatrix:
    configured = getattr(request.app.state, "capability_matrix", None)
    if isinstance(configured, CapabilityMatrix):
        return configured
    try:
        return default_matrix()
    except MatrixLoadError as exc:
        raise DependencyTransientError(
            "capability matrix is unavailable", reason="capability_matrix_unavailable"
        ) from exc


Matrix = Annotated[CapabilityMatrix, Depends(get_capability_matrix)]


def matrix_version(matrix: CapabilityMatrix) -> str:
    """Content digest of every row (order-independent): changes whenever any row changes."""
    rows = sorted(
        json.dumps(r.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        for r in matrix.rows
    )
    digest = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"


def _speaks_for(row: CapabilityMatrixEntry, region: str) -> bool:
    if row.region in (region, "global"):
        return True
    if row.region == "*":
        is_gov_region = region.startswith(_GOV_PREFIXES)
        return is_gov_region if row.cloud == "government" else not is_gov_region
    return False


def build_router() -> APIRouter:
    router = APIRouter(tags=["ui-adapters"])

    @router.get("", response_model=CapabilityMatrixView)
    async def capabilities(
        scope: ReadAnywhere,
        matrix: Matrix,
        cloud: CloudParam = None,
        region: RegionParam = None,
    ) -> CapabilityMatrixView:
        rows = [
            r
            for r in matrix.rows
            if (cloud is None or r.cloud == cloud) and (region is None or _speaks_for(r, region))
        ]
        rows.sort(key=lambda r: r.id)
        observed = max((r.observed_on for r in matrix.rows), default="")
        return CapabilityMatrixView(
            matrix_version=matrix_version(matrix), observed_at=observed, items=rows
        )

    return router
