"""Every action kind against the audit container or an audit record is refused and audited."""

from __future__ import annotations

import pytest
from neurosphere_core.audit.store import RECORD_DOC_TYPE, TAIL_DOC_TYPE
from neurosphere_core.errors import InvalidSchemaError
from neurosphere_core.lifecycle import (
    ActionKind,
    ExportRequest,
    JobStatus,
    LawfulBasis,
    LifecycleRequest,
    Rule,
    TargetRef,
    TargetRegistry,
)
from neurosphere_core.lifecycle.adapters import CatalogTarget
from neurosphere_core.lifecycle.memory import InMemoryTarget

from .lifecycle_helpers import make_ctx, make_rig, make_scope, record

ACTIONS = [ActionKind.EXPIRE, ActionKind.DELETE, ActionKind.PSEUDONYMIZE]


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("container", ["audit", "audit_tail", "AUDIT"])
async def test_audit_container_label_refused(action: ActionKind, container: str) -> None:
    rig = make_rig()
    req = LifecycleRequest(
        action=action,
        target=TargetRef(target_kind="catalog", container=container, record_id="anything"),
    )
    out = await rig.engine.submit(req, make_ctx())
    assert out.status is JobStatus.REFUSED
    assert out.governing_rule is Rule.AUDIT_IMMUTABILITY
    assert ("denied", "audit_immutable", None) in await rig.audit_records()
    assert await rig.queue.pending() == []  # refused, never queued for later


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("doc_type", [RECORD_DOC_TYPE, TAIL_DOC_TYPE])
async def test_audit_record_mislabelled_as_ordinary_is_refused(
    action: ActionKind, doc_type: str
) -> None:
    # The caller says "records"/"catalog"; the store reports an audit document.
    rig = make_rig()
    rig.target.put(record("x1", age_days=4000, doc_type=doc_type))
    req = LifecycleRequest(
        action=action,
        target=TargetRef(target_kind="catalog", container="records", record_id="x1"),
    )
    out = await rig.engine.submit(req, make_ctx())
    assert out.status is JobStatus.REFUSED
    assert out.blocked_by is Rule.AUDIT_IMMUTABILITY
    assert "x1" in rig.target.records
    assert rig.target.delete_calls == 0


async def test_audit_record_id_shape_refused() -> None:
    rig = make_rig()
    req = LifecycleRequest(
        action=ActionKind.DELETE,
        target=TargetRef(
            target_kind="catalog", container="records", record_id="rec-" + "0" * 19 + "7"
        ),
    )
    out = await rig.engine.submit(req, make_ctx())
    assert out.status is JobStatus.REFUSED


async def test_audit_outranks_hold_and_policy() -> None:
    rig = make_rig()
    req = LifecycleRequest(
        action=ActionKind.DELETE,
        target=TargetRef(target_kind="audit_record", container="records", record_id="r"),
    )
    out = await rig.engine.submit(req, make_ctx())
    assert out.reason == "audit_immutable"


async def test_export_of_audit_refused_and_audited() -> None:
    rig = make_rig()
    out = await rig.engine.export(
        ExportRequest(
            lawful_basis=LawfulBasis.LEGAL_PROCESS,
            target_kind="catalog",
            container="audit",
            record_ids=("a",),
        ),
        make_scope(),
        make_ctx(),
    )
    assert out.status is JobStatus.REFUSED
    assert ("denied", "audit_immutable", None) in await rig.audit_records()


def test_audit_container_cannot_be_registered() -> None:
    registry = TargetRegistry()
    with pytest.raises(InvalidSchemaError):
        registry.register(InMemoryTarget("catalog", "audit"))
    with pytest.raises(ValueError, match="audit container"):
        CatalogTarget("audit_tail", object())  # type: ignore[arg-type]
