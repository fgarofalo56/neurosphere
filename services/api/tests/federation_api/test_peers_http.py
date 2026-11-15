"""PRP-21 round 2 item 2: peer cells from ``NS_FEDERATION_PEERS_FILE`` over ``HttpCellClient``."""

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from neurosphere_api.federation import FederationState, HttpCellClient
from neurosphere_api.runtime.builders import ComponentUnavailableError, data
from neurosphere_workers.federation import CellSummary, DomainSummary, load_peers, parse_peers
from test_federation_scope import (  # pyright: ignore[reportMissingImports]
    BOB,
    BOUNDARY,
    CELL_A,
    CUSTOMER,
    HR,
    NOW,
    build,
)

HOST = "cell-c.example.org"


def _doc(**cell: Any) -> dict[str, Any]:
    entry = {
        "cell_id": "cell-c",
        "cloud": "commercial",
        "boundary_id": BOUNDARY,
        "endpoint": f"https://{HOST}/",
    }
    entry.update(cell)
    return {"cells": [entry], "boundaries": {BOUNDARY: {"allowed_hosts": [HOST]}}}


def _parse(doc: dict[str, Any], cloud: Any = "commercial") -> Any:
    return parse_peers(doc, serving_cloud=cloud, local_cell_id="local")


def test_valid_peer_is_registered() -> None:
    (cell,) = _parse(_doc())
    assert cell.cell_id == "cell-c"


def test_host_match_is_exact_and_case_insensitive() -> None:
    assert _parse(_doc(endpoint=f"https://{HOST.upper()}/x"))
    for host in ("evil.example.org", f"sub.{HOST}", f"{HOST}.evil.io"):
        with pytest.raises(ValueError, match="allowed_hosts"):
            _parse(_doc(endpoint=f"https://{host}/"))


def test_boundary_without_allowlist_is_refused() -> None:
    doc = _doc()
    doc["boundaries"] = {}
    with pytest.raises(ValueError, match="allowed_hosts"):
        _parse(doc)


@pytest.mark.parametrize("endpoint", [f"http://{HOST}/", f"ftp://{HOST}/", f"https://u:p@{HOST}/"])
def test_non_https_or_credentialed_endpoint_is_refused(endpoint: str) -> None:
    with pytest.raises(ValueError, match="peers file is not valid"):
        _parse(_doc(endpoint=endpoint))


def test_cross_cloud_peer_is_refused_both_ways() -> None:
    with pytest.raises(ValueError, match="another cloud"):
        _parse(_doc(cloud="government"), cloud="commercial")
    with pytest.raises(ValueError, match="another cloud"):
        _parse(_doc(cloud="commercial"), cloud="government")


def test_local_cell_id_and_duplicates_are_refused() -> None:
    with pytest.raises(ValueError, match="cell id"):
        _parse(_doc(cell_id="local"))
    doc = _doc()
    doc["cells"].append(dict(doc["cells"][0]))
    with pytest.raises(ValueError, match="unique"):
        _parse(doc)


def test_unknown_keys_and_bad_files_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not valid"):
        _parse({"cells": [], "secret": "x"})
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        load_peers(bad, serving_cloud="commercial", local_cell_id="local")
    with pytest.raises(OSError):
        load_peers(tmp_path / "missing.json", serving_cloud="commercial", local_cell_id="local")


def _peer_summary() -> CellSummary:
    return CellSummary(
        cell_id="cell-c",
        cloud="commercial",
        boundary_id=BOUNDARY,
        customer_id=CUSTOMER,
        scope_hash="sha256:" + "3" * 64,
        window_start=NOW - timedelta(days=30),
        window_end=NOW,
        domains=(DomainSummary(domain_id=HR, request_count=321, complete=True),),
    )


def test_peer_is_reached_through_http_client_with_the_callers_bearer() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=_peer_summary().model_dump_json())

    (peer,) = _parse(_doc())
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    env = build(
        registry_cells=(CELL_A, peer),
        overrides={"cell-c": HttpCellClient(http)},
    )
    body = env.get(BOB).json()
    assert {c["cell_id"]: c["state"] for c in body["cells"]} == {"cell-a": "ok", "cell-c": "ok"}
    assert any(d["domain_id"] == HR and d["request_count"] == 321 for d in body["domains"])
    (request,) = seen
    assert request.url.host == HOST
    assert request.headers["authorization"].startswith("Bearer ")


# ------------------------------------------------------------------ builder wiring


def _ctx(http: httpx.AsyncClient | None = None) -> Any:
    state = SimpleNamespace()
    app = SimpleNamespace(state=state)
    shutdown: list[Any] = []
    reader = build().stores["cell-a"]
    shared = {
        "authenticator": SimpleNamespace(),
        "scope_source": SimpleNamespace(),
        "aggregate_reader": reader,
    }

    class Overrides:
        def backend(self, name: str) -> object | None:
            return http if name == "federation_http_client" else None

    ctx = SimpleNamespace(
        app=app,
        settings=SimpleNamespace(
            cloud_profile=SimpleNamespace(cloud=SimpleNamespace(value="commercial"))
        ),
        overrides=Overrides(),
        shared=lambda key: shared[key.name],
        on_shutdown=shutdown.append,
        shutdown=shutdown,
    )
    return ctx


def _write(tmp_path: Path, doc: dict[str, Any]) -> Path:
    path = tmp_path / "peers.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_builder_registers_peers_and_closes_the_shared_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NS_FEDERATION_PEERS_FILE", str(_write(tmp_path, _doc())))
    monkeypatch.setenv("NS_FEDERATION_BOUNDARY_ID", BOUNDARY)
    monkeypatch.setenv("NS_FEDERATION_CACHE_MAX_TTL_SECONDS", "600")
    monkeypatch.setenv("NS_FEDERATION_CACHE_TTL_SECONDS", "500")
    ctx = _ctx()
    data._federation(cast(Any, ctx))  # pyright: ignore[reportPrivateUsage]
    state = ctx.app.state.federation
    assert isinstance(state, FederationState)
    assert {c.cell_id for c in state.federator.select(None)} == {"local", "cell-c"}
    assert state.cache.ttl_seconds == 500.0
    assert len(ctx.shutdown) == 1  # the shared AsyncClient.aclose


def test_builder_without_peers_is_single_cell_and_opens_no_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NS_FEDERATION_PEERS_FILE", raising=False)
    ctx = _ctx()
    data._federation(cast(Any, ctx))  # pyright: ignore[reportPrivateUsage]
    assert [c.cell_id for c in ctx.app.state.federation.federator.select(None)] == ["local"]
    assert ctx.shutdown == []


@pytest.mark.parametrize(
    "doc", [_doc(cloud="government"), _doc(endpoint="http://cell-c.example.org/")]
)
def test_builder_fails_startup_on_a_bad_peer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, doc: dict[str, Any]
) -> None:
    monkeypatch.setenv("NS_FEDERATION_PEERS_FILE", str(_write(tmp_path, doc)))
    with pytest.raises(ComponentUnavailableError, match="federation_settings_invalid"):
        data._federation(cast(Any, _ctx()))  # pyright: ignore[reportPrivateUsage]


def test_builder_fails_startup_on_a_missing_peers_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("NS_FEDERATION_PEERS_FILE", str(tmp_path / "nope.json"))
    with pytest.raises(ComponentUnavailableError, match="federation_settings_invalid"):
        data._federation(cast(Any, _ctx()))  # pyright: ignore[reportPrivateUsage]
