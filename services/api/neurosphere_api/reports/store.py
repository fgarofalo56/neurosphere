"""Report store port and the in-memory implementation (PRP-19 item 5).

Partition = ``(customer_id, domain_id)``. ``replace`` and ``delete`` are compare-and-swap on the
store-assigned ETag: a mismatch is ``stale_version`` (``report_modified``). The store holds
definitions only (plan + query spec); there is nothing result-shaped to cache here.
"""

import base64
import binascii
import itertools
from typing import Final, Protocol, runtime_checkable

from neurosphere_core.errors import (
    DependencyTransientError,
    InvalidSchemaError,
    StaleVersionError,
)
from neurosphere_core.paging import Page

from neurosphere_api.reports.models import PublicationState, StoredReport

__all__ = [
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "InMemoryReportStore",
    "ReportStore",
    "check_limit",
    "decode_cursor",
    "encode_cursor",
    "report_modified",
    "store_unavailable",
    "visible_to",
]

DEFAULT_LIMIT: Final = 50
MAX_LIMIT: Final = 200
_CURSOR_PREFIX: Final = "rp1."


def report_modified() -> StaleVersionError:
    return StaleVersionError("report was modified concurrently", reason="report_modified")


def store_unavailable() -> DependencyTransientError:
    return DependencyTransientError("report store unavailable", reason="report_store_unavailable")


def check_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidSchemaError(f"limit must be 1..{MAX_LIMIT}", reason="invalid_page_size")
    return limit


def encode_cursor(key: str) -> str:
    return _CURSOR_PREFIX + base64.urlsafe_b64encode(key.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> str:
    if not cursor.startswith(_CURSOR_PREFIX):
        raise InvalidSchemaError("cursor is not valid", reason="invalid_cursor")
    try:
        return base64.urlsafe_b64decode(cursor[len(_CURSOR_PREFIX) :].encode("ascii")).decode(
            "utf-8"
        )
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise InvalidSchemaError("cursor is not valid", reason="invalid_cursor") from None


def sort_key(report: StoredReport) -> str:
    return f"{report.created_at.isoformat()}|{report.id}"


def visible_to(report: StoredReport, principal_id: str) -> bool:
    """Owner, share principal, or published (approved add-to-UI)."""
    return (
        report.owner == principal_id
        or principal_id in report.shares
        or report.publication.state == "approved"
    )


@runtime_checkable
class ReportStore(Protocol):
    async def create(self, report: StoredReport) -> StoredReport:
        """Insert (create-only); returns the stored copy with its ETag."""
        ...

    async def get(
        self, customer_id: str, domain_id: str, report_id: str
    ) -> StoredReport | None: ...

    async def replace(self, report: StoredReport, *, if_match: str) -> StoredReport:
        """Compare-and-swap on ``if_match``; mismatch or absence is ``stale_version``."""
        ...

    async def delete(
        self, customer_id: str, domain_id: str, report_id: str, *, if_match: str
    ) -> None:
        """Compare-and-swap delete; mismatch is ``stale_version``."""
        ...

    async def list(
        self,
        customer_id: str,
        domain_id: str,
        *,
        visible_to: str | None = None,
        publication_state: PublicationState | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> Page[StoredReport]:
        """Newest first. ``visible_to`` keeps owner / share / published reports of that principal;
        ``None`` means no visibility filter (callers must have decided access already)."""
        ...


class InMemoryReportStore:
    """Dict-backed store; copies in and out so callers cannot mutate stored state."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str], StoredReport] = {}
        self._counter = itertools.count(1)

    def _next_etag(self) -> str:
        return f'"mem-{next(self._counter)}"'

    async def create(self, report: StoredReport) -> StoredReport:
        key = (report.customer_id, report.domain_id, report.id)
        if key in self._rows:
            raise report_modified()
        stored = report.model_copy(deep=True, update={"etag": self._next_etag()})
        self._rows[key] = stored
        return stored.model_copy(deep=True)

    async def get(self, customer_id: str, domain_id: str, report_id: str) -> StoredReport | None:
        found = self._rows.get((customer_id, domain_id, report_id))
        return None if found is None else found.model_copy(deep=True)

    async def replace(self, report: StoredReport, *, if_match: str) -> StoredReport:
        key = (report.customer_id, report.domain_id, report.id)
        current = self._rows.get(key)
        if current is None or current.etag != if_match:
            raise report_modified()
        stored = report.model_copy(deep=True, update={"etag": self._next_etag()})
        self._rows[key] = stored
        return stored.model_copy(deep=True)

    async def delete(
        self, customer_id: str, domain_id: str, report_id: str, *, if_match: str
    ) -> None:
        key = (customer_id, domain_id, report_id)
        current = self._rows.get(key)
        if current is None or current.etag != if_match:
            raise report_modified()
        del self._rows[key]

    async def list(
        self,
        customer_id: str,
        domain_id: str,
        *,
        visible_to: str | None = None,
        publication_state: PublicationState | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> Page[StoredReport]:
        check_limit(limit)
        rows = [r for (c, d, _), r in self._rows.items() if c == customer_id and d == domain_id]
        if visible_to is not None:
            principal = visible_to
            rows = [r for r in rows if _visible(r, principal)]
        if publication_state is not None:
            rows = [r for r in rows if r.publication.state == publication_state]
        rows.sort(key=sort_key, reverse=True)
        if cursor is not None:
            after = decode_cursor(cursor)
            rows = [r for r in rows if sort_key(r) < after]
        page = rows[:limit]
        next_cursor = encode_cursor(sort_key(page[-1])) if len(rows) > limit else None
        return Page[StoredReport](
            items=tuple(r.model_copy(deep=True) for r in page), next_cursor=next_cursor
        )


def _visible(report: StoredReport, principal_id: str) -> bool:
    return visible_to(report, principal_id)
