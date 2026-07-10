"""Configuration via environment / .env (prefix DRIFTLAB_).

The LLM path is optional. When ``llm_provider`` is ``none`` every compliance
feature works without any inference server reachable — this invariant is
enforced by the test suite.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DRIFTLAB_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    data_dir: Path = Path("./.driftlab")
    registry_path: Path | None = None

    llm_provider: str = "none"  # "none" | "omlx"
    omlx_base_url: str = "http://127.0.0.1:8000/v1"
    omlx_api_key: str = "test"

    email__enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_to: str = ""
    email_from: str = ""

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