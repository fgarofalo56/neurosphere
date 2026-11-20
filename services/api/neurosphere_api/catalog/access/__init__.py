"""Catalog access questions API (PRP-73 item 3): who reads or writes a data asset, who is affected
when a node fails. ``catalog/access/could/**`` is reserved for a later PRP and is not created here.
"""

from neurosphere_api.catalog.access.router import ALIAS_PREFIX, PREFIX, build_router, register

__all__ = ["ALIAS_PREFIX", "PREFIX", "build_router", "register"]
