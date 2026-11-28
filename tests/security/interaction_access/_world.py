"""One world for the PRP-104 item 7 negative suite (no tests in this module).

Reuses, without editing, the item 3-5 harnesses in ``services/api/tests/interaction_explorer_api``
(those directories have no ``__init__.py``, so they are put on ``sys.path`` here and imported by
module name, as ``test_export`` imports ``test_content_read``): the PRP-06 dev-issuer authz
harness, the spying :class:`InMemoryInteractionStore` (counts every decrypt), the spying audit
repository (counts every append), the recording denial hook, and the spying export backend and
key wrapper (counts every bundle unwrap). What this module adds:

* the replay router of the SAME app (``create_app`` registers it by default) over an in-memory
  trace reader whose spans point at the world's interactions, so every content path shares one
  store, one audit, one denial log and one SIEM sink (an exporter on the audit repository);
* extra principals: an investigator of OPERATIONS who is a plain viewer of FINANCE (holds
  ``data.read`` but not ``interaction.read`` there);
* :meth:`World.retarget`, which swaps in an explorer of another cloud or customer over the same
  store and export storage (a deployment the caller does not belong to);
* :func:`luhn_card` / :func:`github_shaped_token` and :func:`redact_input`, which run the real
  PRP-101 redaction over an original input so the stored content is what capture would store.

Every canary, card and credential-shaped value is generated at runtime (gitleaks scans diffs).
"""

from __future__ import annotations

import asyncio
import os
import secrets
import string
import sys
import uuid
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final

import pytest

_API_TESTS = Path(__file__).resolve().parents[3] / "services" / "api" / "tests"
for _path in (
    _API_TESTS,
    _API_TESTS / "admin_identity_api",
    _API_TESTS / "interaction_explorer_api",
):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import authz.authz_helpers as helpers  # noqa: E402  # pyright: ignore[reportMissingImports]
import test_content_read as _cr  # noqa: E402  # pyright: ignore[reportMissingImports]
from neurosphere_api.interactions import (  # noqa: E402
    InteractionExplorer,
    configure_interaction_explorer,
)
from neurosphere_api.replay import PREFIX as REPLAY_PREFIX  # noqa: E402
from neurosphere_api.replay import get_trace_reader  # noqa: E402
from neurosphere_contracts.audit.v1.audit_record import AuditRecord  # noqa: E402
from neurosphere_contracts.interactions.v1.interaction_record import (  # noqa: E402
    InteractionRecord,
)
from neurosphere_contracts.interactions.v1.redacted_content import RedactedContent  # noqa: E402
from neurosphere_core.audit import SiemExporter  # noqa: E402
from neurosphere_core.auth.scope import Role  # noqa: E402
from neurosphere_core.classification import default_detector_set, redact  # noqa: E402
from neurosphere_core.classification.engine import Redacted  # noqa: E402
from neurosphere_core.interactions import interaction_pointer  # noqa: E402
from neurosphere_core.interactions.capture import redaction_config_for  # noqa: E402
from test_content_read import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    investigator_role,
    object_id,
)
from test_export import BODY as _BODY  # noqa: E402  # pyright: ignore[reportMissingImports]
from test_export import ExportApi  # noqa: E402  # pyright: ignore[reportMissingImports]
from test_replay_payload import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    TRACE,
    CountingReader,
    span,
)

__all__ = [
    "ADMIN",
    "ANALYST",
    "AUDITOR",
    "BODY",
    "CUSTOMER",
    "EXPIRING",
    "EXPIRY_SECONDS",
    "FINANCE",
    "GOV_FINANCE",
    "INVESTIGATOR",
    "INVESTIGATOR_ONLY",
    "OPERATIONS",
    "OPS_INVESTIGATOR",
    "OPS_INVESTIGATOR_FIN_VIEWER",
    "OTHER_CUSTOMER_FINANCE",
    "PURPOSE",
    "PURPOSE_PARAMS",
    "STEWARD",
    "VIEWER",
    "World",
    "canary",
    "clean_env",
    "content_for",
    "github_shaped_token",
    "luhn_card",
    "new_id",
    "payload_spans",
    "record_doc",
    "redact_input",
]

