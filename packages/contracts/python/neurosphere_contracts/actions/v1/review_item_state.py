# GENERATED - do not edit.
# Source of truth: packages/contracts/schemas/ (JSON Schema 2020-12).
# Regenerate: python packages/contracts/scripts/generate.py
# Drift check: python packages/contracts/scripts/generate.py --check (ADR-0004).
# pyright: reportAssignmentType=false, reportInvalidTypeForm=false

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, RootModel


class ReviewItemState(
    RootModel[
        Literal[
            "pending",
            "assigned",
            "approved",
            "rejected",
            "expired",
            "escalated",
            "executed",
            "failed",
        ]
    ]
):
    root: Annotated[
        Literal[
            "pending",
            "assigned",
            "approved",
            "rejected",
            "expired",
            "escalated",
            "executed",
            "failed",
        ],
        Field(title="ReviewItemState"),
    ]
    """
    Persistent state of a human-in-the-loop review item (PRD NS-04): low-confidence relationships, disputed evaluations, recommendation reviews, policy exceptions and maker-checker approvals of executable changes. Deliberately separate from ActionState (Clarification 12); a review item for a maker-checker approval references an ActionIntent but does not share its enum.
    """
