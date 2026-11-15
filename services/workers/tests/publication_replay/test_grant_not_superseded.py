"""PRP-46: the worker recorder's stale-intent guard for grant publications."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from neurosphere_core.errors import StaleVersionError
from neurosphere_workers.publication.grant import check_grant_not_superseded

RECORDED = "2026-11-01T10:00:00Z"


def _stored(applied: datetime | None) -> Any:
    return SimpleNamespace(execution=SimpleNamespace(apply_finished_at=applied))


def _doc(**provenance: Any) -> dict[str, Any]:
    return {
        "attributes": {"apim_intent_id": "intent-recorded"},
        "provenance": {"method": "declared", "recorded_at": RECORDED, **provenance},
    }


def test_older_intent_is_refused() -> None:
    with pytest.raises(StaleVersionError) as err:
        check_grant_not_superseded(_doc(), _stored(datetime(2026, 10, 1, tzinfo=UTC)))
    assert err.value.reason == "stale_intent"


def test_newer_intent_passes() -> None:
    check_grant_not_superseded(_doc(), _stored(datetime(2026, 11, 2, tzinfo=UTC)))


def test_never_recorded_grant_has_nothing_to_supersede() -> None:
    doc = {"attributes": {}, "provenance": {"method": "declared", "recorded_at": RECORDED}}
    check_grant_not_superseded(doc, _stored(datetime(2020, 1, 1, tzinfo=UTC)))


def test_unknown_apply_time_is_not_guessed() -> None:
    check_grant_not_superseded(_doc(), _stored(None))
