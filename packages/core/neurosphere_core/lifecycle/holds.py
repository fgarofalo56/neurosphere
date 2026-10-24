"""Legal hold matching."""

from __future__ import annotations

from collections.abc import Iterable

from neurosphere_core.lifecycle.models import LegalHold, TargetRecord, TargetRef


def hold_matches(
    hold: LegalHold,
    *,
    ref: TargetRef | None,
    record: TargetRecord | None,
    subject_id: str | None,
) -> bool:
    """Every selector the hold sets must match; an unknown fact never matches (fail closed
    is handled by the caller: a hold with a selector we cannot evaluate simply does not match,
    so holds should name at least one selector the stores report)."""
    if hold.target_kind is not None and (ref is None or ref.target_kind != hold.target_kind):
        return False
    if hold.record_id is not None and (ref is None or ref.record_id != hold.record_id):
        return False
    effective_subject = subject_id or (record.subject_id if record is not None else None)
    if hold.subject_id is not None and effective_subject != hold.subject_id:
        return False
    return hold.data_class is None or (record is not None and record.data_class == hold.data_class)


def matching_holds(
    holds: Iterable[LegalHold],
    *,
    ref: TargetRef | None,
    record: TargetRecord | None,
    subject_id: str | None = None,
) -> list[LegalHold]:
    return [h for h in holds if hold_matches(h, ref=ref, record=record, subject_id=subject_id)]
