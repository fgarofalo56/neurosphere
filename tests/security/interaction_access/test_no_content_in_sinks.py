"""PRP-104 criteria 6 and 8: captured content stays out of every sink, and redacted-away values
stay out of everything.

One scenario seeds synthetic captured interactions whose ORIGINAL input carried a unique canary,
a Luhn-valid card number and a GitHub-token-shaped credential; the real PRP-101 redaction runs
first (as capture does), so only the canary and placeholders are stored. The scenario then drives
every PRP-104 path, allowed and refused: search, detail, content read, export create, manifest and
download, and the replay payload branch. Afterwards:

* the canaries appear ONLY in the three content-bearing responses (content read, bundle, replay
  payload) and never in a log record (every logger, every level), an audit record of any chain,
  a SIEM event, a denied-attempt record, a metadata response, the sealed bundle at rest, the
  committed ``services/api/openapi.json`` or the app's live OpenAPI document;
* the card number and the credential appear nowhere at all, responses and bundle included;
* an MCP session whose caller IS an unexpired investigator of the domain, on an app with the
  explorer installed, never sees a canary in ``tools/list`` or in any read tool's answer.

The copilot is covered structurally (``test_no_content_to_models``): its engine runs over the
ports it is built with, none of which reaches the interaction store, so a scripted turn here could
only prove what that test already proves.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from neurosphere_api.interactions import (
    InteractionExplorer,
    configure_interaction_explorer,
)
from neurosphere_core.audit import AuditRepository, InMemoryAuditStore, to_siem_event
from neurosphere_core.auth.scope import Role
from neurosphere_core.crypto import LocalFileKeyWrapper
from neurosphere_core.interactions import InMemoryInteractionStore

from ._world import (
    ADMIN,
    FINANCE,
    INVESTIGATOR,
    OPERATIONS,
    PURPOSE,
    PURPOSE_PARAMS,
    VIEWER,
    World,
    canary,
    clean_env,
    content_for,
    github_shaped_token,
    luhn_card,
    new_id,
    redact_input,
)

_REPO: Final = Path(__file__).resolve().parents[3]
OPENAPI: Final = _REPO / "services" / "api" / "openapi.json"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    clean_env(monkeypatch)


@pytest.fixture
def all_log_records(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[logging.LogRecord]]:
    """Every record any logger handles during the test, whatever its level or handlers."""
    seen: list[logging.LogRecord] = []
    original_handle = logging.Logger.handle

    def recording_handle(self: logging.Logger, record: logging.LogRecord) -> None:
        seen.append(record)
        original_handle(self, record)

    def always_enabled(self: logging.Logger, level: int) -> bool:
        del self, level
        return True

    monkeypatch.setattr(logging.Logger, "handle", recording_handle)
    monkeypatch.setattr(logging.Logger, "isEnabledFor", always_enabled)
    yield seen


def _record_text(record: logging.LogRecord) -> str:
    parts = [record.getMessage(), repr(record.msg), repr(record.args), repr(record.__dict__)]
    if record.exc_info:
        parts.append("".join(traceback.format_exception(*record.exc_info)))
    return "\n".join(parts)


def _hits(text: str, values: Iterable[str]) -> int:
    return sum(1 for value in values if value in text)


def _assert_clean(label: str, text: str, values: Iterable[str]) -> None:
    # Count only: a failing run must not echo the generated values either.
    assert _hits(text, values) == 0, f"{label} carries generated content"


class Seeded:
    """Interactions whose original input held a canary, a card and a credential."""

    def __init__(self, world: World, count: int, *, domain: str = FINANCE) -> None:
        self.ids: list[str] = []
        self.marks: list[str] = []
        self.removed: list[str] = []  # what redaction took out before storage
        for _ in range(count):
            iid, mark, card, token = new_id(), canary(), luhn_card(), github_shaped_token()
            original = f"Customer {mark} paid with {card} and pasted {token} by mistake."
            stored = redact_input(original)
            # Preconditions: redaction really removed both values and kept the canary.
            assert mark in stored and card not in stored and token not in stored
            assert "[[ns-redacted:" in stored
            world.put(iid, stored, domain=domain)
            self.ids.append(iid)
            self.marks.append(mark)
            self.removed.extend([card, token])


def test_canaries_stay_out_of_every_sink_and_redacted_values_out_of_everything(
    tmp_path: Path, all_log_records: list[logging.LogRecord], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    world = World(tmp_path)
    fin = Seeded(world, 2)
    ops = Seeded(world, 1, domain=OPERATIONS)
    marks = [*fin.marks, *ops.marks]
    removed = [*fin.removed, *ops.removed]
    c = world.h.client

    metadata = [
        world.search(INVESTIGATOR),
        world.search(VIEWER),
        world.detail(INVESTIGATOR, fin.ids[0]),
        world.detail(VIEWER, fin.ids[1]),
        world.detail(VIEWER, ops.ids[0]),  # another domain: 404
    ]
    read = world.read(INVESTIGATOR, fin.ids[0])
    refused = [
        world.read(VIEWER, fin.ids[0]),
        world.read(ADMIN, fin.ids[1]),
        world.read(INVESTIGATOR, ops.ids[0], domain=OPERATIONS),
        world.read(INVESTIGATOR, fin.ids[0], body={"purpose_code": "curiosity"}),
        world.create(VIEWER),
    ]
    created = world.create(INVESTIGATOR)
    assert created.status_code == 201, created.text
    export_id = created.json()["export_id"]
    manifest = world.manifest(INVESTIGATOR, export_id)
    refused += [world.manifest(ADMIN, export_id), world.bundle(VIEWER, export_id)]
    bundle = world.bundle(INVESTIGATOR, export_id)
    replay = world.trace(INVESTIGATOR, include_payload="true", **PURPOSE_PARAMS)
    replay_free = [
        world.trace(VIEWER, include_payload="true", **PURPOSE_PARAMS),
        world.trace(ADMIN, include_payload="true"),
        world.trace(INVESTIGATOR),
    ]
    live_openapi = c.get("/openapi.json")

    # The allowed content paths really returned content (so the absence checks are not vacuous).
    assert read.status_code == 200 and fin.marks[0] in read.text
    assert bundle.status_code == 200 and all(m in bundle.text for m in fin.marks)
    assert replay.status_code == 200 and all(m in replay.text for m in fin.marks)
    assert [r.status_code for r in refused] == [403, 403, 403, 422, 403, 403, 403]
    assert [r.status_code for r in metadata] == [200, 200, 200, 200, 404]
    assert len(world.denials.attempts) == 6  # one per 403; the 422 records nothing

    # 1. Redacted-away values: nowhere, content-bearing responses and the bundle included.
    responses = [*metadata, read, *refused, created, manifest, bundle, replay, *replay_free]
    for response in responses:
        _assert_clean(f"response {response.request.url.path}", response.text, removed)
    for blob in world.backend.blobs.values():
        _assert_clean("a stored export blob", blob.decode("latin-1"), [*removed, *marks])

    # 2. Canaries: only in the three content-bearing responses.
    for response in [*metadata, *refused, created, manifest, *replay_free]:
        _assert_clean(f"metadata response {response.request.url.path}", response.text, marks)
    assert ops.marks[0] not in replay.text  # another domain's span is withheld

    # 3. Logs: every record any logger made, plus caplog's view.
    assert all_log_records, "the log hook saw nothing"
    log_text = "\n".join(_record_text(r) for r in all_log_records)
    _assert_clean("a log record", log_text, [*marks, *removed])
    _assert_clean("caplog", caplog.text, [*marks, *removed])

    # 4. Audit, SIEM and denial records: ids, codes and digests only; no case reference.
    records = world.all_audit_records()
    operations = sorted({r.operation for r in records})
    assert {"interaction.read", "interaction.export", "interaction.export_download"} <= set(
        operations
    )
    audit_text = json.dumps([r.model_dump(mode="json") for r in records])
    audit_text += world.raw_audit_text()
    siem_text = json.dumps(world.siem.events) + json.dumps([to_siem_event(r) for r in records])
    assert len(world.siem.events) == len(records)
    denial_text = "\n".join(repr(a) for a in world.denials.attempts)
    case_ref = str(PURPOSE["case_ref"])
    for label, text in (("audit", audit_text), ("SIEM", siem_text), ("denial", denial_text)):
        _assert_clean(f"a {label} record", text, [*marks, *removed, case_ref])

    # 5. OpenAPI: the committed document and the app's live one.
    assert live_openapi.status_code == 200
    _assert_clean("the live OpenAPI document", live_openapi.text, [*marks, *removed])
    _assert_clean("services/api/openapi.json", OPENAPI.read_text(encoding="utf-8"), marks)


def test_committed_openapi_carries_no_canary_or_content_example() -> None:
    """No captured-looking text in any example of the committed document."""
    text = OPENAPI.read_text(encoding="utf-8")
    for marker in ("CANARY-" + "PRP104", "NSCANARY", "NSCANARY-"):
        assert marker not in text
    doc = json.loads(text)

    def examples(node: Any) -> Iterator[Any]:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in ("example", "examples"):
                    yield value
                yield from examples(value)
        elif isinstance(node, list):
            for value in node:
                yield from examples(value)

    for example in examples(doc):
        dumped = json.dumps(example)
        assert "[[ns-redacted:" not in dumped  # no stored-content sample is published


# --- MCP: an investigator's session never reaches content -----------------------------------------

_MCP_API: Final = _REPO / "services" / "api" / "tests" / "mcp_api"


def _mcp_harness() -> Any:
    if str(_MCP_API) not in sys.path:
        sys.path.insert(0, str(_MCP_API))
    import conftest_server as cs  # pyright: ignore[reportMissingImports]

    return cs


async def test_an_investigators_mcp_session_never_sees_captured_content(tmp_path: Path) -> None:
    cs = _mcp_harness()
    harness = cs.make_harness()
    helpers = cs.helpers
    # The MCP caller is an unexpired FINANCE investigator AND a steward: the most a person can be.
    harness.api.h.repo.put_principal(
        helpers.policy(
            cs.ALICE,
            helpers.role(Role.DOMAIN_STEWARD, cs.FINANCE),
            helpers.role(Role.INTERACTION_INVESTIGATOR, cs.FINANCE, expires_in=3 * 24 * 3600),
        )
    )
    store = InMemoryInteractionStore(
        LocalFileKeyWrapper(tmp_path / "kek.bin"),
        kek_uri="https://synthetic-kv.vault.azure.net/keys/ns-content-kek",
        policy=_retention(),
    )
    marks: list[str] = []
    for _ in range(2):
        iid, mark = new_id(), canary()
        marks.append(mark)
        await store.put(_record(iid, cs.FINANCE), content_for(iid, mark), capture_retention_days=30)
    configure_interaction_explorer(
        harness.app,
        InteractionExplorer(
            store=store,
            audit=AuditRepository(InMemoryAuditStore()),
            cloud="commercial",
            customer_id=cs.CUSTOMER,
        ),
    )
    texts: list[str] = []
    async with cs.mcp_session(harness) as client:
        token = harness.token(cs.ALICE)
        listed = await cs.rpc(client, "tools/list", token=token)
        assert listed.status_code == 200, listed.text
        texts.append(listed.text)
        names = sorted(t["name"] for t in listed.json()["result"]["tools"])
        assert not [n for n in names if "interaction" in n or "content" in n]
        calls = [
            ("search_catalog", cs.query_args("agent")),
            ("search_catalog", cs.query_args("interaction")),
            ("list_recommendations", cs.query_args("recommendation")),
            ("get_cost_summary", cs.cost_args()),
        ]
        for tool, arguments in calls:
            response = await cs.rpc(
                client, "tools/call", {"name": tool, "arguments": arguments}, token=token
            )
            assert response.status_code == 200, response.text
            texts.append(response.text)
        resources = await cs.rpc(client, "resources/list", token=token)
        texts.append(resources.text)
    for text in texts:
        _assert_clean("an MCP response", text, marks)


def _retention() -> Any:
    from neurosphere_core.lifecycle.policy import load_policy

    return load_policy(
        {
            "policy_version": "v1",
            "rules": [
                {
                    "data_class": "telemetry_event",
                    "min_retention_days": 0,
                    "max_retention_days": 30,
                },
                {
                    "data_class": "interaction_content",
                    "min_retention_days": 0,
                    "max_retention_days": 90,
                },
            ],
            "retain_prompt_response_bodies": True,
        }
    )


def _record(iid: str, domain: str) -> Any:
    from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord

    from ._world import record_doc

    return InteractionRecord.model_validate(record_doc(iid, domain_id=domain))
