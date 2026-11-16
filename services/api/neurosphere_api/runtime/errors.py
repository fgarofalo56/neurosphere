"""Startup refusals of the composition root (PRP-51).

A startup refusal is a deliberate hard stop: the process must not boot with a configuration
that is unsafe (a credential in ``NS_COPILOT_*``, a wildcard CORS origin, test overrides outside
``NS_ENV=local``). Every refusal derives from :class:`StartupRefusedError`, so callers handle
one type, and the builder loop re-raises it instead of degrading the component to
``build_error``. Messages name variables or fields, never values.
"""

from __future__ import annotations

from neurosphere_core.errors import InvalidSchemaError

__all__ = ["CorsConfigError", "StartupRefusedError"]


class StartupRefusedError(Exception):
    """Base of every startup refusal; propagates out of ``compose_app``."""


class CorsConfigError(StartupRefusedError, InvalidSchemaError):
    """``NS_CORS_ALLOWED_ORIGINS`` is invalid (still an ``invalid_schema``/``config`` problem)."""
