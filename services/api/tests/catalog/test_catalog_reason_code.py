"""Optional closed ``reason_code`` on deprecate and recertify (PRP-31 round 2 item 9)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from authz.authz_helpers import FINANCE  # pyright: ignore[reportMissingImports]
from catalog_api_helpers import (  # pyright: ignore[reportMissingImports]
    STEWARD_FINANCE,
    Api,
    agent_doc,
    agent_id,
    make_api,
    owner_doc,
    owner_id,
)

FIN_AGENT = agent_id("fin-bot")
OWNER = owner_id("team-b")
CODES = (
    "superseded",
    "no_longer_used",
    "owner_changed",
    "owner_left",
    "security_issue",
    "quality_issue",
    "periodic_review",
    "other",
)


def _api() -> Api:
    api = make_api()
    api.seed(
        agent_doc("fin-bot", FINANCE),
        owner_doc("team-b", FINANCE, recertify_by="2027-02-01T00:00:00Z"),
    )
    return api


def _etag(api: Api, entity_id: str) -> str:
    return api.get(STEWARD_FINANCE, f"/entities/{entity_id}").headers["ETag"]


def _after_details(api: Api, operation: str) -> list[str | None]:
    records = asyncio.run(api.audit_records())
    return [
        r.outcome.detail
        for r in records
        if r.kind == "after" and r.operation == operation and r.outcome is not None
    ]


def _post(api: Api, entity_id: str, verb: str, body: Any) -> Any:
    return api.post(
        STEWARD_FINANCE,
        f"/entities/{entity_id}/{verb}",
        body,
        headers={"If-Match": _etag(api, entity_id)},
    )


@pytest.mark.parametrize("code", CODES)
def test_deprecate_reason_code_reaches_the_audit_detail(code: str) -> None:
    api = _api()
    response = _post(api, FIN_AGENT, "deprecate", {"reason_code": code})
    assert response.status_code == 200, response.text
    assert _after_details(api, "catalog.entity_deprecate") == [f"entity_deprecate:reason={code}"]


def test_recertify_reason_code_reaches_the_audit_detail() -> None:
    api = _api()
    response = _post(
        api, OWNER, "recertify", {"valid_for_days": 90, "reason_code": "periodic_review"}
    )
    assert response.status_code == 200, response.text
    assert _after_details(api, "catalog.owner_recertify") == [
        "owner_recertify:reason=periodic_review"
    ]


def test_no_body_or_no_code_keeps_the_detail_unchanged() -> None:
    api = _api()
    assert _post(api, FIN_AGENT, "deprecate", None).status_code == 200
    assert _after_details(api, "catalog.entity_deprecate") == ["entity_deprecate"]

    other = _api()
    assert _post(other, FIN_AGENT, "deprecate", {}).status_code == 200
    assert _after_details(other, "catalog.entity_deprecate") == ["entity_deprecate"]

    assert _post(other, OWNER, "recertify", {"valid_for_days": 30}).status_code == 200
    assert _after_details(other, "catalog.owner_recertify") == ["owner_recertify"]


@pytest.mark.parametrize(
    ("verb", "entity", "body"),
    [
        ("deprecate", FIN_AGENT, {"reason_code": "because"}),
        ("deprecate", FIN_AGENT, {"reason_code": "other", "note": "free text"}),
        ("recertify", OWNER, {"valid_for_days": 30, "reason_code": "because"}),
        ("recertify", OWNER, {"valid_for_days": 30, "note": "free text"}),
    ],
)
def test_unknown_code_or_extra_field_is_422(verb: str, entity: str, body: dict[str, Any]) -> None:
    api = _api()
    response = _post(api, entity, verb, body)
    assert response.status_code == 422, response.text
    assert asyncio.run(api.audit_records()) == []


def test_if_match_paths_are_unchanged_with_a_reason_code() -> None:
    api = _api()
    path = f"/entities/{FIN_AGENT}/deprecate"
    body = {"reason_code": "superseded"}
    stale = api.post(STEWARD_FINANCE, path, body, headers={"If-Match": '"old"'})
    assert stale.json()["code"] == "stale_version"
    missing = api.post(STEWARD_FINANCE, path, body)
    assert missing.json()["code"] == "invalid_schema"