# Typed re-exports of the item 3 harness (its module is resolved only at run time).
ADMIN: str = _cr.ADMIN
ANALYST: str = _cr.ANALYST
AUDITOR: str = _cr.AUDITOR
CUSTOMER: str = _cr.CUSTOMER
EXPIRING: str = _cr.EXPIRING
EXPIRY_SECONDS: int = _cr.EXPIRY_SECONDS
FINANCE: str = _cr.FINANCE
GOV_FINANCE: str = _cr.GOV_FINANCE
INVESTIGATOR: str = _cr.INVESTIGATOR
INVESTIGATOR_ONLY: str = _cr.INVESTIGATOR_ONLY
OPERATIONS: str = _cr.OPERATIONS
OPS_INVESTIGATOR: str = _cr.OPS_INVESTIGATOR
OTHER_CUSTOMER_FINANCE: str = _cr.OTHER_CUSTOMER_FINANCE
PURPOSE: dict[str, Any] = _cr.PURPOSE
STEWARD: str = _cr.STEWARD
VIEWER: str = _cr.VIEWER
BODY: dict[str, Any] = _BODY


def record_doc(interaction_id: str, **overrides: Any) -> dict[str, Any]:
    return _cr.record_doc(interaction_id, **overrides)


#: Investigator of OPERATIONS who is only a viewer of FINANCE (data.read, no interaction.read).
OPS_INVESTIGATOR_FIN_VIEWER: Final = object_id()
PURPOSE_PARAMS: Final = {"purpose_code": PURPOSE["purpose_code"], "case_ref": PURPOSE["case_ref"]}

_PREFIXES: Final = (
    "NS_AUTH_",
    "NS_STORE_",
    "NS_CORS_",
    "NS_COSMOS_",
    "NS_REVOCATION_",
    "NS_GATEWAY_",
)
_NAMES: Final = (
    "NS_CLOUD",
    "NS_INGEST_PRODUCERS_FILE",
    "NS_SCAN_ENABLED",
    "NS_MCP_RESOURCE_SERVER_URL",
)
_ALNUM: Final = string.ascii_letters + string.digits


def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The interaction_explorer_api conftest's environment (it does not apply in this tree)."""
    for name in sorted(os.environ):
        if name.startswith(_PREFIXES) or name in _NAMES:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NS_ENV", "local")


def new_id() -> str:
    return str(uuid.uuid4())


def canary() -> str:
    """A unique marker. Letters only: a hex run is high-entropy and redaction would take it."""
    return (
        "CANARY-" + "PRP104-" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(20))
    )


def luhn_card() -> str:
    """A 16-digit Luhn-valid card-shaped number starting with 4 (built at runtime)."""
    digits = [4] + [secrets.randbelow(10) for _ in range(14)]
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = d * 2 if i % 2 == 0 else d
        total += n - 9 if n > 9 else n
    return "".join(map(str, digits)) + str((10 - total % 10) % 10)


def github_shaped_token() -> str:
    """A GitHub-token-shaped value the PRP-101 detectors redact, built from fragments."""
    body = list("".join(secrets.choice(_ALNUM) for _ in range(36)))
    body[0], body[1], body[2] = "Q", "q", "7"
    return "gh" + "p_" + "".join(body)


def redact_input(text: str) -> str:
    """The real PRP-101 redaction capture runs before anything is stored."""
    result = redact(
        text, part="prompt", config=redaction_config_for(()), detector_set=default_detector_set()
    )
    assert isinstance(result, Redacted), result
    return result.text


def content_for(interaction_id: str, text: str) -> RedactedContent:
    return RedactedContent.model_validate(
        {
            "schema_version": "1.0.0",
            "interaction_id": interaction_id,
            "redaction_state": "redacted",
            "detector_set_version": "detectors-1.0",
            "parts": [{"part": "prompt", "text": text, "truncated": False, "findings": []}],
        }
    )


class RecordingSiemSink:
    """A SIEM sink that keeps every event it is sent."""

    name = "recording"

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def emit(self, event: Mapping[str, Any]) -> None:
        self.events.append(dict(event))


