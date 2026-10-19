"""A second forward run against the Cosmos emulator writes nothing (G12: shape only)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from neurosphere_core.migrations import snapshot_hash

if TYPE_CHECKING:
    from .support import Env

pytestmark = pytest.mark.integration


async def test_second_forward_is_noop(env: Env) -> None:
    runner = env.runner("it")
    await runner.migrate()
    etags = {d["id"]: d["_etag"] for d in await env.documents()}
    state = snapshot_hash(await env.documents())

    again = await runner.migrate()

    assert again.noop
    assert again.documents_written == 0
    after = await env.documents()
    assert snapshot_hash(after) == state
    assert {d["id"]: d["_etag"] for d in after} == etags  # no document was rewritten


async def test_new_runner_instance_skips_applied_steps(env: Env) -> None:
    await env.runner("first").migrate()
    result = await env.runner("second").migrate()
    assert result.noop
