"""FastAPI providers for the replay API (PRP-18 item 5).

* :func:`get_trace_reader` -- ``app.state.trace_reader`` (a ``TraceReader``); fails closed with 503
  (``DependencyTransientError``) when unset. Tests use ``app.dependency_overrides``.
* :func:`get_payload_policy` -- derived from the deployment (PRP-104 clarification 9): bodies are
  allowed only while ``app.state.interaction_explorer`` is installed (the audited content reader
  exists). ``app.state.replay_payload_policy`` (always bodies-off, set by the data builder) no
  longer decides it. Allowing bodies is necessary, not sufficient: the trace route still requires
  ``interaction.read`` in the domain and a purpose before any content is read.

No ``from __future__ import annotations``: FastAPI inspects these signatures.
"""

from dataclasses import dataclass

from fastapi import Request
from neurosphere_core.errors import DependencyTransientError

from neurosphere_api.interactions.content import InteractionContentReader
from neurosphere_api.replay.reader import TraceReader

__all__ = ["PayloadPolicy", "get_payload_policy", "get_trace_reader"]


@dataclass(frozen=True, slots=True)
class PayloadPolicy:
    """Deployment policy for stored payload bodies. Default: off."""

    allow_bodies: bool = False


def get_trace_reader(request: Request) -> TraceReader:
    reader = getattr(request.app.state, "trace_reader", None)
    if not isinstance(reader, TraceReader):
        raise DependencyTransientError(
            "trace reader is not configured", reason="trace_reader_unconfigured"
        )
    return reader


def get_payload_policy(request: Request) -> PayloadPolicy:
    explorer_on = InteractionContentReader.from_app_state(request.app.state) is not None
    return PayloadPolicy(allow_bodies=explorer_on)
