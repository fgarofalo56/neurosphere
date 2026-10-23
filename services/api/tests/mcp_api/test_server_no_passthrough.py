"""No token passthrough (PRP-22 item 1, clarification 5): the inbound bearer never leaves.

Static: the MCP server package imports no outbound client, never reads a header, never touches a
``.token`` attribute, and the raw token flows only into the in-process validator.

Runtime: a full session (every tool, every resource) runs while every outbound transport (httpx,
httpx2, sockets, asyncio connections) is replaced by a recorder, and every downstream port and
the action service record their arguments. Nothing goes out, and the bearer appears in no
downstream argument, log record, response body or retained ``AccessToken``.
"""

from __future__ import annotations

import ast
import asyncio
import functools
import logging
import socket
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import conftest_server as cs  # pyright: ignore[reportMissingImports]
import httpx
import httpx2
import neurosphere_api.mcp.server as server_package
import pytest
from mcp.server.auth.middleware.auth_context import get_access_token
from neurosphere_api.authz import configure_authz
from neurosphere_api.mcp.server import REDACTED_TOKEN, McpAccessToken
from neurosphere_core.auth.jwt import VerifiedClaims
from neurosphere_core.auth.scope import ScopeDerivation

PACKAGE_DIR = Path(server_package.__file__).resolve().parent
FORBIDDEN_IMPORTS = (
    "httpx",
    "httpx2",
    "aiohttp",
    "requests",
    "urllib3",
    "urllib.request",
    "http.client",
    "socket",
    "ssl",
    "websockets",
    "grpc",
    "azure",
    "msal",
    "neurosphere_core.clients",
    "neurosphere_connector",
)
RAW_TOKEN_NAMES = frozenset({"token", "dev_token"})
TOKEN_SINKS = frozenset({"validate", "verify_token"})


# -- static ----------------------------------------------------------------------------------


def _sources() -> Iterator[tuple[Path, ast.Module]]:
    files = sorted(PACKAGE_DIR.rglob("*.py"))
    assert files
    for path in files:
        yield path, ast.parse(path.read_text(encoding="utf-8"))


def _docstring_nodes(tree: ast.Module) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _parents(tree: ast.Module) -> dict[int, ast.AST]:
    return {id(child): node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}


def test_the_server_package_imports_no_outbound_client() -> None:
    offenders: list[str] = []
    for path, tree in _sources():
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for name in names:
                if any(name == f or name.startswith(f + ".") for f in FORBIDDEN_IMPORTS):
                    offenders.append(f"{path.name}: {name}")
    assert offenders == []


def test_the_server_package_never_reads_headers_or_token_attributes() -> None:
    offenders: list[str] = []
    for path, tree in _sources():
        docstrings = _docstring_nodes(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"headers", "token"}:
                offenders.append(f"{path.name}:{node.lineno} .{node.attr}")
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                # A header name, or the scheme prefix of a header value ("Bearer " + ...).
                if node.value.strip().lower() in {"authorization", "bearer"}:
                    offenders.append(f"{path.name}:{node.lineno} {node.value!r}")
    assert offenders == []


def test_the_raw_token_only_flows_into_the_in_process_validator() -> None:
    uses = 0
    offenders: list[str] = []
    for path, tree in _sources():
        parents = _parents(tree)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Name)
                and node.id in RAW_TOKEN_NAMES
                and isinstance(node.ctx, ast.Load)
            ):
                continue
            uses += 1
            parent = parents.get(id(node))
            ok = (
                isinstance(parent, ast.Call)
                and node in parent.args
                and isinstance(parent.func, ast.Attribute)
                and parent.func.attr in TOKEN_SINKS
            )
            if not ok:
                offenders.append(f"{path.name}:{node.lineno}")
    assert uses >= 2  # verify_token -> validator.validate, stdio -> verifier.verify_token
    assert offenders == []


# -- runtime ---------------------------------------------------------------------------------


