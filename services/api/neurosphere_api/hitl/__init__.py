"""Shared review queue API (PRP-17 item 4): list, read, assign, decide.

Public API:

* :func:`register` -- router hook (prefix ``/api/v1/review``) for ``RouterRegistry``. Not added
  to ``routers.py`` here; PRP-17 item 7 owns that wiring.
* :class:`RecheckerReviewerAuthorizer` -- the ``ReviewerAuthorizer`` to build ``HitlService``
  with (same ``PermissionRechecker`` as the action service).
* :class:`ReviewerDirectory` -- optional ``app.state.reviewer_directory`` port for assigning
  another reviewer.

Collaborators come from the same ``app.state`` keys as the action API
(:func:`neurosphere_api.actions.configure_action_plane`). One queue serves maker-checker
approvals and insight reviews (catalog relationships, disputed evaluations, recommendations,
policy exceptions); a maker-checker decision delegates to the action approval path.
"""

from neurosphere_api.hitl.models import (
    AssignmentBody,
    ReviewDecisionBody,
    ReviewItemList,
    ReviewItemView,
)
from neurosphere_api.hitl.ports import RecheckerReviewerAuthorizer, ReviewerDirectory
from neurosphere_api.hitl.router import PREFIX, build_router, register

__all__ = [
    "PREFIX",
    "AssignmentBody",
    "RecheckerReviewerAuthorizer",
    "ReviewDecisionBody",
    "ReviewItemList",
    "ReviewItemView",
    "ReviewerDirectory",
    "build_router",
    "register",
]
