"""PRP-104 item 3: content reads fail closed on the audit write (criterion 2, clarification 5).

If the ``interaction.read`` record cannot be appended, the answer is 503 ``audit_write_failed``
and ``read_content`` is never called: for the route, for the reader's single read and for the
batch read the replay payload branch uses. Harness from ``test_content_read``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from neurosphere_api.interactions import InteractionContentReader
from neurosphere_core.audit import AuditDraft
from neurosphere_core.errors import DependencyTransientError
from test_content_read import (  # pyright: ignore[reportMissingImports]
    FINANCE,
    INVESTIGATOR,
    PURPOSE,
    Api,
    new_id,
)


@pytest.fixture
def api(tmp_path: Path) -> Api:
    return Api(tmp_path, audit_fails=True)


def test_route_answers_503_and_never_decrypts(api: Api) -> None:
    iid = new_id()
    (mark,) = api.seed(iid)
    response = api.read(INVESTIGATOR, iid)
    assert response.status_code == 503, response.text
    assert response.json()["reason"] == "audit_write_failed"
    assert mark not in response.text
    assert api.audit.attempts == 1
    assert api.store.content_reads == 0
    assert api.events == []


def test_single_read_raises_and_never_decrypts(api: Api) -> None:
    iid = new_id()
    api.seed(iid)
    reader = InteractionContentReader(api.explorer)
    access = api.access(api.scope_of(INVESTIGATOR))
    with pytest.raises(DependencyTransientError) as caught:
        asyncio.run(reader.read(access, FINANCE, iid, PURPOSE))
    assert caught.value.reason == "audit_write_failed"
    assert api.store.content_reads == 0


def test_batch_read_raises_and_decrypts_nothing(api: Api) -> None:
    ids = [new_id(), new_id(), new_id()]
    api.seed(*ids)
    reader = InteractionContentReader(api.explorer)
    access = api.access(api.scope_of(INVESTIGATOR))
    with pytest.raises(DependencyTransientError) as caught:
        asyncio.run(reader.read_many(access, FINANCE, ids, PURPOSE))
    assert caught.value.reason == "audit_write_failed"
    assert api.audit.attempts == 1  # one record for the whole batch, never per id
    assert api.store.content_reads == 0


def test_a_rejected_record_also_fails_closed(tmp_path: Path, monkeypatch: Any) -> None:
    """Any append failure counts, not only a store outage (for example the content guard)."""
    api = Api(tmp_path)
    iid = new_id()
    api.seed(iid)

    async def refuse(chain_id: str, draft: AuditDraft) -> Any:
        api.audit.attempts += 1
        raise ValueError("audit record rejected")

    monkeypatch.setattr(api.audit, "append", refuse)
    response = api.read(INVESTIGATOR, iid)
    assert response.status_code == 503
    assert response.json()["reason"] == "audit_write_failed"
    assert api.store.content_reads == 0
