from pathlib import Path

import pytest

from app.config import ConfigError, Settings


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-test")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test")
    monkeypatch.setenv("ALLOWED_USER_IDS", "12, 34")
    monkeypatch.setenv("DATABASE_PATH", "tmp/test.sqlite3")

    settings = Settings.from_env()

    assert settings.transcribe_model == "gpt-transcribe"
    assert settings.summary_model == "gpt-5.6-terra"
    assert settings.database_path == Path("tmp/test.sqlite3")
    assert settings.allowed_user_ids == frozenset({12, 34})
    assert settings.bot_claim_secret is None
    assert settings.openai_proxy_url is None
    assert settings.max_concurrent_updates == 4
    assert settings.user_is_allowed(12)
    assert not settings.user_is_allowed(56)


def test_file_limit_cannot_exceed_telegram_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-test")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test")
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "21")

    with pytest.raises(ConfigError):
        Settings.from_env()


def test_requires_explicit_access_control(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-test")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test")
    monkeypatch.delenv("ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("BOT_CLAIM_SECRET", raising=False)

    with pytest.raises(ConfigError, match="ALLOWED_USER_IDS"):
        Settings.from_env()


def test_accepts_long_claim_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-test")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test")
    monkeypatch.delenv("ALLOWED_USER_IDS", raising=False)
    monkeypatch.setenv("BOT_CLAIM_SECRET", "a-very-long-claim-secret")

    settings = Settings.from_env()

    assert settings.bot_claim_secret == "a-very-long-claim-secret"
