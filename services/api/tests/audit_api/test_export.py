"""PRP-40 item 4: ``GET /api/v1/audit/export`` is bounded, permissioned, audited and escaped."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import pytest
from authz.authz_helpers import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    HR,
    OPERATIONS,
    policy,
    role,
)
from neurosphere_api.audit import export
from neurosphere_api.audit.export import CSV_COLUMNS, csv_cell
from neurosphere_core.audit import build_after
from neurosphere_core.auth.scope import Role

from .audit_api_helpers import (
    AUDITOR_FO,
    MEMBERS,
    SINCE,
    STEWARD,
    UNTIL,
    World,
    chain_of,
    ctx,
    make_world,
    seed,
    subject,
)

EXPORT = "/api/v1/audit/export"
#: An admin of FINANCE: privileged, but without audit.export (only the auditor role holds it).
ADMIN_FINANCE = "e49fa0b1-c2d3-4e45-b6a7-b8c9d0e1f2ee"


@pytest.fixture
async def world() -> World:
    w = make_world()
    await seed(w)
    return w


async def _records(world: World, chain: str) -> list[Any]:
    tail = await world.repository.tail(chain)
    assert tail is not None
    return await world.repository.read_range(chain, start=0, limit=tail.sequence + 1)


async def test_ndjson_export_streams_and_audits_each_domain(world: World) -> None:
    before = {d: len(await _records(world, chain_of(d))) for d in (FINANCE, OPERATIONS, HR)}
    response = world.get(AUDITOR_FO, EXPORT, since=SINCE, until=UNTIL, format="ndjson")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.headers["x-neurosphere-export-rows"] == "8"
    assert response.headers["x-neurosphere-export-truncated"] == "false"
    lines = [json.loads(line) for line in response.text.splitlines()]
    assert len(lines) == 8
    assert {line["domain_id"] for line in lines} == {FINANCE, OPERATIONS}
    # One audit.export record per exported domain, appended before the stream; none on HR.
    for domain in (FINANCE, OPERATIONS):
        records = await _records(world, chain_of(domain))
        assert len(records) == before[domain] + 1
        last = records[-1]
        assert last.operation == "audit.export"
        assert last.outcome is not None and last.outcome.detail == "rows_8_ndjson"
        assert last.subject is not None and last.subject.state_digest is not None
        # No record bodies: only a digest of the filters, the count and the format.
        assert "corr-f" not in json.dumps(last.model_dump(mode="json"))
    assert len(await _records(world, chain_of(HR))) == before[HR]


async def test_csv_export_has_a_header_and_rows(world: World) -> None:
    response = world.get(
        AUDITOR_FO, EXPORT, since=SINCE, until=UNTIL, format="csv", domain=[FINANCE]
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(response.text)))
    assert tuple(rows[0]) == CSV_COLUMNS
    assert len(rows) == 1 + 4
    assert {row[0] for row in rows[1:]} == {FINANCE}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=HYPERLINK(1)", "'=HYPERLINK(1)"),
        ("+1", "'+1"),
        ("-2", "'-2"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tx", "'\tx"),
        ("\rx", "'\rx"),
        ("safe", "safe"),
        (None, ""),
        (3, "3"),
    ],
)
def test_csv_cells_are_escaped(value: object, expected: str) -> None:
    assert csv_cell(value) == expected


async def test_formula_in_a_stored_field_is_escaped_in_csv(world: World) -> None:
    await world.repository.append(
        chain_of(FINANCE),
        build_after(
            ctx("action.execute", correlation="-cmd"),
            subject(FINANCE),
            result="failed",
            verified=False,
        ),
    )
    response = world.get(
        AUDITOR_FO, EXPORT, since=SINCE, until=UNTIL, format="csv", domain=[FINANCE]
    )
    rows = list(csv.reader(io.StringIO(response.text)))
    correlation = CSV_COLUMNS.index("correlation_id")
    assert rows[1][correlation] == "'-cmd"


async def test_missing_audit_export_is_403(world: World) -> None:
    # A domain steward holds neither audit.read nor audit.export.
    response = world.get(STEWARD, EXPORT, since=SINCE, until=UNTIL)
    assert response.status_code == 403
    assert response.json()["reason"] == "permission_missing"


async def test_export_permission_must_cover_every_named_domain(world: World) -> None:
    response = world.get(AUDITOR_FO, EXPORT, since=SINCE, until=UNTIL, domain=[FINANCE, HR])
    assert response.status_code == 403
    assert response.json()["reason"] == "target_out_of_scope"
    assert world.denials.attempts[-1].domain_id == HR
    # Nothing was audited as exported on FINANCE either: the refusal comes first.
    assert all(r.operation != "audit.export" for r in await _records(world, chain_of(FINANCE)))


async def test_admin_without_audit_export_cannot_export() -> None:
    w = make_world()
    w.h.repo.put_principal(policy(ADMIN_FINANCE, role(Role.ADMIN, FINANCE), memberships=MEMBERS))
    response = w.get(ADMIN_FINANCE, EXPORT, since=SINCE, until=UNTIL)
    assert response.status_code == 403


async def test_row_cap_truncates(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(export, "MAX_EXPORT_ROWS", 3)
    response = world.get(AUDITOR_FO, EXPORT, since=SINCE, until=UNTIL)
    assert response.status_code == 200
    assert len(response.text.splitlines()) == 3
    assert response.headers["x-neurosphere-export-truncated"] == "true"


async def test_audit_write_failure_refuses_the_export(world: World) -> None:
    async def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise ConnectionError("audit store down")

    world.repository.append = broken  # type: ignore[method-assign]
    response = world.get(AUDITOR_FO, EXPORT, since=SINCE, until=UNTIL)
    assert response.status_code == 503
    assert response.json()["reason"] == "audit_write_failed"
    assert "domain_id" not in response.text


@pytest.mark.parametrize("fmt", ["xml", "json", ""])
async def test_unknown_format_is_refused(world: World, fmt: str) -> None:
    response = world.get(AUDITOR_FO, EXPORT, since=SINCE, until=UNTIL, format=fmt)
    assert response.status_code == 422
