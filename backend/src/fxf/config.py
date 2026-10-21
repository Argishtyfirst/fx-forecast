"""Runtime settings. Secrets come from the environment only (NFR-06)."""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


def normalize_database_url(url: str) -> str:
    """Use the psycopg 3 driver for any Postgres URL.

    Hosted providers (Neon via the Vercel Marketplace, Supabase) hand out postgres:// or
    postgresql:// URLs, which SQLAlchemy would map to psycopg2, which is not installed.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_DIR / ".env"), str(BACKEND_DIR / ".env")),
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://fxf:fxf@localhost:5433/fxf"

    fred_api_key: str | None = None
    anthropic_api_key: str | None = None
    fxf_scorer_model: str = "claude-haiku-5-5"
    # The experimental AI view (fxf.ai). Off unless GEMINI_API_KEY is set.
    gemini_api_key: str | None = None
    fxf_ai_model: str = "gemini-3.8-flash"
    # Used for the day when the main model is rate limited or overloaded.
    fxf_ai_fallback_model: str = "gemini-3.5-flash-lite"
    # Statement tone scoring is a simple task; flash-lite has its own, larger free quota and
    # leaves the AI view's model quota for the daily forecasts.
    fxf_scorer_gemini_model: str = "gemini-3.5-flash-lite"
    # Thinking depth for the AI view ("low" | "medium" | "high"); empty uses the model default.
    fxf_ai_thinking: str = "high"

    slack_webhook_url: str | None = None
    alert_email_to: str | None = None
    smtp_url: str | None = None

    fxf_raw_dir: Path = BACKEND_DIR / "var" / "raw"
    raw_retention_days: int = 30

    http_timeout_s: float = 30.0
    http_retries: int = 3
    http_backoff_base_s: float = 1.0
    user_agent: str = "fxf/0.1 (FX forecast research tool)"

    git_sha: str | None = None
    # Set by Vercel and GitHub Actions; used when GIT_SHA is not.
    vercel_git_commit_sha: str | None = None
    github_sha: str | None = None
    random_seed: int = 7

    # Market timezone for "working day" and the 17:00 / 18:00 CET rules.
    market_tz: str = "Europe/Berlin"

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        return normalize_database_url(v)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def git_sha() -> str:
    s = get_settings()
    for sha in (s.git_sha, s.vercel_git_commit_sha, s.github_sha):
        if sha:
            return sha[:12]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return out.stdout.strip() or "dev"
    except Exception:
        return "dev"
