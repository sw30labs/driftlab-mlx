"""Configuration via environment / .env (prefix DRIFTLAB_).

The LLM path is optional. When ``llm_provider`` is ``none`` every compliance
feature works without any inference server reachable — this invariant is
enforced by the test suite.

When an LLM *is* enabled it speaks the same OMLX contract as the sibling
projects on this workstation (book-buddy-2026, contingency-atlas): an
OpenAI-compatible local MLX server on ``http://127.0.0.1:8000/v1``, an explicit
model id, non-streaming only. ``OMLX_API_KEY`` is read as a fallback so one
exported key serves every project.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Backend aliases, matching book-buddy-2026's normalize_backend().
_PROVIDER_ALIASES = {"mlx": "omlx", "vllm": "dgx"}
_PROVIDERS = ("none", "omlx", "dgx")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DRIFTLAB_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    data_dir: Path = Path("./.driftlab")
    registry_path: Path | None = None

    # -- LLM (advisory only; never decides a severity or a verdict) --------
    llm_provider: str = "none"  # "none" | "omlx" | "dgx" (aliases: mlx, vllm)
    omlx_base_url: str = "http://127.0.0.1:8000/v1"
    omlx_api_key: str = "test"
    omlx_model: str = "DeepSeek-V4-Flash-0731-MLX"
    # Large MLX models narrate a full ledger in minutes, not seconds; this
    # matches book-buddy-2026's OMLX timeout.
    omlx_timeout: float = 180.0
    omlx_max_tokens: int = 4096
    # DGX / vLLM shares the OpenAI-compatible shape; base_url must be explicit.
    dgx_base_url: str = ""
    # Local-first is a design principle: a non-loopback endpoint is refused
    # unless the operator consciously accepts the egress.
    allow_remote_llm: bool = False

    email__enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_to: str = ""
    email_from: str = ""

    @model_validator(mode="after")
    def _normalize_llm(self) -> "Settings":
        provider = (self.llm_provider or "none").strip().lower()
        provider = _PROVIDER_ALIASES.get(provider, provider)
        if provider not in _PROVIDERS:
            known = ", ".join(_PROVIDERS)
            raise ValueError(
                f"unknown llm_provider {self.llm_provider!r}; known: {known} "
                f"(aliases: {', '.join(_PROVIDER_ALIASES)})"
            )
        self.llm_provider = provider
        # A key exported once for the workstation serves every project — but
        # only as a fallback. `model_fields_set` tells us whether the DriftLab
        # key was actually supplied (by env, .env, or kwargs); checking
        # os.environ alone would let OMLX_API_KEY clobber a key set in .env.
        if "omlx_api_key" not in self.model_fields_set and os.environ.get("OMLX_API_KEY"):
            self.omlx_api_key = os.environ["OMLX_API_KEY"]
        return self

    @property
    def llm_base_url(self) -> str:
        """Endpoint for the active provider (empty when the LLM is off)."""
        if self.llm_provider == "omlx":
            return self.omlx_base_url
        if self.llm_provider == "dgx":
            return self.dgx_base_url or self.omlx_base_url
        return ""

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "driftlab.db"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