class Outbound:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def record(self, label: str) -> Callable[..., Any]:
        def blocked(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(f"{label}: {args!r} {kwargs!r}")
            raise AssertionError(f"outbound {label} attempted")

        return blocked


def _block_outbound(monkeypatch: pytest.MonkeyPatch) -> Outbound:
    outbound = Outbound()
    targets: list[tuple[Any, str]] = [
        (httpx.AsyncHTTPTransport, "handle_async_request"),
        (httpx.HTTPTransport, "handle_request"),
        (httpx2.AsyncHTTPTransport, "handle_async_request"),
        (httpx2.HTTPTransport, "handle_request"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (asyncio.BaseEventLoop, "create_connection"),
    ]
    for owner, name in targets:
        monkeypatch.setattr(owner, name, outbound.record(f"{owner.__name__}.{name}"))
    monkeypatch.setattr(socket, "create_connection", outbound.record("socket.create_connection"))
    return outbound


def _record_calls(obj: object, names: tuple[str, ...], sink: list[str]) -> None:
    for name in names:
        original = getattr(obj, name)

        def make(fn: Callable[..., Any], label: str) -> Callable[..., Any]:
            @functools.wraps(fn)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                sink.append(f"{label}{args!r}{kwargs!r}")
                return await fn(*args, **kwargs)

            return wrapper

        setattr(obj, name, make(original, name))


class TokenWitness:
    """Scope source wrapper that looks at what the SDK retained for the call."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.retained: list[str] = []

    async def derive(self, claims: VerifiedClaims) -> ScopeDerivation:
        access = get_access_token()
        assert isinstance(access, McpAccessToken)
        self.retained.append(access.model_dump_json())
        return await self.inner.derive(claims)


async def test_a_full_session_sends_nothing_out_and_leaks_the_bearer_nowhere(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    harness = cs.make_harness()
    witness = TokenWitness(harness.api.h.deriver)
    configure_authz(
        harness.app,
        authenticator=harness.api.h.validator,
        scope_source=witness,
        clock=harness.clock,
    )
    downstream: list[str] = []
    _record_calls(harness.world.catalog, ("get_entity", "list_entities"), downstream)
    _record_calls(harness.world.metrics, ("query",), downstream)
    _record_calls(harness.world.recs, ("list",), downstream)
    _record_calls(
        harness.api.actions,
        ("draft", "get", "record_validation", "present_confirmation"),
        downstream,
    )
    token = harness.token(cs.ALICE)
    outbound = _block_outbound(monkeypatch)
    bodies: list[str] = []

    with caplog.at_level(logging.DEBUG):
        async with cs.mcp_session(harness) as client:
            for method, params in (
                ("tools/list", None),
                ("resources/list", None),
                ("resources/read", {"uri": "neurosphere://scope/current"}),
                ("resources/read", {"uri": "neurosphere://recommendations/recent"}),
            ):
                response = await cs.rpc(client, method, params, token=token)
                assert response.status_code == 200, response.text
                bodies.append(response.text)
            for tool, args in (
                ("search_catalog", cs.query_args("agent")),
                ("get_cost_summary", cs.cost_args()),
                ("list_recommendations", cs.query_args("recommendation")),
            ):
                bodies.append(str(await cs.call_tool(client, token, tool, args)))
            draft = await cs.call_tool(client, token, "draft_action", cs.draft_args())
            bodies.append(str(draft))
            intent_id = cs.records(draft)[0]["data"]["intent_id"]
            for tool in ("validate_action", "present_action_confirmation", "get_action_status"):
                result = await cs.call_tool(client, token, tool, {"intent_id": intent_id})
                assert result["isError"] is False, result
                bodies.append(str(result))

    assert outbound.calls == []
    assert downstream, "the session reached the downstream ports"
    signature = token.rsplit(".", 1)[-1]
    for text in (*downstream, *bodies, *witness.retained):
        assert token not in text and signature not in text
    assert witness.retained and all(REDACTED_TOKEN in r for r in witness.retained)
    assert harness.api.connector.dry_runs  # the in-process connector saw only write requests
    assert all(token not in repr(r) for r in harness.api.connector.dry_runs)
    for record in caplog.records:
        rendered = f"{record.getMessage()} {record.__dict__!r}"
        assert token not in rendered and signature not in rendered


async def test_the_verifier_never_retains_the_raw_token() -> None:
    harness = cs.make_harness()
    token = harness.token(cs.ALICE)
    access = await harness.mount.verifier.verify_token(token)
    assert isinstance(access, McpAccessToken)
    assert access.token == REDACTED_TOKEN
    assert token not in access.model_dump_json()
    assert access.verified.audience == cs.MCP_AUDIENCE
