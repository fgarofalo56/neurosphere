"""Settings for the ``policy_eval`` role (``NS_POLICY_EVAL_*``, PRP-105 item 5).

Three settings, no secrets:

* ``NS_POLICY_EVAL_INTERVAL_SECONDS`` (300): seconds between interval runs. A policy published
  since the last run makes the role run sooner (trigger ``due``).
* ``NS_POLICY_EVAL_SUBJECT_BUDGET`` (5000): subjects one rule may examine per run.
* ``NS_POLICY_EVAL_TIME_BUDGET_SECONDS`` (120): seconds one rule may take per run.

A rule that hits either budget is ``truncated`` and resolves nothing (criterion 3).

An unknown ``NS_POLICY_EVAL_*`` name (a typo such as ``NS_POLICY_EVAL_INTERVAL``) or an invalid
value refuses to start the role with a machine reason (:class:`RoleConfigError`), so a mistyped
budget never silently runs on the default. Logs name the offending setting, never a value.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Final

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from neurosphere_workers.runtime.roles import RoleConfigError

__all__ = [
    "ENV_PREFIX",
    "KNOWN_SETTINGS",
    "SETTING_INVALID",
    "SETTING_UNKNOWN",
    "PolicyEvalSettings",
    "load_policy_eval_settings",
]

ENV_PREFIX: Final = "NS_POLICY_EVAL_"
SETTING_UNKNOWN: Final = "policy_eval_setting_unknown"
SETTING_INVALID: Final = "policy_eval_setting_invalid"

_log = logging.getLogger(__name__)


class PolicyEvalSettings(BaseSettings):
    """The role's interval and per-rule budgets (see the module docstring)."""

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, frozen=True, extra="ignore")

    interval_seconds: float = Field(default=300.0, ge=30.0, le=86400.0)
    subject_budget: int = Field(default=5000, ge=1, le=100_000)
    time_budget_seconds: float = Field(default=120.0, ge=1.0, le=3600.0)


KNOWN_SETTINGS: Final[frozenset[str]] = frozenset(
    ENV_PREFIX + name.upper() for name in PolicyEvalSettings.model_fields
)
"""Every ``NS_POLICY_EVAL_*`` environment variable name the role reads."""


def load_policy_eval_settings(environ: Mapping[str, str] | None = None) -> PolicyEvalSettings:
    """The settings from the environment; :class:`RoleConfigError` on an unknown or bad one."""
    env = os.environ if environ is None else environ
    unknown = sorted(
        name.upper()
        for name in env
        if name.upper().startswith(ENV_PREFIX) and name.upper() not in KNOWN_SETTINGS
    )
    if unknown:
        _log.error(
            "unknown policy_eval setting; the role refuses to start",
            extra={"event": "worker.policy_eval_config_refused", "settings": unknown},
        )
        raise RoleConfigError(SETTING_UNKNOWN)
    try:
        if environ is None:
            return PolicyEvalSettings()
        values = {
            name.upper().removeprefix(ENV_PREFIX).lower(): value
            for name, value in environ.items()
            if name.upper().startswith(ENV_PREFIX)
        }
        return PolicyEvalSettings.model_validate(values)
    except ValidationError as exc:
        fields = sorted({ENV_PREFIX + str(e["loc"][0]).upper() for e in exc.errors() if e["loc"]})
        _log.error(
            "invalid policy_eval setting; the role refuses to start",
            extra={"event": "worker.policy_eval_config_refused", "settings": fields},
        )
        raise RoleConfigError(SETTING_INVALID) from None
