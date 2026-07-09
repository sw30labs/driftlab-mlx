"""Settings — pydantic-settings with env / .env overrides (glass-graph pattern).

Everything is local-first: SQLite under ``data_dir``, artifacts on disk, LLM
optional and pointed at a local OMLX server. Tests inject ``Settings`` with
paths under pytest's tmp_path.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DIR = Path(__file__).resolve().parent
#: bundled demo estate — ships inside the wheel so `driftlab demo` works anywhere
BUNDLED_SEED_REGISTRY = PACKAGE_DIR / "seed" / "agents.yaml"


class EmailSettings(BaseModel):
    """SMTP digest delivery. Config-first, env-fallback (regitel notifier pattern).

    Disabled by default: a monitor cycle must never depend on a mail server.
    """

    enabled: bool = False
    send_empty: bool = False
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    use_tls: bool = True
    to: str | None = None
    sender: str | None = None
    subject_prefix: str = "[driftlab]"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DRIFTLAB_", env_file=".env", extra="ignore", env_nested_delimiter="__")

    # --- storage -----------------------------------------------------------
    data_dir: Path = Field(default_factory=lambda: Path.cwd() / ".driftlab")
    registry_path: Path = Field(default_factory=lambda: BUNDLED_SEED_REGISTRY)

    # --- LLM (advisory only; "none" keeps the whole platform deterministic) -
    llm_provider: str = "none"  # none | omlx | openai
    llm_model: str = ""  # empty for omlx -> auto-discovered from /models
    omlx_base_url: str = "http://127.0.0.1:8000/v1"
    omlx_api_key: str = "test"
    omlx_request_timeout: float = 600.0  # OMLX loads models on demand
    max_llm_retries: int = 2
    llm_token_budget: int | None = 200_000

    # --- experiment loop ----------------------------------------------------
    confirm_threshold: float = 0.7
    refute_threshold: float = 0.05
    max_experiment_iterations: int = 3
    max_experiments_per_cycle: int = 5
    min_probe_samples: int = 3

    # --- monitor (staleness-weighted, regitel pattern) -----------------------
    intervals_days: dict[int, int] = Field(
        default_factory=lambda: {1: 1, 2: 1, 3: 3, 4: 7, 5: 7, 6: 14, 7: 30}
    )
    default_interval_days: int = 7
    max_agents_per_run: int = 6
    email: EmailSettings = Field(default_factory=EmailSettings)

    # --- dashboard -----------------------------------------------------------
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8321

    # --- derived paths -------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.data_dir / "driftlab.sqlite3"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def artifacts_dir(self) -> Path:
        return self.data_dir / "artifacts"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
