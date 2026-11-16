"""PRP-46: a grant publication intent applied before the last record is refused (stale_intent)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from gateway_mode_harness import STEWARD, problem  # pyright: ignore[reportMissingImports]
from grant_publish_harness import (  # pyright: ignore[reportMissingImports]
    GrantEnv,
    make_grant_env,
)


def _execute(g: GrantEnv, drafted: Any) -> str:
    assert drafted.status_code == 201, drafted.text
    intent_id = drafted.json()["intent"]["intent_id"]
    g.execute(intent_id)
    return intent_id


def _stamp_applied(g: GrantEnv, intent_id: str, when: datetime) -> None:
    async def run() -> None:
        stored = await g.env.intents.get("contoso", _domain(g, intent_id), intent_id)
        assert stored is not None and stored.execution is not None and stored.etag is not None
        execution = stored.execution.model_copy(update={"apply_finished_at": when})
        await g.env.intents.replace(
            stored.model_copy(update={"execution": execution}), if_match=stored.etag
        )

    asyncio.run(run())


def _domain(g: GrantEnv, intent_id: str) -> str:
    from gateway_mode_harness import FINANCE  # pyright: ignore[reportMissingImports]

    return FINANCE


def test_older_intent_replay_is_refused_and_recorded_one_is_idempotent() -> None:
    g = make_grant_env()
    publish_id = _execute(g, g.publish(STEWARD))
    _stamp_applied(g, publish_id, datetime(2000, 1, 1, tzinfo=UTC))
    first = g.record(STEWARD, publish_id)
    assert first.status_code == 200, first.text

    unpublish_id = _execute(g, g.unpublish(STEWARD))
    # The unpublish was applied long before the publish was recorded: it is history.
    _stamp_applied(g, unpublish_id, datetime(1999, 1, 1, tzinfo=UTC))
    stale = g.record(STEWARD, unpublish_id)
    assert stale.status_code == 409, stale.text
    assert problem(stale)["reason"] == "stale_intent"
    assert g.stored().model_dump(mode="json")["attributes"]["apim_intent_id"] == publish_id

    again = g.record(STEWARD, publish_id)
    assert again.status_code == 200
    assert again.json()["etag"] == first.json()["etag"]
