"""Shared builders for the PRP-102 item 6 security negative suite (synthetic data only).

Every canary, key, vault host and credential-shaped value is generated at runtime: no
credential-shaped literal lives in this tree (gitleaks and ``.githooks`` scan diffs). Small
helpers are copied from ``packages/core/tests/interaction_store`` and
``services/workers/tests/lifecycle_interactions`` rather than imported (separate test packages).
"""

from __future__ import annotations

import base64
import hashlib
import itertools
import json
import logging
import os
import uuid
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx
from neurosphere_contracts.interactions.v1.interaction_record import InteractionRecord
from neurosphere_contracts.interactions.v1.redacted_content import RedactedContent
from neurosphere_contracts.scope.v1.identity_scope import IdentityScope as ContractScope
from neurosphere_core.audit import AuditContext, AuditRepository, InMemoryAuditStore
from neurosphere_core.crypto import KeyWrapper, WrappedKey
from neurosphere_core.interactions import EncryptedInteractionStore
from neurosphere_core.interactions.lifecycle_delete import (
    InteractionLifecycleBackend,
    InteractionTarget,
    interaction_target,
)
from neurosphere_core.interactions.store import METRIC_INTERACTION_REFUSALS
from neurosphere_core.lifecycle import LifecycleEngine, PolicyState, TargetRegistry, load_policy
from neurosphere_core.lifecycle.memory import (
    InMemoryHoldRegistry,
    InMemoryMappingStore,
    InMemoryRequestQueue,
)
from neurosphere_core.scope import IdentityScope
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

CUSTOMER: Final = "acme"
DOMAIN: Final = "commercial:acme:neurosphere:domain:support"
OTHER_DOMAIN: Final = "commercial:acme:neurosphere:domain:sales/emea"
CAPTURED_AT: Final = "2026-11-20T10:15:01Z"
CAPTURED: Final = datetime(2026, 11, 20, 10, 15, 1, tzinfo=UTC)
#: Past the 90-day interaction rule: every stored record is due for expiry.
EXPIRED_NOW: Final = CAPTURED + timedelta(days=100)
#: The PRP-101 placeholder that replaced the generated credential-shaped value.
PLACEHOLDER: Final = "[[ns-redacted:vendor_api_key]]"
COMMERCIAL_SUFFIX: Final = ".vault.azure.net"
GOVERNMENT_SUFFIX: Final = ".vault.usgovcloudapi.net"


def canary() -> str:
    return "NSCANARY" + uuid.uuid4().hex.upper()


def new_id() -> str:
    return str(uuid.uuid4())


def fake_vendor_key() -> str:
    """A credential-shaped value, built from fragments; it never reaches the store."""
    return "s" + "k-" + (uuid.uuid4().hex + uuid.uuid4().hex)[:40]


def secret_shaped_texts() -> dict[str, str]:
    """One value per ``secret_free_text`` ``not`` family, assembled from fragments at runtime."""
    alnum = (uuid.uuid4().hex[:6] + "Ab3") * 4
    alpha = "".join(c for c in uuid.uuid4().hex.upper() if c.isalpha()) + "QRSTUVWXYZQRSTUV"
    return {
        "private_key": "-----BEGIN " + "RSA PRIVATE" + " KEY-----",
        "jwt": "ey" + "J" + alnum[:10] + "." + alnum[:10] + "." + alnum[:6],
        "bearer": "Bear" + "er " + alnum[:16],
        "aws_key_id": "AK" + "IA" + alpha[:16],
        "github_token": "gh" + "p_" + alnum[:24],
        "sk_key": "s" + "k-" + alnum[:24],
        "storage_key": "Account" + "Key=" + alnum[:12],
        "sas_signature": "s" + "ig=" + alnum[:24],
        "url_userinfo": "https://"
        + "user"
        + ":"
        + "pw"
        + uuid.uuid4().hex[:6]
        + "@example.invalid/x",
    }


@dataclass(frozen=True)
class Corpus:
    """Part texts carrying distinct canaries; ``forbidden`` must never appear in clear."""

    texts: tuple[str, ...]
    canaries: tuple[str, ...]
    replaced_value: str

    @property
    def forbidden(self) -> tuple[str, ...]:
        return (*self.canaries, self.replaced_value)


def build_corpus() -> Corpus:
    canaries = tuple(canary() for _ in range(6))
    replaced = fake_vendor_key()
    texts = (
        "customer " + canaries[0] + " asked about invoice " + canaries[1],
        "agent answered with " + canaries[2] + " and key " + PLACEHOLDER,
        "tool input " + canaries[3] + " " + canaries[4],
        "tool output " + canaries[5],
    )
    assert replaced not in "".join(texts)
    return Corpus(texts=texts, canaries=canaries, replaced_value=replaced)


def policy(*, opt_in: bool = True, rule: bool = True, max_days: int = 90) -> PolicyState:
    rules: list[dict[str, Any]] = [
        {"data_class": "telemetry_event", "min_retention_days": 0, "max_retention_days": 30}
    ]
    if rule:
        rules.append(
            {
                "data_class": "interaction_content",
                "min_retention_days": 0,
                "max_retention_days": max_days,
            }
        )
    return load_policy(
        {"policy_version": "v1", "rules": rules, "retain_prompt_response_bodies": opt_in}
    )


