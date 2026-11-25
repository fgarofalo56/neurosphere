"""The interaction store: a metadata index plus envelope-encrypted content (PRP-102 item 4).

Write path (:meth:`EncryptedInteractionStore.put`), every refusal before any I/O:

1. the retention gate :func:`content_writes_enabled` (a valid customer retention policy that
   opts in to bodies AND has an ``interaction_content`` rule), else
   ``content_retention_not_enabled`` (counted, never logged with content);
2. :func:`validate_redacted_content`: the ``RedactedContent`` JSON Schema, including the
   ``secret_free_text`` ``not`` patterns Pydantic ignores (ADR-0004), else
   ``content_not_secret_free``;
3. the record and the content must agree (``content_record_mismatch``) and the key vault must be
   on the record's cloud (``key_host_refused``); a present index document is
   ``interaction_exists``;
4. seal with a fresh data key, AAD = customer, domain, interaction id and format version;
5. write the envelope blob (create-only), then create the index document with ``content_ref``
   and ``expires_at``; if the index write fails the blob is deleted (best effort, counted).

The write API takes only ``RedactedContent``; there is no method that stores ``str`` or
``bytes``. Reads check the index ``byte_length`` and ``ciphertext_sha256`` before decrypting
(``content_integrity_failed``); an index document whose blob is gone answers
``content_purged``. :meth:`~EncryptedInteractionStore.delete` removes the blob, then the index
document, and is idempotent so a rerun completes an interrupted purge.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import timedelta
from functools import cache
from importlib import resources
from typing import Any, Final, Protocol, runtime_checkable
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from neurosphere_contracts.interactions.v1.interaction_record import (
    EncryptedObjectRef,
    InteractionRecord,
)
from neurosphere_contracts.interactions.v1.redacted_content import RedactedContent
from opentelemetry import metrics as otel_metrics
from opentelemetry.metrics import Meter
from pydantic import ValidationError

from neurosphere_core.cloud import CloudName
from neurosphere_core.crypto import (
    CONTENT_INTEGRITY_FAILED,
    KEY_HOST_REFUSED,
    Envelope,
    EnvelopeError,
    KeyWrapper,
    canonical_aad,
    open_envelope,
    seal,
)
from neurosphere_core.crypto.keyvault import VAULT_SUFFIXES
from neurosphere_core.interactions.blob_content import (
    ContentBackend,
    InMemoryInteractionContent,
    content_blob_name,
)
from neurosphere_core.interactions.cosmos_index import IndexBackend, InMemoryInteractionIndex
from neurosphere_core.interactions.models import (
    CONTENT_NOT_SECRET_FREE,
    CONTENT_PURGED,
    CONTENT_RECORD_MISMATCH,
    CONTENT_RETENTION_NOT_ENABLED,
    DATA_CLASS_INTERACTION,
    INTERACTION_EXISTS,
    INTERACTION_NOT_FOUND,
    IndexPage,
    InteractionQuery,
    InteractionStoreError,
    format_timestamp,
    parse_timestamp,
)
from neurosphere_core.lifecycle.policy import PolicyState

__all__ = [
    "CONTENT_ALGORITHM",
    "CONTENT_FORMAT_VERSION",
    "METRIC_INTERACTION_ORPHAN_CLEANUP",
    "METRIC_INTERACTION_REFUSALS",
    "EncryptedInteractionStore",
    "InMemoryInteractionStore",
    "InteractionStore",
    "content_aad",
    "content_writes_enabled",
    "redacted_content_schema",
    "validate_redacted_content",
]

_LOG = logging.getLogger(__name__)
_METER_NAME: Final = "neurosphere_core.interactions"
METRIC_INTERACTION_REFUSALS: Final = "ns.interactions.store.refusals"
METRIC_INTERACTION_ORPHAN_CLEANUP: Final = "ns.interactions.store.orphan_cleanup"
#: The ``format`` field bound into the AAD; bump only with a new content layout.
CONTENT_FORMAT_VERSION: Final = "1"
CONTENT_ALGORITHM: Final = "aes_256_gcm"
_SCHEMA_RESOURCE: Final = "redacted_content.schema.json"
_MAX_CAPTURE_RETENTION_DAYS: Final = 365
_STORABLE_STATES: Final = frozenset({"redacted", "not_required"})


# --- retention gate ------------------------------------------------------------------------------


def content_writes_enabled(policy_state: PolicyState) -> bool:
    """True only under a valid policy that keeps bodies AND has an ``interaction_content`` rule."""
    if not isinstance(policy_state, PolicyState) or not policy_state.bodies_retained:
        return False
    policy = policy_state.policy
    return policy is not None and policy.rule_for(DATA_CLASS_INTERACTION) is not None


# --- content validation --------------------------------------------------------------------------


@cache
def redacted_content_schema() -> Mapping[str, Any]:
    """The vendored, self-contained RedactedContent JSON Schema (package data)."""
    text = (
        resources.files("neurosphere_core.interactions")
        .joinpath(_SCHEMA_RESOURCE)
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


@cache
def _validator() -> Draft202012Validator:
    schema = redacted_content_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_redacted_content(doc: object) -> RedactedContent:
    """JSON Schema (including the ``not`` patterns) then Pydantic; else ``content_not_secret_free``.

    Neither the document nor any validator message is ever placed in the exception.
    """
    if not isinstance(doc, Mapping):
        raise InteractionStoreError(CONTENT_NOT_SECRET_FREE)
    try:
        valid = _validator().is_valid(doc)
    except Exception:
        valid = False
    if not valid:
        raise InteractionStoreError(CONTENT_NOT_SECRET_FREE)
    try:
        return RedactedContent.model_validate(dict(doc))
    except ValidationError:
        raise InteractionStoreError(CONTENT_NOT_SECRET_FREE) from None


def _content_document(content: object) -> dict[str, Any]:
    if not isinstance(content, RedactedContent):
        raise InteractionStoreError(CONTENT_NOT_SECRET_FREE)
    try:
        return content.model_dump(mode="json", warnings=False)
    except Exception:
        raise InteractionStoreError(CONTENT_NOT_SECRET_FREE) from None


def content_aad(customer_id: str, domain_id: str, interaction_id: str) -> bytes:
    """The associated data binding an envelope to exactly one interaction."""
    return canonical_aad(
        {
            "customer_id": customer_id,
            "domain_id": domain_id,
            "interaction_id": interaction_id,
            "format": CONTENT_FORMAT_VERSION,
        }
    )


def _plaintext(doc: Mapping[str, Any]) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


# --- the store -----------------------------------------------------------------------------------


@runtime_checkable
class InteractionStore(Protocol):
    """Opt-in captured interaction content: write redacted content, read, query, delete."""

    async def put(
        self, record: InteractionRecord, content: RedactedContent, *, capture_retention_days: int
    ) -> InteractionRecord: ...

    async def get_metadata(
        self, customer_id: str, domain_id: str, interaction_id: str
    ) -> InteractionRecord | None: ...

    async def read_content(
        self, customer_id: str, domain_id: str, interaction_id: str
    ) -> RedactedContent: ...

    async def query_index(self, query: InteractionQuery) -> IndexPage: ...

    async def delete(self, customer_id: str, domain_id: str, interaction_id: str) -> bool: ...


PolicySource = PolicyState | Callable[[], PolicyState]


class EncryptedInteractionStore:
    """:class:`InteractionStore` composed of an index, a content backend and a key wrapper.

    ``kek_uri`` is what the index records as ``content_ref.kek_uri`` (the configured key
    identifier, see ``InteractionSettings.content_kek_uri``). ``policy`` is the customer
    retention state, or a callable returning the current one (re-read on every write so turning
    the opt-in off stops writes immediately).
    """

    def __init__(
        self,
        index: IndexBackend,
        content: ContentBackend,
        wrapper: KeyWrapper,
        *,
        kek_uri: str,
        policy: PolicySource,
        meter: Meter | None = None,
    ) -> None:
        self._index = index
        self._content = content
        self._wrapper = wrapper
        self._kek_uri = kek_uri
        self._policy = policy
        meter = meter or otel_metrics.get_meter(_METER_NAME)
        self._refusal_counter = meter.create_counter(METRIC_INTERACTION_REFUSALS, unit="{write}")
        self._orphan_counter = meter.create_counter(
            METRIC_INTERACTION_ORPHAN_CLEANUP, unit="{blob}"
        )
        #: In-process tallies (reason -> count); the meter is the operational signal.
        self.refusals: Counter[str] = Counter()
        self.orphan_cleanups: Counter[str] = Counter()

    @property
    def index(self) -> IndexBackend:
        return self._index

    @property
    def content(self) -> ContentBackend:
        return self._content

    def _policy_state(self) -> PolicyState:
        source = self._policy
        return source if isinstance(source, PolicyState) else source()

    def _refuse(self, reason: str) -> None:
        self.refusals[reason] += 1
        self._refusal_counter.add(1, {"ns.reason": reason})
        _LOG.info("interaction content write refused", extra={"reason": reason})

    def _orphan(self, outcome: str) -> None:
        self.orphan_cleanups[outcome] += 1
        self._orphan_counter.add(1, {"ns.outcome": outcome})

    async def put(
        self, record: InteractionRecord, content: RedactedContent, *, capture_retention_days: int
    ) -> InteractionRecord:
        try:
            return await self._put(record, content, capture_retention_days)
        except (InteractionStoreError, EnvelopeError) as exc:
            self._refuse(exc.reason)
            raise

    async def _put(
        self, record: InteractionRecord, content: RedactedContent, capture_retention_days: int
    ) -> InteractionRecord:
        # 1. retention gate, before anything else
        state = self._policy_state()
        if not content_writes_enabled(state):
            raise InteractionStoreError(CONTENT_RETENTION_NOT_ENABLED)
        rule = state.policy.rule_for(DATA_CLASS_INTERACTION) if state.policy else None
        if rule is None:  # pragma: no cover - guarded by content_writes_enabled
            raise InteractionStoreError(CONTENT_RETENTION_NOT_ENABLED)

        # 2. content: JSON Schema incl. the secret-free `not` patterns, then Pydantic
        validated = validate_redacted_content(_content_document(content))

        # 3. record checks
        if not isinstance(record, InteractionRecord):
            raise TypeError("put takes an InteractionRecord")
        if (
            isinstance(capture_retention_days, bool)
            or not isinstance(capture_retention_days, int)
            or not 1 <= capture_retention_days <= _MAX_CAPTURE_RETENTION_DAYS
        ):
            raise ValueError("capture_retention_days must be an integer from 1 to 365")
        body = record.model_dump(mode="json")
        customer_id: str = body["customer_id"]
        domain_id: str = body["domain_id"]
        interaction_id: str = body["interaction_id"]
        if (
            validated.interaction_id.root != interaction_id
            or validated.redaction_state != body["redaction_state"]
            or body["redaction_state"] not in _STORABLE_STATES
            or validated.detector_set_version != body["detector_set_version"]
        ):
            raise InteractionStoreError(CONTENT_RECORD_MISMATCH)
        host = (urlsplit(self._kek_uri).hostname or "").lower()
        if not host.endswith(VAULT_SUFFIXES[CloudName(body["cloud"])]):
            raise EnvelopeError(KEY_HOST_REFUSED)
        captured = parse_timestamp(body["captured_at"])
        name = content_blob_name(customer_id, domain_id, captured, interaction_id)
        if await self._index.get(customer_id, domain_id, interaction_id) is not None:
            raise InteractionStoreError(INTERACTION_EXISTS)

        # 4. seal
        aad = content_aad(customer_id, domain_id, interaction_id)
        envelope_bytes = (
            await seal(_plaintext(validated.model_dump(mode="json")), aad, self._wrapper)
        ).to_bytes()

        # 5. blob first, then the index document
        await self._content.put(name, envelope_bytes)
        expires = captured + timedelta(days=min(capture_retention_days, rule.max_retention_days))
        body["captured_at"] = format_timestamp(captured)
        body["expires_at"] = format_timestamp(expires)
        body["content_ref"] = EncryptedObjectRef(
            pointer=name,
            kek_uri=self._kek_uri,
            algorithm=CONTENT_ALGORITHM,
            ciphertext_sha256=hashlib.sha256(envelope_bytes).hexdigest(),
            byte_length=len(envelope_bytes),
        ).model_dump(mode="json")
        try:
            stored = InteractionRecord.model_validate(body)
            await self._index.create(stored)
        except BaseException:
            await self._remove_orphan(name)
            raise
        return stored

    async def _remove_orphan(self, name: str) -> None:
        try:
            await self._content.delete(name)
        except Exception:
            self._orphan("failed")
            return
        self._orphan("removed")

    async def get_metadata(
        self, customer_id: str, domain_id: str, interaction_id: str
    ) -> InteractionRecord | None:
        return await self._index.get(customer_id, domain_id, interaction_id)

    async def read_content(
        self, customer_id: str, domain_id: str, interaction_id: str
    ) -> RedactedContent:
        record = await self._index.get(customer_id, domain_id, interaction_id)
        if record is None:
            raise InteractionStoreError(INTERACTION_NOT_FOUND)
        ref = record.content_ref
        if ref is None:
            raise InteractionStoreError(CONTENT_PURGED)
        expected = content_blob_name(
            customer_id, domain_id, parse_timestamp(record.captured_at.root), interaction_id
        )
        if ref.pointer != expected:
            raise EnvelopeError(CONTENT_INTEGRITY_FAILED)
        stored = await self._content.get(ref.pointer)
        if stored is None:
            raise InteractionStoreError(CONTENT_PURGED)
        if len(stored) != ref.byte_length or (
            hashlib.sha256(stored).hexdigest() != ref.ciphertext_sha256
        ):
            raise EnvelopeError(CONTENT_INTEGRITY_FAILED)
        envelope = Envelope.from_bytes(stored)
        plaintext = await open_envelope(
            envelope, content_aad(customer_id, domain_id, interaction_id), self._wrapper
        )
        try:
            doc = json.loads(plaintext.decode("utf-8"))
            content = validate_redacted_content(doc)
        except (ValueError, InteractionStoreError):
            raise EnvelopeError(CONTENT_INTEGRITY_FAILED) from None
        finally:
            del plaintext
        if content.interaction_id.root != interaction_id:
            raise EnvelopeError(CONTENT_INTEGRITY_FAILED)
        return content

    async def query_index(self, query: InteractionQuery) -> IndexPage:
        return await self._index.query(query)

    async def delete(self, customer_id: str, domain_id: str, interaction_id: str) -> bool:
        """Blob first, then the index document. Idempotent: a rerun completes a partial purge."""
        record = await self._index.get(customer_id, domain_id, interaction_id)
        if record is None:
            return False
        if record.content_ref is not None:
            await self._content.delete(record.content_ref.pointer)
        await self._index.delete(customer_id, domain_id, interaction_id)
        return True


class InMemoryInteractionStore(EncryptedInteractionStore):
    """:class:`EncryptedInteractionStore` over in-memory backends (tests, ``NS_ENV=local``)."""

    def __init__(
        self,
        wrapper: KeyWrapper,
        *,
        kek_uri: str,
        policy: PolicySource,
        meter: Meter | None = None,
    ) -> None:
        self.index_backend = InMemoryInteractionIndex()
        self.content_backend = InMemoryInteractionContent()
        super().__init__(
            self.index_backend,
            self.content_backend,
            wrapper,
            kek_uri=kek_uri,
            policy=policy,
            meter=meter,
        )
