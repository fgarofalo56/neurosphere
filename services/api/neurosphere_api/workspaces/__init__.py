"""Workspace API (PRP-28 item 1): ``GET /api/v1/workspaces/{role}``."""

from neurosphere_api.workspaces.router import PREFIX, ROLE_MAP, build_router, register

__all__ = ["PREFIX", "ROLE_MAP", "build_router", "register"]
