"""MCP server builder (PRP-29 item 8 fills this body).

PLACEHOLDER (item 1): ``mcp_server`` reports ``not_built`` (optional). Item 8 mounts
``create_mcp_server`` only when ``NS_MCP_RESOURCE_SERVER_URL`` is set (``disabled`` otherwise),
after ``configure_authz`` (the authz builder runs first), per ``mcp/server/__init__.py``.
"""

from __future__ import annotations

from typing import Final

from neurosphere_api.runtime.builders import BuildContext, BuilderSpec

__all__ = ["BUILDER", "COMPONENTS", "build"]

COMPONENTS: Final = ("mcp_server",)


def build(ctx: BuildContext) -> None:
    for name in COMPONENTS:
        ctx.not_built(name)


BUILDER: Final = BuilderSpec("mcp", COMPONENTS, build)
