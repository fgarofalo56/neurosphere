"""Event sources that stamp a resolved canonical agent id on what they return (PRP-137 item 2).

The wrappers sit between the archive readers and their consumers (catalog projection, aggregates,
evaluation sampler). They never mutate the inner source's objects: an event is copied with
``model_copy`` and a record is shallow-copied with a copied ``contract`` dict.

A resolver lookup failure is re-raised as ``DependencyTransientError`` (chained) so the outbox
entry retries. There is no fallback to the derived id while the catalog is unavailable, because
that would file telemetry under the wrong agent.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from neurosphere_contracts.telemetry.v1.telemetry_event import CanonicalId, Identifier
from neurosphere_core.agent_identity import AgentIdentityResolver, AgentResolution
from neurosphere_core.errors import DependencyTransientError

from neurosphere_workers.evaluation.source import RecordSource
from neurosphere_workers.projections.catalog.source import LoadedEvent, TraceEventSource

__all__ = ["ResolvingRecordSource", "ResolvingTraceEventSource"]

_Key = tuple[str, str, str, str | None, str | None, str | None]


async def _resolve(
    resolver: AgentIdentityResolver, memo: dict[_Key, AgentResolution], key: _Key
) -> AgentResolution:
    found = memo.get(key)
    if found is not None:
        return found
    cloud, customer, source, external, canonical, domain = key
    try:
        found = await resolver.resolve(cloud, customer, source, external, canonical, domain)
    except Exception as exc:
        raise DependencyTransientError(
            "agent identity lookup unavailable", reason="agent_identity_lookup"
        ) from exc
    memo[key] = found
    return found


class ResolvingTraceEventSource:
    """``TraceEventSource`` that returns events with ``canonical_agent_id`` resolved."""

    def __init__(self, inner: TraceEventSource, resolver: AgentIdentityResolver) -> None:
        self._inner = inner
        self._resolver = resolver

    async def _stamp(self, loaded: LoadedEvent, memo: dict[_Key, AgentResolution]) -> LoadedEvent:
        event = loaded.event
        key: _Key = (
            event.cloud,
            event.customer_id.root,
            event.source_id.root,
            event.external_agent_id.root if event.external_agent_id else None,
            event.canonical_agent_id.root if event.canonical_agent_id else None,
            event.domain_id.root if event.domain_id else None,
        )
        resolution = await _resolve(self._resolver, memo, key)
        canonical = (
            CanonicalId(resolution.canonical_id) if resolution.canonical_id is not None else None
        )
        update: dict[str, Any] = {"canonical_agent_id": canonical}
        if event.domain_id is None and resolution.domain_id is not None:
            update["domain_id"] = Identifier(resolution.domain_id)
        return LoadedEvent(loaded.doc_id, event.model_copy(update=update), resolution.status)

    async def get_event(self, customer_id: str, doc_id: str) -> LoadedEvent | None:
        loaded = await self._inner.get_event(customer_id, doc_id)
        return None if loaded is None else await self._stamp(loaded, {})

    async def find_span(self, customer_id: str, trace_id: str, span_id: str) -> LoadedEvent | None:
        loaded = await self._inner.find_span(customer_id, trace_id, span_id)
        return None if loaded is None else await self._stamp(loaded, {})

    async def find_child_spans(
        self, customer_id: str, trace_id: str, parent_span_id: str
    ) -> Sequence[LoadedEvent]:
        memo: dict[_Key, AgentResolution] = {}
        return [
            await self._stamp(loaded, memo)
            for loaded in await self._inner.find_child_spans(customer_id, trace_id, parent_span_id)
        ]


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


class ResolvingRecordSource:
    """``RecordSource`` that yields records whose telemetry contract carries the resolved id."""

    def __init__(self, inner: RecordSource, resolver: AgentIdentityResolver) -> None:
        self._inner = inner
        self._resolver = resolver

    async def records(self) -> AsyncIterator[Mapping[str, Any]]:
        memo: dict[_Key, AgentResolution] = {}
        async for record in self._inner.records():
            contract = record.get("contract")
            if not isinstance(contract, Mapping):
                yield record
                continue
            cloud = _text(contract.get("cloud"))
            customer = _text(contract.get("customer_id"))
            source = _text(contract.get("source_id"))
            if cloud is None or customer is None or source is None:
                yield record  # not a telemetry contract (cost record, odd shape)
                continue
            key: _Key = (
                cloud,
                customer,
                source,
                _text(contract.get("external_agent_id")),
                _text(contract.get("canonical_agent_id")),
                _text(contract.get("domain_id")),
            )
            resolution = await _resolve(self._resolver, memo, key)
            stamped = dict(contract)
            stamped["canonical_agent_id"] = resolution.canonical_id
            if key[5] is None and resolution.domain_id is not None:
                stamped["domain_id"] = resolution.domain_id
            yield {**record, "contract": stamped}
