"""Application configuration.

Every setting is environment-driven (SECURITY.md §5): no secret has a usable default, and the
application refuses to start with an insecure one outside development.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VAANIOS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = "development"
    debug: bool = False

    # --- Stores -------------------------------------------------------------
    database_url: PostgresDsn = Field(
        description="async DSN, e.g. postgresql+asyncpg://user:pw@host:5432/vaanios",
    )
    database_pool_size: int = 10
    database_max_overflow: int = 5
    redis_url: RedisDsn = Field()

    # --- Auth ---------------------------------------------------------------
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_seconds: int = 30 * 24 * 3600

    # Argon2id parameters. Defaults follow OWASP's guidance (>=19 MiB, t=2, p=1); tests lower
    # them via env so the suite is not dominated by KDF time.
    argon2_time_cost: int = 2
    argon2_memory_cost_kib: int = 19456
    argon2_parallelism: int = 1

    # --- Rate limiting (SECURITY.md §4) -------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_anonymous_per_min: int = 10
    rate_limit_authenticated_per_min: int = 60
    rate_limit_ai_per_min: int = 6
    rate_limit_voice_minutes_per_day: int = 60

    # --- Cost guard (Gate 0 finding M-11) -----------------------------------
    # Unset means no cap is enforced. The application says so at startup rather than implying
    # a limit exists; it never invents one.
    monthly_spend_cap_usd: float | None = None

    # --- HTTP ---------------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:3000"]
    request_timeout_seconds: int = 30

    # --- Observability ------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True
    # Full transcripts at INFO would put student speech in every log line (SECURITY.md §5).
    log_transcripts: bool = False

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @model_validator(mode="after")
    def _production_hardening(self) -> "Settings":
        if self.environment != "production":
            return self
        if self.debug:
            raise ValueError("debug must be off in production")
        if "*" in self.cors_origins:
            raise ValueError("wildcard CORS origin is not allowed in production")
        if self.log_transcripts:
            raise ValueError("log_transcripts must be off in production")
        if not self.rate_limit_enabled:
            raise ValueError("rate limiting cannot be disabled in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
