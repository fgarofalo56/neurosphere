"""Governed copilot conversation API (PRP-19 item 2).

Public API:

* :func:`register` -- router hook (prefix ``/api/v1/copilot``) for ``RouterRegistry``. Not added
  to ``routers.py`` here; PRP-19 item 7 owns that wiring (and the OpenAPI regeneration).
* :func:`configure_copilot` -- installs the copilot collaborators on ``app.state`` (keys and
  types in :mod:`neurosphere_api.copilot.dependencies`); a missing one fails closed with 503.
* :class:`CopilotEngine` / :class:`CopilotSettings` -- the turn engine and its budgets and
  retention policy.
* :class:`InMemoryConversationStore` / :class:`CosmosConversationStore` -- redacted, owner-
  partitioned persistence; :func:`create_conversation_container` provisions the Cosmos container.
* :func:`reject_all_chart_plans` -- the fail-closed default chart validator.

Chat only ever drafts an action intent (through the PRP-17 action API) and never confirms or
executes one. Tool output and retrieved content are data; the scope is always server-derived.
"""

from neurosphere_api.copilot.cosmos_store import (
    DEFAULT_CONVERSATION_CONTAINER,
    CosmosConversationStore,
    create_conversation_container,
)
from neurosphere_api.copilot.dependencies import (
    CopilotRuntime,
    EmptyEvidenceReader,
    configure_copilot,
    get_copilot,
)
from neurosphere_api.copilot.drafter import ActionPlaneDrafter, DraftedIntent
from neurosphere_api.copilot.engine import (
    SYSTEM_PROMPT,
    ChartPlanValidator,
    CopilotEngine,
    ToolPorts,
    TurnOutcome,
    reject_all_chart_plans,
)
from neurosphere_api.copilot.models import MessageBody, MessageContext, SseEvent
from neurosphere_api.copilot.router import PREFIX, build_router, register
from neurosphere_api.copilot.settings import CopilotSettings
from neurosphere_api.copilot.store import (
    ConversationStore,
    InMemoryConversationStore,
    StoredConversation,
    StoredTurn,
)

__all__ = [
    "DEFAULT_CONVERSATION_CONTAINER",
    "PREFIX",
    "SYSTEM_PROMPT",
    "ActionPlaneDrafter",
    "ChartPlanValidator",
    "ConversationStore",
    "CopilotEngine",
    "CopilotRuntime",
    "CopilotSettings",
    "CosmosConversationStore",
    "DraftedIntent",
    "EmptyEvidenceReader",
    "InMemoryConversationStore",
    "MessageBody",
    "MessageContext",
    "SseEvent",
    "StoredConversation",
    "StoredTurn",
    "ToolPorts",
    "TurnOutcome",
    "build_router",
    "configure_copilot",
    "create_conversation_container",
    "get_copilot",
    "register",
    "reject_all_chart_plans",
]
