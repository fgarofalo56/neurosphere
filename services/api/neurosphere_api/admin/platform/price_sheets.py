"""Price sheet routes, mounted at ``/api/v1/admin/platform/price-sheets`` (PRP-44).

| Method | Path                         | Notes                                                    |
|--------|------------------------------|----------------------------------------------------------|
| POST   | ``""``                       | upload: 201 new, 200 same content; 409 changed content   |
| GET    | ``""``                       | list sheets that apply to this cloud (no rows)           |
| GET    | ``/{snapshot_id}``           | summary (no rows)                                        |
| GET    | ``/{snapshot_id}/coverage``  | priced and incomplete models, rows without a meter       |

There is no update or delete: a changed list is a new ``snapshot_id`` (append-only store). No
price value is logged or put in an audit record.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Request, Response, status
from neurosphere_contracts.admin.v1.price_sheet_upload import PriceSheetUpload
from neurosphere_core.admin.platform import PriceSheetResult, coverage_report
from neurosphere_core.errors import NotFoundError

from neurosphere_api.admin.platform.deps import Platform, correlation
from neurosphere_api.admin.platform.models import (
    CoverageView,
    PriceSheetPage,
    PriceSheetUploadView,
    PriceSheetView,
    coverage_view,
    sheet_view,
    upload_view,
)

SnapshotPath = Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]


def _info(result: PriceSheetResult) -> tuple[str | None, dict[str, object]]:
    return result.snapshot.content_hash[:16], {
        "snapshot_id": result.snapshot.snapshot_id,
        "created": result.created,
        "rows": result.coverage.rows,
        "models_priced": result.coverage.models_priced,
        "models_incomplete": len(result.coverage.models_incomplete),
    }


def build_router() -> APIRouter:
    router = APIRouter(tags=["admin-platform-price-sheets"])

    @router.post("", response_model=PriceSheetUploadView, status_code=status.HTTP_201_CREATED)
    async def upload_price_sheet(
        request: Request, response: Response, body: PriceSheetUpload, platform: Platform
    ) -> PriceSheetUploadView:
        result = await platform.audit.run(
            correlation(request),
            "price_sheet.upload",
            "price_sheet",
            body.snapshot_id.root,
            lambda: platform.admin.price_sheets.upload(body),
            info=_info,
        )
        if not result.created:
            response.status_code = status.HTTP_200_OK
        return upload_view(result)

    @router.get("", response_model=PriceSheetPage)
    async def list_price_sheets(platform: Platform) -> PriceSheetPage:
        snapshots = await platform.admin.price_sheets.list()
        return PriceSheetPage(items=[sheet_view(s) for s in snapshots])

    @router.get("/{snapshot_id}", response_model=PriceSheetView)
    async def get_price_sheet(snapshot_id: SnapshotPath, platform: Platform) -> PriceSheetView:
        snapshot = await platform.admin.price_sheets.get(snapshot_id)
        if snapshot is None:
            raise NotFoundError("no such price sheet", reason="price_sheet_not_found")
        return sheet_view(snapshot)

    @router.get("/{snapshot_id}/coverage", response_model=CoverageView)
    async def get_price_sheet_coverage(
        snapshot_id: SnapshotPath, platform: Platform
    ) -> CoverageView:
        snapshot = await platform.admin.price_sheets.get(snapshot_id)
        if snapshot is None:
            raise NotFoundError("no such price sheet", reason="price_sheet_not_found")
        return coverage_view(coverage_report(snapshot))

    return router
