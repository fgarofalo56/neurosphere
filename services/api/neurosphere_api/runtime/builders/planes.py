"""Action-plane, HITL, reports and MCP-admin builder (PRP-29 item 8 fills this body).

PLACEHOLDER (item 1): every component below reports ``not_built``. Item 8 calls
``configure_action_plane`` (which also serves the HITL routes), ``configure_reports`` and
``configure_mcp_admin``, consuming ``AUDIT_REPOSITORY`` and ``HITL_SERVICE`` from the data
builder and publishing ``ACTION_SERVICE`` for the copilot and MCP builders.
"""

from __future__ import annotations

from typing import Final

from neurosphere_api.runtime.builders import BuildContext, BuilderSpec

__all__ = ["BUILDER", "COMPONENTS", "build"]

COMPONENTS: Final = ("hitl", "action_plane", "reports", "mcp_admin")


def build(ctx: BuildContext) -> None:
    for name in COMPONENTS:
        ctx.not_built(name)


BUILDER: Final = BuilderSpec("planes", COMPONENTS, build)
