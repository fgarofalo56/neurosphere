"""Shared action API (PRP-17 item 4): draft, validate, confirm, approve, status, kill switch.

Public API:

* :func:`register` -- router hook (prefix ``/api/v1/actions``) for ``RouterRegistry``. Not
  added to ``routers.py`` here; PRP-17 item 7 owns that wiring.
* :func:`configure_action_plane` -- installs every collaborator on ``app.state`` (keys and
  types in :mod:`neurosphere_api.actions.dependencies`); missing ones fail closed with 503.
* :func:`decide_maker_checker` -- the one maker-checker approval path (also used by the review
  queue API in :mod:`neurosphere_api.hitl`).
* :class:`ActionApiSettings` -- per-kind ``requires_approval`` and confirmation lifetimes.

Every surface builds the same ``ActionIntent`` through these routes; nothing here calls a
connector's ``apply`` or ``rollback`` (only the executor worker does) and nothing edits catalog
metadata to represent a change.
"""

from neurosphere_api.actions.approval import decide_maker_checker
from neurosphere_api.actions.dependencies import (
    ActionPlane,
    configure_action_plane,
    get_action_plane,
)
from neurosphere_api.actions.models import (
    ActionList,
    ActionView,
    ConfirmBody,
    DecisionBody,
    DraftIntentBody,
    EmergencyDisableBody,
    EmergencyDisableView,
    ExecutionView,
)
from neurosphere_api.actions.router import PREFIX, build_router, register
from neurosphere_api.actions.settings import ActionApiSettings, ActionKindPolicy

__all__ = [
    "PREFIX",
    "ActionApiSettings",
    "ActionKindPolicy",
    "ActionList",
    "ActionPlane",
    "ActionView",
    "ConfirmBody",
    "DecisionBody",
    "DraftIntentBody",
    "EmergencyDisableBody",
    "EmergencyDisableView",
    "ExecutionView",
    "build_router",
    "configure_action_plane",
    "decide_maker_checker",
    "get_action_plane",
    "register",
]
