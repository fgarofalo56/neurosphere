"""Notification channel and subscription administration API (PRP-107 item 7).

Routes at ``/api/v1/admin/notifications``; see :mod:`neurosphere_api.notifications.router` for the
route table and :mod:`neurosphere_api.notifications.service` for the rules.
"""

from __future__ import annotations

from neurosphere_api.notifications.router import PREFIX, build_router, register

__all__ = ["PREFIX", "build_router", "register"]
