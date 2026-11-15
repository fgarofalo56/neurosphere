"""``NS_LIFECYCLE_*`` settings shared by the API (status route) and the lifecycle worker.

=============================  =============================================================
``NS_LIFECYCLE_MODE``          ``dry_run`` (default) or ``execute``. Only ``execute`` calls a
                               mutating target method; dry-run decides and audits only.
``NS_LIFECYCLE_POLICY_FILE``   path to a JSON retention policy (``load_policy_file``); unset or
                               invalid means no policy and nothing expires.
``NS_LIFECYCLE_MAX_ATTEMPTS``  bound on retries of a FAILED queued request (default 5).
=============================  =============================================================

Settings are read at process start; changing them needs a restart. A value that is not exactly
``execute`` is rejected rather than coerced, so a typo can never switch mutation on, and the
default is always the safe one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["LifecycleSettings"]


class LifecycleSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NS_LIFECYCLE_", frozen=True, extra="ignore")

    mode: Literal["dry_run", "execute"] = "dry_run"
    policy_file: Path | None = None
    max_attempts: int = Field(default=5, ge=1, le=100)
