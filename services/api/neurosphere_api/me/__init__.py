"""Caller-identity API (PRP-28 item 1): ``GET /api/v1/me/domains``."""

from neurosphere_api.me.router import PREFIX, build_router, derived_label, register

__all__ = ["PREFIX", "build_router", "derived_label", "register"]
