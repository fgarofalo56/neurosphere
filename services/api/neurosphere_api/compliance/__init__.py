"""Compliance read API (PRP-56): framework list, mapped controls and evidence bundles.

Metadata only; maps and collects, never judges. See :mod:`neurosphere_api.compliance.router`.
"""

from neurosphere_api.compliance.dependencies import get_clock, get_library, get_sources
from neurosphere_api.compliance.router import PREFIX, build_router, register

__all__ = ["PREFIX", "build_router", "get_clock", "get_library", "get_sources", "register"]
