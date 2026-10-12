"""Startup settings: NS_CLOUD and NS_ENV read once into a frozen object. Unknown values fail."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from neurosphere_core.cloud.profile import CloudName, CloudProfile, profile_for


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NS_", frozen=True, extra="forbid")

    env: Literal["local", "dev", "test", "staging", "prod"] = "local"
    cloud: CloudName | None = None

    @model_validator(mode="after")
    def _cloud_required_outside_local(self) -> Self:
        if self.cloud is None and self.env != "local":
            raise ValueError(
                "NS_CLOUD (commercial|government) is required when NS_ENV is not local"
            )
        return self

    @property
    def cloud_profile(self) -> CloudProfile:
        # Only NS_ENV=local may fall back to Commercial; every other env is validated above.
        return profile_for(self.cloud or CloudName.COMMERCIAL)


def load_settings() -> Settings:
    """Read the environment once. Callers keep the returned frozen object; no module cache."""
    return Settings()
