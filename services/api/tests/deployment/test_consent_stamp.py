"""PRP-59 item 2: the consent audit record names the authenticated principal (#133)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from authz.authz_helpers import Harness  # pyright: ignore[reportMissingImports]
from neurosphere_api.deploy.plan import build_router as plan_router
from neurosphere_api.deploy.scan import ScanService, ScanSettings, configure_scan
from neurosphere_api.deploy.scan import build_router as scan_router
from neurosphere_api.deploy.scan.audit import DeployAuditor, opaque_id

from .conftest import ADMIN
from .test_plan import _matrix  # pyright: ignore[reportPrivateUsage]
from .test_scan import ROWS, SUB_A, SUB_B, FakeReader, _consent  # pyright: ignore[reportPrivateUsage]

CLIENT_TEXT = "owner@example.com"


def test_consent_state_stamps_principal_and_hashes_client_text(
    mount: Callable[[dict[str, Any]], Harness], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The audit builder hashes and discards ``state``, so record what the service hands it.
    recorded: list[Mapping[str, Any]] = []
    original = DeployAuditor.consent_decision

    async def spy(self: DeployAuditor, consent_id: str, **kwargs: Any) -> None:
        recorded.append(kwargs["state"])
        await original(self, consent_id, **kwargs)

    monkeypatch.setattr(DeployAuditor, "consent_decision", spy)
    h = mount({"/v1/deploy/scan": scan_router(), "/v1/deploy/plan": plan_router(_matrix())})
    configure_scan(
        h.app, ScanService(FakeReader({SUB_A, SUB_B}, ROWS), ScanSettings(result_ttl_seconds=900.0))
    )
    consent = _consent(SUB_A)
    assert consent["consented_by"] == CLIENT_TEXT
    r = h.client.post(
        "/v1/deploy/scan",
        json={"consent": consent, "subscription_ids": [SUB_A]},
        headers=h.auth(ADMIN),
    )
    assert r.status_code == 200, r.text
    assert len(recorded) == 1
    state = recorded[0]
    assert state["attestation"] == opaque_id("attest", CLIENT_TEXT)
    assert state["consented_by"] != CLIENT_TEXT
    assert state["consented_by"]  # the authenticated principal pseudonym
    assert CLIENT_TEXT not in json.dumps(dict(state))  # the raw client string is not stored
