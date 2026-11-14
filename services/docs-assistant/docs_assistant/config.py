"""Configuration surface for the docs assistant.

Deliberately small. There is no field for a product API URL, a database or a production
credential, and unknown fields are rejected (`extra="forbid"`). The only secret-adjacent
field is the NAME of an environment variable that will hold a model key; the key itself is
never a config value.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Allowed model endpoint host suffixes per cloud (matched on the parsed hostname, with a
# leading dot, never as a substring).
ALLOWED_HOST_SUFFIXES: dict[str, tuple[str, ...]] = {
    "commercial": (".openai.azure.com", ".services.ai.azure.com", ".cognitiveservices.azure.com"),
    "government": (".openai.azure.us", ".cognitiveservices.azure.us"),
}


class Settings(BaseSettings):
    """Runtime settings, read from `DOCS_ASSISTANT_*` environment variables."""

    model_config = SettingsConfigDict(
        extra="forbid",
        env_prefix="DOCS_ASSISTANT_",
        env_file=None,
        frozen=True,
    )

    # Corpus: the built-site artifact directory (HTML). Never the repository tree.
    site_dir: Path
    docs_base_url: str = "https://fgarofalo56.github.io/neurosphere/"

    # Per-client sliding-window rate limit (defaults documented in README).
    rate_limit_requests: int = Field(default=20, ge=1, le=10_000)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=86_400)
    # 0 = ignore X-Forwarded-For and use the socket peer. N>0 = the client is the Nth entry
    # from the right of X-Forwarded-For (N trusted proxies in front of the service).
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)
    max_tracked_clients: int = Field(default=10_000, ge=1)

    # Request limits.
    max_body_bytes: int = Field(default=2_048, ge=64, le=65_536)
    max_question_chars: int = Field(default=500, ge=1, le=2_000)

    # Retrieval and abstention.
    top_k: int = Field(default=3, ge=1, le=10)
    min_score: float = Field(default=2.0, ge=0.0)
    min_coverage: float = Field(default=0.5, ge=0.0, le=1.0)

    # Optional operator-configured model endpoint. Unset means the deterministic stub.
    # The key is read from the environment variable NAMED here, at call time.
    model_endpoint: str | None = None
    model_api_key_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    cloud: Literal["commercial", "government"] = "commercial"
    model_deployment: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    model_auth: Literal["entra", "key"] = "entra"
    model_timeout_seconds: float = Field(default=20.0, gt=0.0, le=120.0)
    # GPT-5 series count reasoning tokens against this budget, so leave headroom.
    model_max_completion_tokens: int = Field(default=1024, ge=64, le=16_384)
    model_reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = "minimal"

    @field_validator("model_endpoint")
    @classmethod
    def _endpoint_is_https(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.hostname:
            msg = "model_endpoint must be an https:// URL"
            raise ValueError(msg)
        if parsed.username or parsed.password:
            msg = "model_endpoint must not embed userinfo"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def _model_settings_consistent(self) -> Settings:
        if self.model_endpoint is not None:
            host = (urlparse(self.model_endpoint).hostname or "").lower()
            if not host.endswith(ALLOWED_HOST_SUFFIXES[self.cloud]):
                msg = f"model_endpoint host is not an allowed Azure OpenAI host for {self.cloud}"
                raise ValueError(msg)
            if self.model_deployment is None:
                msg = "model_endpoint requires model_deployment"
                raise ValueError(msg)
        if self.model_auth == "key" and self.model_api_key_env is None:
            msg = "model_auth=key requires model_api_key_env"
            raise ValueError(msg)
        return self
