"""FinOps forecast route (PRP-21 item 4), mounted at ``/api/v1/finops``.

| Method | Path                           | Permission    |
|--------|--------------------------------|---------------|
| GET    | ``/domains/{domain}/forecast`` | ``data.read`` |

The path ``{domain}`` is the addressed resource and the authorization TARGET: ``require`` checks
``data.read`` on exactly that domain against the scope derived from the bearer token (403 outside
it, 503 on a policy-store outage). ``customer_id`` comes only from the derived ``IdentityScope``;
query parameters named ``customer_id`` or ``domain_id`` are not read.

Query: ``history_days`` 7-90 (default 30), ``horizon_days`` 1-31 (default 14), ``currency`` ISO
4217 (default USD), ``as_of`` (a date not after today; default today). With a past ``as_of`` the
horizon days that have already happened carry their actuals beside the forecast (backtest).

Response: see :mod:`neurosphere_api.finops.models`. It always cites the price version; the
estimated and invoiced series are separate; unknown is ``null`` with ``status: "unknown"``.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from datetime import date
from typing import Annotated, Final

from fastapi import APIRouter, Depends, Path, Query
from neurosphere_core.auth.scope import Permission
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.ledger import LedgerStore
from neurosphere_core.scope import IdentityScope

from neurosphere_api.authz import domain_from_path, require
from neurosphere_api.finops.dependencies import Clock, get_clock, get_ledger_store
from neurosphere_api.finops.models import ForecastResponse
from neurosphere_api.finops.service import build_forecast
from neurosphere_api.routers import RouterRegistry

__all__ = ["PREFIX", "build_router", "register"]

PREFIX: Final = "/api/v1/finops"

ReadScope = Annotated[
    IdentityScope, Depends(require(Permission.DATA_READ, domain_from_path("domain")))
]
Store = Annotated[LedgerStore, Depends(get_ledger_store)]
Now = Annotated[Clock, Depends(get_clock)]
DomainPath = Annotated[str, Path(min_length=1, max_length=512)]
HistoryDays = Annotated[int, Query(ge=7, le=90)]
HorizonDays = Annotated[int, Query(ge=1, le=31)]
CurrencyParam = Annotated[str, Query(pattern="^[A-Z]{3}$")]


def build_router() -> APIRouter:
    router = APIRouter(tags=["finops"])

    @router.get("/domains/{domain}/forecast", response_model=ForecastResponse)
    async def get_forecast(
        domain: DomainPath,
        scope: ReadScope,
        store: Store,
        clock: Now,
        history_days: HistoryDays = 30,
        horizon_days: HorizonDays = 14,
        currency: CurrencyParam = "USD",
        as_of: date | None = None,
    ) -> ForecastResponse:
        today = clock().date()
        first_forecast_day = today if as_of is None else as_of
        if first_forecast_day > today:
            raise InvalidSchemaError("as_of must not be in the future", reason="as_of_future")
        return await build_forecast(
            store,
            customer_id=scope.customer_id,  # derived scope only; never a request value
            domain_id=domain,
            as_of=first_forecast_day,
            today=today,
            history_days=history_days,
            horizon_days=horizon_days,
            currency=currency,
        )

    return router


def register(registry: RouterRegistry) -> None:
    registry.register(PREFIX, build_router())