class World(ExportApi):
    """Content reads, exports AND the replay payload branch over one store, audit and denials."""

    def __init__(self, tmp_path: Path, **kwargs: Any) -> None:
        super().__init__(tmp_path, **kwargs)
        self.h.repo.put_principal(
            helpers.policy(
                OPS_INVESTIGATOR_FIN_VIEWER,
                investigator_role(OPERATIONS, suffix="-ops-fin"),
                helpers.role(Role.VIEWER, FINANCE),
                helpers.role(Role.VIEWER, OPERATIONS),
            )
        )
        self.reader = CountingReader()
        self.h.app.dependency_overrides[get_trace_reader] = lambda: self.reader
        self._span = 0
        # A SIEM exporter on the audit repository: every appended record is also an event.
        self.siem = RecordingSiemSink()
        self.audit._exporter = SiemExporter([self.siem])  # pyright: ignore[reportPrivateUsage]

    # --- data -------------------------------------------------------------------------------------

    def put(self, iid: str, text: str, *, domain: str = FINANCE, **overrides: Any) -> None:
        """Store one interaction with ``text`` as its (already redacted) prompt, plus a span."""
        record = InteractionRecord.model_validate(record_doc(iid, domain_id=domain, **overrides))

        async def store() -> None:
            await self.store.put(record, content_for(iid, text), capture_retention_days=30)

        asyncio.run(store())
        self._span += 1
        self.reader.add(span(self._span, pointer=interaction_pointer(iid), domain=domain))

    def seed_marked(self, count: int = 1, *, domain: str = FINANCE) -> tuple[list[str], list[str]]:
        """``count`` interactions, each carrying a fresh canary; returns (ids, canaries)."""
        ids, marks = [], []
        for _ in range(count):
            iid, mark = new_id(), canary()
            self.put(iid, f"{mark} card [[ns-redacted:payment_card]]", domain=domain)
            ids.append(iid)
            marks.append(mark)
        return ids, marks

    # --- requests ---------------------------------------------------------------------------------

    def trace(self, who: str, *, domain: str = FINANCE, **params: Any) -> Any:
        return self.h.client.get(
            f"{REPLAY_PREFIX}/domains/{domain}/traces/{TRACE}",
            params=params or None,
            headers=self.h.auth(who),
        )

    def search(self, who: str, *, domain: str = FINANCE) -> Any:
        from neurosphere_api.interactions import PREFIX

        return self.h.client.get(f"{PREFIX}/{domain}/interactions", headers=self.h.auth(who))

    def detail(self, who: str, iid: str, *, domain: str = FINANCE) -> Any:
        from neurosphere_api.interactions import PREFIX

        return self.h.client.get(f"{PREFIX}/{domain}/interactions/{iid}", headers=self.h.auth(who))

    # --- deployments ------------------------------------------------------------------------------

    def retarget(self, *, cloud: str = "commercial", customer_id: str = CUSTOMER) -> None:
        """Install an explorer of another deployment over the same store, audit and exports."""
        configure_interaction_explorer(
            self.h.app,
            InteractionExplorer(
                store=self.store,
                audit=self.audit,
                cloud=cloud,
                customer_id=customer_id,
                exports=self.explorer.exports,
            ),
        )

    # --- counters and sinks -----------------------------------------------------------------------

    def counters(self) -> tuple[int, int, int]:
        """(record decrypts, bundle unwraps, audit append attempts)."""
        return self.store.content_reads, self.wrapper.unwraps, self.audit.attempts

    def all_audit_records(self) -> list[AuditRecord]:
        store = self.audit._store  # pyright: ignore[reportPrivateUsage]
        chains = sorted({chain for (chain, _doc) in store._docs})  # pyright: ignore[reportPrivateUsage]
        out: list[AuditRecord] = []
        for chain in chains:
            records = asyncio.run(self.audit.read_range(chain, start=0, limit=100))
            assert len(records) < 100, "scenario outgrew one audit range page"
            out.extend(records)
        return out

    def raw_audit_text(self) -> str:
        """Every stored audit document (records and chain tails), as stored."""
        store = self.audit._store  # pyright: ignore[reportPrivateUsage]
        return "\n".join(store._docs.values())  # pyright: ignore[reportPrivateUsage]


def payload_spans(response: Any) -> Iterator[Any]:
    for item in response.json()["spans"]:
        yield item["payload"]
