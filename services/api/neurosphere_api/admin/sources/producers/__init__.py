"""Ingest producer admin API (PRP-41), mounted at ``/api/v1/admin/sources/producers``.

Register, rotate, disable and enable ingest producers; the secret is returned once and only its
digest is stored. See ``router`` for the route table and ``service`` for the audit wrapping.
"""

from __future__ import annotations

from neurosphere_api.admin.sources.producers.router import PREFIX, build_router, register
from neurosphere_api.admin.sources.producers.service import (
    STATE_ATTRIBUTE,
    ProducerAdminPlane,
    configure_producer_admin,
)

__all__ = [
    "PREFIX",
    "STATE_ATTRIBUTE",
    "ProducerAdminPlane",
    "build_router",
    "configure_producer_admin",
    "register",
]
