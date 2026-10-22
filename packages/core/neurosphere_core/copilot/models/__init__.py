"""Model adapters for the governed copilot (PRP-19 item 3)."""

from neurosphere_core.copilot.models.approved_endpoint import ApprovedEndpointAdapter
from neurosphere_core.copilot.models.endpoints import AdapterConfig, endpoint_problem
from neurosphere_core.copilot.models.foundry_agent import FoundryAgentAdapter
from neurosphere_core.copilot.models.gating import (
    AdapterAvailability,
    create_adapter,
    resolve_adapters,
)
from neurosphere_core.copilot.models.normalize import SUGGEST_ACTION_TOOL, collapse_text
from neurosphere_core.copilot.models.protocol import AdapterDescriptor, AdapterKind, ModelAdapter
from neurosphere_core.copilot.models.recorded import FixtureAdapter
from neurosphere_core.copilot.models.redaction import redact_request, redact_text
from neurosphere_core.copilot.models.types import (
    ActionSuggestion,
    Completed,
    ConversationTurn,
    ModelEvent,
    ModelRequest,
    TextDelta,
    ToolCallRequest,
    ToolCallRequested,
    ToolSpec,
    Usage,
)

__all__ = [
    "SUGGEST_ACTION_TOOL",
    "ActionSuggestion",
    "AdapterAvailability",
    "AdapterConfig",
    "AdapterDescriptor",
    "AdapterKind",
    "ApprovedEndpointAdapter",
    "Completed",
    "ConversationTurn",
    "FixtureAdapter",
    "FoundryAgentAdapter",
    "ModelAdapter",
    "ModelEvent",
    "ModelRequest",
    "TextDelta",
    "ToolCallRequest",
    "ToolCallRequested",
    "ToolSpec",
    "Usage",
    "collapse_text",
    "create_adapter",
    "endpoint_problem",
    "redact_request",
    "redact_text",
    "resolve_adapters",
]
