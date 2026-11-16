"""PRP-45 item 2: ``GET /api/v1/admin/system/status`` (names and reason codes only)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from neurosphere_api.runtime.builders import BuildContext, BuilderSpec
from neurosphere_api.runtime.status import OPTIONAL_COMPONENTS, REQUIRED_COMPONENTS
from neurosphere_core.admin import InMemoryAdminConfigRepository
from system_harness import (  # pyright: ignore[reportMissingImports]
    SystemWorld,
    configure_env,
    model_body,
    seed,
)

_CODE = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
STORED_HOST = "acct.openai.azure.com"


@pytest.fixture(autouse=True)
def _auth(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_env(monkeypatch)
    monkeypatch.setenv("NS_COPILOT_ENDPOINT", "https://env-host.openai.azure.com")


def _every_state(ctx: BuildContext) -> None:
    ctx.failed("copilot", "endpoint_cloud_mismatch")
    ctx.disabled("mcp_server")
    ctx.ok("ingest")


EVERY_STATE = BuilderSpec("every-state", ("copilot", "mcp_server", "ingest"), _every_state)


def _strings(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)
    elif isinstance(node, str):
        yield node


class _Probe:
    def __init__(self, name: str, code: str) -> None:
        self.name = name
        self._code = code

    async def check(self) -> str:
        return self._code


def test_status_lists_every_component_with_state_required_and_reason() -> None:
    world = SystemWorld.build(extra=(EVERY_STATE,))
    response = world.get("/status")
    assert response.status_code == 200, response.text
    body = response.json()
    by_name = {c["name"]: c for c in body["components"]}
    assert set(REQUIRED_COMPONENTS) | set(OPTIONAL_COMPONENTS) <= set(by_name)
    assert by_name["copilot"] == {
        "name": "copilot",
        "state": "failed",
        "required": False,
        "reason": "endpoint_cloud_mismatch",
        "blocks_readiness": True,
        "step": False,
    }
    assert by_name["mcp_server"]["state"] == "disabled"
    assert by_name["mcp_server"]["blocks_readiness"] is False
    assert by_name["ingest"]["state"] == "ok"
    assert by_name["ledger"]["state"] == "not_built" and by_name["ledger"]["required"]
    assert by_name["admin_system"]["state"] == "ok"
    assert by_name["cosmos_containers"]["step"] is True
    assert body["ready"] is False
    assert body["stored_settings"]["status"] == "loaded"


def test_status_body_holds_codes_only_never_a_value() -> None:
    repository = InMemoryAdminConfigRepository(cloud="commercial")
    seed(repository, "copilot", model_body())
    world = SystemWorld.build(repository=repository, extra=(EVERY_STATE,))
    body = world.get("/status").json()
    for text in _strings(body):
        assert _CODE.fullmatch(text), text
    raw = world.get("/status").text
    assert STORED_HOST not in raw and "env-host" not in raw and "https" not in raw


def test_status_reports_environment_probe_codes() -> None:
    world = SystemWorld.build()
    world.composed.app.state.health_probes = [
        _Probe("cosmos", "ok"),
        _Probe("blob", "down"),
        _Probe("composition", "unavailable"),
        _Probe("composition.copilot.disabled", "ok"),
    ]
    world.composed.app.state.health_timeout = 1.0
    assert world.get("/status").json()["probes"] == {
        "cosmos": "ok",
        "blob": "unavailable",
    }


def test_status_without_the_plane_is_503() -> None:
    world = SystemWorld.build()
    world.composed.app.state.admin_system = None
    response = world.get("/status")
    assert response.status_code == 503
    assert response.json()["reason"] == "admin_system_unconfigured"
