"""Export: server-derived scope, lawful basis, custodian rule for held data, audit."""

from __future__ import annotations

import pytest
from neurosphere_core.lifecycle import ExportRequest, JobStatus, LawfulBasis, LegalHold
from pydantic import ValidationError

from .lifecycle_helpers import NOW, OTHER_DOMAIN, make_ctx, make_rig, make_scope, record


def _req(*ids: str) -> ExportRequest:
    return ExportRequest(
        lawful_basis=LawfulBasis.LEGAL_OBLIGATION,
        target_kind="catalog",
        container="records",
        record_ids=ids,
    )


def test_caller_supplied_scope_fields_are_rejected() -> None:
    for extra in ({"domain_id": "x"}, {"customer_id": "other"}):
        with pytest.raises(ValidationError):
            ExportRequest.model_validate(
                {
                    "lawful_basis": "consent",
                    "target_kind": "catalog",
                    "container": "records",
                    "record_ids": ["a"],
                    **extra,
                }
            )


def test_lawful_basis_is_required_and_closed() -> None:
    with pytest.raises(ValidationError):
        ExportRequest.model_validate(
            {"target_kind": "catalog", "container": "records", "record_ids": ["a"]}
        )
    with pytest.raises(ValidationError):
        ExportRequest.model_validate(
            {
                "lawful_basis": "because",
                "target_kind": "catalog",
                "container": "records",
                "record_ids": ["a"],
            }
        )


async def test_export_filters_by_scope_customer_and_domain() -> None:
    rig = make_rig()
    rig.target.put(record("in-scope"))
    rig.target.put(record("other-domain", domain_id=OTHER_DOMAIN))
    rig.target.put(record("other-customer", customer_id="fabrikam"))
    rig.target.put(record("no-domain", domain_id=None))
    out = await rig.engine.export(
        _req("in-scope", "other-domain", "other-customer", "no-domain", "missing"),
        make_scope(),
        make_ctx(),
    )
    assert out.status is JobStatus.COMPLETED
    assert [i.record_id for i in out.items] == ["in-scope"]
    assert out.withheld_out_of_scope == 4


async def test_held_data_exports_only_to_custodians() -> None:
    rig = make_rig()
    rig.target.put(record("r1"))
    await rig.holds.place(
        LegalHold(
            reason_code="litigation",
            record_id="r1",
            custodians=("p-custodian",),
            placed_at=NOW,
        )
    )
    denied = await rig.engine.export(_req("r1"), make_scope("p-other"), make_ctx())
    assert denied.items == ()
    assert denied.withheld_held == 1
    allowed = await rig.engine.export(_req("r1"), make_scope("p-custodian"), make_ctx())
    assert [i.record_id for i in allowed.items] == ["r1"]
    assert allowed.withheld_held == 0


async def test_export_is_audited_with_lawful_basis_in_operation() -> None:
    rig = make_rig()
    rig.target.put(record("r1"))
    await rig.engine.export(_req("r1"), make_scope(), make_ctx())
    records = await rig.audit.read_range("lifecycle.contoso", limit=10)
    assert [r.operation for r in records] == ["lifecycle.export.legal_obligation"]
    assert records[0].kind == "after"
