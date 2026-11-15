"""Operator admin API package root (PRP-39).

Sub-packages own one admin area each and are mounted under ``/api/v1/admin/<area>``:

* ``identity`` (PRP-39): principals, role assignments, memberships, resource grants, revocation.

Later admin PRPs (41, 42, 44, 45) add their own sub-package and their own ``_register_*`` hook
line in ``neurosphere_api/routers.py``; :func:`register` here only mounts ``identity``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from neurosphere_api.routers import RouterRegistry

__all__ = ["ADMIN_PREFIX", "register"]

#: Every admin area lives below this prefix.
ADMIN_PREFIX: Final = "/api/v1/admin"


def register(registry: RouterRegistry) -> None:
    """Router-registry hook (see ``neurosphere_api/routers.py``): mounts the identity admin."""
    from neurosphere_api.admin.identity import register as register_identity

    register_identity(registry)