def make_record(interaction_id: str, **overrides: Any) -> InteractionRecord:
    doc: dict[str, Any] = {
        "schema_version": "1.2.0",
        "interaction_id": interaction_id,
        "cloud": "commercial",
        "customer_id": CUSTOMER,
        "domain_id": DOMAIN,
        "source_id": "otel-gateway",
        "event_id": "evt-" + interaction_id[:8],
        "correlation_id": "corr-" + interaction_id[:8],
        "capture_source": "edge_push",
        "occurred_at": "2026-11-20T10:15:00Z",
        "captured_at": CAPTURED_AT,
        "agent_id": "commercial:acme:neurosphere:agent:support-bot",
        "tool_id": None,
        "principal_id": None,
        "capture_policy_id": "support-capture",
        "capture_policy_version": 2,
        "detector_set_version": "detectors-1.0",
        "redaction_state": "redacted",
        "parts": [{"part": "prompt", "char_count": 40, "truncated": False}],
        "content_ref": None,
        "findings_summary": [{"category": "vendor_api_key", "count": 1, "action": "replaced"}],
        "sensitivity_categories": ["pii"],
        "data_asset_ids": [],
        "expires_at": "2027-02-18T10:15:01Z",
    }
    doc.update(overrides)
    return InteractionRecord.model_validate(doc)


_KINDS: Final = ("prompt", "response", "tool_input", "tool_output", "system_instructions")


def content_doc(
    interaction_id: str, texts: Iterable[str], state: str = "redacted"
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "interaction_id": interaction_id,
        "redaction_state": state,
        "detector_set_version": "detectors-1.0",
        "parts": [
            {"part": _KINDS[i], "text": text, "truncated": False, "findings": []}
            for i, text in enumerate(texts)
        ],
    }


def make_content(interaction_id: str, texts: Iterable[str]) -> RedactedContent:
    return RedactedContent.model_validate(content_doc(interaction_id, texts))


class SpyWrapper:
    """Delegates to a real key wrapper; records every data key and wrapped value it sees."""

    def __init__(self, inner: KeyWrapper) -> None:
        self._inner = inner
        self.wrap_calls = 0
        self.unwrap_calls = 0
        self.data_keys: list[bytes] = []
        self.wrapped_values: list[bytes] = []

    @property
    def key_id(self) -> str:
        return self._inner.key_id

    async def wrap(self, data_key: bytes) -> WrappedKey:
        self.wrap_calls += 1
        self.data_keys.append(data_key)
        wrapped = await self._inner.wrap(data_key)
        self.wrapped_values.append(wrapped.value)
        return wrapped

    async def unwrap(self, wrapped: WrappedKey) -> bytes:
        self.unwrap_calls += 1
        self.wrapped_values.append(wrapped.value)
        data_key = await self._inner.unwrap(wrapped)
        self.data_keys.append(data_key)
        return data_key


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass
class FakeVault:
    """An ``httpx.MockTransport`` Key Vault with a random host, key name and version."""

    suffix: str = COMMERCIAL_SUFFIX
    label: str = field(default_factory=lambda: "nsv" + uuid.uuid4().hex[:12])
    key_name: str = field(default_factory=lambda: "nskek-" + uuid.uuid4().hex[:10])
    version: str = field(default_factory=lambda: os.urandom(16).hex())
    #: When set, every request raises an httpx error that names the request URL.
    broken: bool = False
    requests: list[httpx.Request] = field(default_factory=list)
    handles: dict[bytes, bytes] = field(default_factory=dict)

    @property
    def host(self) -> str:
        return self.label + self.suffix

    @property
    def key_uri(self) -> str:
        return f"https://{self.host}/keys/{self.key_name}"

    @property
    def kid(self) -> str:
        return f"{self.key_uri}/{self.version}"

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.broken:
            raise httpx.ConnectError(f"cannot reach {request.url}", request=request)
        if request.method == "GET":
            return httpx.Response(200, json={"key": {"kid": self.kid, "kty": "RSA"}})
        body = json.loads(request.content)
        value = _b64url_decode(body["value"])
        if request.url.path.endswith("/wrapkey"):
            handle = os.urandom(256)
            self.handles[handle] = value
            return httpx.Response(200, json={"kid": self.kid, "value": _b64url(handle)})
        if value not in self.handles:
            return httpx.Response(400, json={"error": {"code": "BadParameter"}})
        return httpx.Response(200, json={"kid": self.kid, "value": _b64url(self.handles[value])})


class TokenSpy:
    def __init__(self) -> None:
        self.calls = 0
        self.issued: list[str] = []

    async def __call__(self) -> str:
        self.calls += 1
        token = "test-bearer-" + uuid.uuid4().hex
        self.issued.append(token)
        return token


# --- leak detection -------------------------------------------------------------------------------


