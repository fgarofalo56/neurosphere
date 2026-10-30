"""Configuration surface for the docs assistant.

Deliberately small. There is no field for a product API URL, a database or a production
credential, and unknown fields are rejected (`extra="forbid"`). The only secret-adjacent
field is the NAME of an environment variable that will hold a model key; the key itself is
never a config value.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime settings, read from `DOCS_ASSISTANT_*` environment variables."""

    model_config = ConfigDict(
        extra="forbid",
        env_prefix="DOCS_ASSISTANT_",
        env_file=None,
        frozen=True,
    )

    # Corpus: the built-site artifact directory (HTML). Never the repository tree.
    site_dir: Path
    docs_base_url: str = "https://docs.example.invalid/"

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
