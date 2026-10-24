"""Sandbox API (PRP-24 item 2): synthetic-only data from allowlisted sandbox containers."""

from neurosphere_api.sandbox.router import PREFIX, build_router, register

__all__ = ["PREFIX", "build_router", "register"]
