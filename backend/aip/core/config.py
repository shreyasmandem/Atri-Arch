"""Platform configuration.

All settings are environment driven so the same image runs locally, in CI and in
production without code changes. Nothing here is required: the platform boots
with zero configuration and degrades to local/offline behaviour, which is what
makes the "no cost to the architecture firm" promise real.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    """Runtime settings, populated from environment variables or a `.env` file."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- app ---
    app_name: str = "Architect Intelligence Platform"
    environment: str = Field(default="development")
    debug: bool = Field(default=True)
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)

    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    cors_origins: str = "*"

    # Secret used to sign session tokens. Auto-generated in dev; MUST be set in
    # production or startup fails loudly (see `validate_production`).
    secret_key: str = Field(default="dev-insecure-change-me")

    # ------------------------------------------------------------ storage ---
    data_dir: Path = Field(default=BACKEND_ROOT / "data")
    artifact_dir: Path = Field(default=BACKEND_ROOT / "var" / "artifacts")
    cache_dir: Path = Field(default=BACKEND_ROOT / "var" / "cache")
    database_url: str = Field(default="")

    # -------------------------------------------------- model provider keys --
    # Every one of these is a *free tier*. Leave blank to disable that provider.
    groq_api_key: str = ""
    google_api_key: str = ""
    openrouter_api_key: str = ""
    cerebras_api_key: str = ""
    mistral_api_key: str = ""
    together_api_key: str = ""
    huggingface_api_key: str = ""
    github_token: str = ""
    nvidia_api_key: str = ""

    # Local inference. Requires nothing but a running Ollama daemon.
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_enabled: bool = True

    # ---------------------------------------------------------- behaviour ---
    # Hard ceiling on spend. The router refuses any provider that would bill.
    enforce_zero_cost: bool = True
    llm_timeout_seconds: float = 90.0
    llm_max_retries: int = 3
    llm_cache_enabled: bool = True

    # Multi-agent consensus knobs.
    consensus_generators: int = 3
    consensus_critics: int = 4
    consensus_debate_rounds: int = 1
    consensus_min_score: float = 0.62

    # Retrieval.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    retrieval_top_k: int = 8
    retrieval_hybrid_alpha: float = 0.55  # weight of dense vs lexical

    # Vastu reconciliation. 1.0 = purely traditional, 0.0 = purely modern.
    vastu_default_tradition_weight: float = 0.5

    # Cost engine.
    cost_region_default: str = "IN-TN"
    cost_currency_default: str = "INR"
    cost_monte_carlo_runs: int = 4000

    @field_validator("data_dir", "artifact_dir", "cache_dir", mode="after")
    @classmethod
    def _ensure_dir(cls, value: Path) -> Path:
        value.mkdir(parents=True, exist_ok=True)
        return value

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        db_path = (BACKEND_ROOT / "var" / "aip.db").as_posix()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{db_path}"

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw in {"", "*"}:
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    def validate_production(self) -> list[str]:
        """Return a list of blocking misconfigurations for production deploys."""
        problems: list[str] = []
        if not self.is_production:
            return problems
        if self.secret_key == "dev-insecure-change-me":
            problems.append("SECRET_KEY must be set to a strong random value in production")
        if self.debug:
            problems.append("DEBUG must be false in production")
        if self.cors_origin_list == ["*"]:
            problems.append("CORS_ORIGINS must be an explicit allow-list in production")
        if not self.configured_providers():
            problems.append(
                "no model provider configured - set at least one free API key "
                "(GROQ_API_KEY, GOOGLE_API_KEY, ...) or run Ollama locally"
            )
        return problems

    def configured_providers(self) -> list[str]:
        """Names of providers that currently have credentials available."""
        mapping = {
            "groq": self.groq_api_key,
            "google": self.google_api_key,
            "openrouter": self.openrouter_api_key,
            "cerebras": self.cerebras_api_key,
            "mistral": self.mistral_api_key,
            "together": self.together_api_key,
            "huggingface": self.huggingface_api_key,
            "github": self.github_token,
            "nvidia": self.nvidia_api_key,
        }
        active = [name for name, key in mapping.items() if key.strip()]
        if self.ollama_enabled:
            active.append("ollama")
        return active


@lru_cache(maxsize=1)
def _cached_settings() -> Settings:
    return Settings()


#: Explicit override, used by tests and by anything that must not read the
#: ambient environment. See `override_settings`.
_override: Settings | None = None


def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return _override if _override is not None else _cached_settings()


def override_settings(settings: Settings) -> None:
    """Force `get_settings()` to return a specific instance.

    This exists because environment-based configuration is not hermetic: the
    test suite's whole premise is that it runs with *no* model provider
    configured, which proves the analytical engines need no API. Relying on
    unset environment variables to achieve that is a trap - the moment a
    developer creates a `.env`, the suite silently starts calling live
    providers, becoming slow, flaky, and quota-consuming while still passing.
    An explicit override makes the isolation real rather than incidental.
    """
    global _override
    _override = settings


def clear_settings_override() -> None:
    global _override
    _override = None


def hermetic_settings(**overrides: Any) -> Settings:
    """A Settings instance that ignores `.env` and the ambient environment."""
    base: dict[str, Any] = {
        "environment": "test",
        "debug": True,
        "groq_api_key": "", "google_api_key": "", "openrouter_api_key": "",
        "cerebras_api_key": "", "mistral_api_key": "", "together_api_key": "",
        "huggingface_api_key": "", "github_token": "", "nvidia_api_key": "",
        "ollama_enabled": False,
        "database_url": "sqlite+aiosqlite:///:memory:",
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def reload_settings() -> Settings:
    """Clear the cache and re-read the environment."""
    clear_settings_override()
    _cached_settings.cache_clear()
    return get_settings()


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