def encodings(value: bytes) -> list[bytes]:
    """Raw, UTF-16, hex, base64 and base64url forms of ``value`` (base64 at every alignment).

    A base64 encoding of ``value`` embedded in a longer byte string depends on its offset modulo
    3, so each alignment contributes the run of characters determined by ``value`` alone.
    """
    out = [value, value.hex().encode(), value.hex().upper().encode()]
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is not None:
        out += [text.encode("utf-16-le"), text.encode("utf-16-be")]
    for encode in (base64.b64encode, base64.urlsafe_b64encode):
        for offset in range(3):
            encoded = encode(b"\x00" * offset + value + b"\x00\x00\x00")
            if offset:
                encoded = encoded[4:]
            out.append(encoded[: (len(value) - (3 - offset) % 3) // 3 * 4])
    return [needle for needle in out if len(needle) >= 8]


def found(haystack: bytes, values: Iterable[str | bytes]) -> list[str]:
    """Which ``values`` (in any encoding from :func:`encodings`) occur in ``haystack``."""
    hits: list[str] = []
    for value in values:
        raw = value.encode("utf-8") if isinstance(value, str) else value
        if any(needle in haystack for needle in encodings(raw)):
            hits.append(repr(value)[:24] + "...")
    return hits


def exception_chain(exc: BaseException) -> Iterator[BaseException]:
    """``exc`` and everything reachable through ``__cause__`` and ``__context__``."""
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                pending.append(linked)


def exception_text(exc: BaseException) -> str:
    parts: list[str] = []
    for link in exception_chain(exc):
        parts += [type(link).__name__, str(link), repr(link), repr(link.args)]
        parts += [repr(note) for note in getattr(link, "__notes__", ())]
    return "\n".join(parts)


def log_text(records: Iterable[logging.LogRecord]) -> str:
    parts: list[str] = []
    for record in records:
        parts += [record.name, record.getMessage(), repr(record.args), repr(vars(record))]
        if record.exc_info and record.exc_info[1] is not None:
            parts.append(exception_text(record.exc_info[1]))
    return "\n".join(parts)


def refusal_points(reader: InMemoryMetricReader) -> dict[str, int]:
    data = reader.get_metrics_data()
    counts: dict[str, int] = {}
    if data is None:
        return counts
    for resource in data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name != METRIC_INTERACTION_REFUSALS:
                    continue
                for point in metric.data.data_points:
                    reason = str(point.attributes.get("ns.reason"))  # type: ignore[union-attr]
                    counts[reason] = counts.get(reason, 0) + int(point.value)  # type: ignore[attr-defined]
    return counts


def index_dump(documents: Mapping[Any, Mapping[str, Any]]) -> str:
    return json.dumps(list(documents.values()), sort_keys=True, ensure_ascii=False)


def all_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            keys.add(str(key))
            keys |= all_keys(item)
    elif isinstance(value, list | tuple):
        for item in value:
            keys |= all_keys(item)
    return keys


# --- lifecycle ---------------------------------------------------------------------------------


def _make_scope() -> IdentityScope:
    contract = ContractScope.model_validate(
        {
            "schema_version": "1.0.0",
            "cloud": "commercial",
            "customer_id": CUSTOMER,
            "principal": {
                "principal_id": "commercial:acme:entra:person:psn_0123456789abcdef",
                "principal_pseudonym": "p-7f3a9c21",
                "principal_kind": "user",
            },
            "roles": [],
            "allowed_domains": [DOMAIN, OTHER_DOMAIN],
            "allowed_resources": [],
            "policy_version": "v1",
            "derived_at": "2026-10-10T00:00:00Z",
            "scope_hash": "sha256:" + hashlib.sha256(b"scope").hexdigest(),
        }
    )
    return IdentityScope._from_verified_contract(contract)  # pyright: ignore[reportPrivateUsage]


def lifecycle_ctx() -> AuditContext:
    return AuditContext.from_scope(
        _make_scope(), correlation_id="corr-102i6", operation="lifecycle.run", channel="worker"
    )


def lifecycle_for(
    store: EncryptedInteractionStore, *, now: datetime = EXPIRED_NOW
) -> tuple[LifecycleEngine, InteractionTarget]:
    """A real lifecycle engine over ``store``'s backends (execute mode, synthetic clock)."""
    target = interaction_target(
        "interaction_index",
        InteractionLifecycleBackend(store.index, store.content, customer_id=CUSTOMER),
    )
    registry = TargetRegistry()
    registry.register(target)
    counter = itertools.count(1)
    audit = AuditRepository(
        InMemoryAuditStore(),
        clock=lambda: now,
        id_factory=lambda: f"00000000-0000-4000-8000-{next(counter):012d}",
    )
    engine = LifecycleEngine(
        policy=policy(),
        targets=registry,
        holds=InMemoryHoldRegistry(),
        queue=InMemoryRequestQueue(),
        audit=audit,
        audit_chain_id="lifecycle.acme",
        cloud="commercial",
        customer_id=CUSTOMER,
        mappings=InMemoryMappingStore(set()),
        clock=lambda: now,
        mode="execute",
    )
    return engine, target
