from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    """Raised when required runtime configuration is missing or invalid."""


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Environment variable {name} is required")
    return value


def _positive_int(name: str, default: int, maximum: int | None = None) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"Environment variable {name} must be an integer") from exc
    if value <= 0 or (maximum is not None and value > maximum):
        suffix = f" and at most {maximum}" if maximum is not None else ""
        raise ConfigError(f"Environment variable {name} must be positive{suffix}")
    return value


def _user_ids() -> frozenset[int]:
    raw = os.getenv("ALLOWED_USER_IDS", "").strip()
    if not raw:
        return frozenset()
    try:
        return frozenset(int(item.strip()) for item in raw.split(",") if item.strip())
    except ValueError as exc:
        raise ConfigError("ALLOWED_USER_IDS must be a comma-separated list of integers") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str = field(repr=False)
    openai_api_key: str = field(repr=False)
    bot_claim_secret: str | None = field(repr=False)
    telegram_proxy_url: str | None
    transcribe_model: str
    summary_model: str
    database_path: Path
    max_file_size_mb: int
    retention_days: int
    openai_timeout_seconds: int
    ffmpeg_bin: str
    log_level: str
    max_concurrent_updates: int
    allowed_user_ids: frozenset[int]

    @classmethod
    def from_env(cls) -> "Settings":
        allowed_user_ids = _user_ids()
        claim_secret = os.getenv("BOT_CLAIM_SECRET", "").strip() or None
        if not allowed_user_ids and (claim_secret is None or len(claim_secret) < 16):
            raise ConfigError(
                "Set ALLOWED_USER_IDS or a BOT_CLAIM_SECRET of at least 16 characters"
            )
        return cls(
            telegram_bot_token=_required_env("TELEGRAM_BOT_TOKEN"),
            openai_api_key=_required_env("OPENAI_API_KEY"),
            bot_claim_secret=claim_secret,
            telegram_proxy_url=os.getenv("TELEGRAM_PROXY_URL", "").strip() or None,
            transcribe_model=os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-transcribe").strip(),
            summary_model=os.getenv("OPENAI_SUMMARY_MODEL", "gpt-5.6-terra").strip(),
            database_path=Path(os.getenv("DATABASE_PATH", "data/bot.sqlite3")).expanduser(),
            max_file_size_mb=_positive_int("MAX_FILE_SIZE_MB", 20, maximum=20),
            retention_days=_positive_int("TRANSCRIPT_RETENTION_DAYS", 30),
            openai_timeout_seconds=_positive_int("OPENAI_TIMEOUT_SECONDS", 240),
            ffmpeg_bin=os.getenv("FFMPEG_BIN", "ffmpeg").strip() or "ffmpeg",
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
            max_concurrent_updates=_positive_int(
                "MAX_CONCURRENT_UPDATES", 4, maximum=16
            ),
            allowed_user_ids=allowed_user_ids,
        )

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    def user_is_allowed(self, user_id: int) -> bool:
        return user_id in self.allowed_user_ids
