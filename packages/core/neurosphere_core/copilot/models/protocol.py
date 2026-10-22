"""The ``ModelAdapter`` protocol the copilot orchestrator calls."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from neurosphere_core.copilot.models.types import ModelEvent, ModelRequest

AdapterKind = Literal["fixture", "approved_endpoint", "foundry_agent"]
ADAPTER_KINDS: tuple[AdapterKind, ...] = ("fixture", "approved_endpoint", "foundry_agent")


class AdapterDescriptor(BaseModel):
    """Who is answering. ``synthetic`` adapters replay recordings and never reach a model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: AdapterKind
    name: str
    synthetic: bool = False


@runtime_checkable
class ModelAdapter(Protocol):
    """Provider-neutral streaming model access.

    ``stream`` yields :data:`~neurosphere_core.copilot.models.types.ModelEvent` values:
    zero or more ``TextDelta`` (as they arrive, for first-token measurement), then any
    ``ToolCallRequested`` / ``ActionSuggestion`` in model order, then exactly one ``Completed``.
    Prompts are redacted before they leave the boundary. Failures raise the PRP-01 error
    taxonomy (``dependency_transient``, ``rate_limited``, ``unauthorized``, ...), never a
    provider exception, and never include a prompt or response body.
    """

    @property
    def descriptor(self) -> AdapterDescriptor: ...

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...
