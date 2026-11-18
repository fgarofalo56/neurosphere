"""Caller-identity API: ``GET /api/v1/me/domains`` and ``GET /api/v1/me/access`` (PRP-138)."""

from neurosphere_api.me.router import PREFIX, build_router, derived_label, register

__all__ = ["PREFIX", "build_router", "derived_label", "register"]
