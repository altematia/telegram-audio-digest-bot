from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage
from aiogram.methods.base import TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    Message,
    MessageEntity,
    Update,
    User,
    Voice,
)

from app.bot import create_dispatcher
from app.config import Settings
from app.database import Database


OWNER_ID = 101
ATTACKER_ID = 202
CHAT_ID = 303
CLAIM_SECRET = "correct-claim-secret"


def make_settings(database_path: Path) -> Settings:
    return Settings(
        telegram_bot_token="123456:test-token",
        openai_api_key="test-openai-key",
        bot_claim_secret=CLAIM_SECRET,
        telegram_proxy_url=None,
        transcribe_model="gpt-transcribe",
        summary_model="gpt-5.6-terra",
        database_path=database_path,
        max_file_size_mb=20,
        retention_days=30,
        openai_timeout_seconds=240,
        ffmpeg_bin="ffmpeg",
        log_level="INFO",
        max_concurrent_updates=4,
        allowed_user_ids=frozenset(),
    )


def make_database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "bot.sqlite3")
    database.initialize()
    return database


def make_openai_service(*, summary: str = "Готовая выжимка") -> SimpleNamespace:
    return SimpleNamespace(
        transcribe=AsyncMock(return_value="Расшифровка"),
        summarize=AsyncMock(return_value=summary),
    )


class FakeTelegramSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []

    async def close(self) -> None:
        return None

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,
    ) -> Any:
        self.requests.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message(
                message_id=999 + len(self.requests),
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id), type="private"),
                from_user=User(id=123456, is_bot=True, first_name="Test bot"),
                text=method.text,
            ).as_(bot)
        return True

    async def stream_content(
        self,
        url: str,
        headers: dict[str, Any] | None = None,
        timeout: int = 30,
        chunk_size: int = 65_536,
        raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        if False:
            yield b""


def make_bot() -> Bot:
    return Bot("123456:test-token", session=FakeTelegramSession())


def telegram_requests(bot: Bot, request_type: type[Any]) -> list[Any]:
    assert isinstance(bot.session, FakeTelegramSession)
    return [
        request for request in bot.session.requests if isinstance(request, request_type)
    ]


def user(user_id: int) -> User:
    return User(id=user_id, is_bot=False, first_name=f"User {user_id}")


def text_update(update_id: int, user_id: int, text: str) -> Update:
    command = text.split(maxsplit=1)[0]
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=CHAT_ID, type="private"),
            from_user=user(user_id),
            text=text,
            entities=[MessageEntity(type="bot_command", offset=0, length=len(command))],
        ),
    )


def voice_update(update_id: int, user_id: int) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=CHAT_ID, type="private"),
            from_user=user(user_id),
            voice=Voice(
                file_id="voice-file-id",
                file_unique_id="voice-file-unique-id",
                duration=1,
                file_size=10,
            ),
        ),
    )


def callback_update(update_id: int, user_id: int, recording_id: int) -> Update:
    callback_message = Message(
        message_id=500,
        date=datetime.now(UTC),
        chat=Chat(id=CHAT_ID, type="private"),
        from_user=User(id=123456, is_bot=True, first_name="Test bot"),
        text="Выберите формат",
    )
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"callback-{update_id}",
            from_user=user(user_id),
            chat_instance="test-chat-instance",
            message=callback_message,
            data=f"digest:{recording_id}:detailed",
        ),
    )


@pytest.mark.asyncio
async def test_start_and_media_do_not_implicitly_claim_owner(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    openai_service = make_openai_service()
    dispatcher = create_dispatcher(
        make_settings(database.path), database, openai_service
    )
    bot = make_bot()

    await dispatcher.feed_update(bot, text_update(1, ATTACKER_ID, "/start"))
    await dispatcher.feed_update(bot, voice_update(2, ATTACKER_ID))

    assert database.get_owner() is None
    openai_service.transcribe.assert_not_awaited()
    openai_service.summarize.assert_not_awaited()
    assert len(telegram_requests(bot, SendMessage)) == 2


@pytest.mark.asyncio
async def test_claim_requires_secret_and_atomically_fixes_one_owner(tmp_path: Path) -> None:
    database = make_database(tmp_path)
    dispatcher = create_dispatcher(
        make_settings(database.path), database, make_openai_service()
    )
    bot = make_bot()

    await dispatcher.feed_update(
        bot, text_update(1, ATTACKER_ID, "/claim definitely-wrong-secret")
    )
    assert database.get_owner() is None

    await asyncio.gather(
        dispatcher.feed_update(
            bot, text_update(2, OWNER_ID, f"/claim {CLAIM_SECRET}")
        ),
        dispatcher.feed_update(
            bot, text_update(3, ATTACKER_ID, f"/claim {CLAIM_SECRET}")
        ),
    )

    assert database.get_owner() in {OWNER_ID, ATTACKER_ID}
    responses = [request.text for request in telegram_requests(bot, SendMessage)]
    assert sum("стали владельцем" in response for response in responses) == 1
    assert sum("уже привязан" in response for response in responses) == 1


@pytest.mark.asyncio
async def test_callback_after_access_revocation_does_not_call_openai(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    database.claim_owner(OWNER_ID)
    recording_id = database.add_recording(
        chat_id=CHAT_ID,
        user_id=OWNER_ID,
        source_name="voice.ogg",
        transcript="Секретная расшифровка",
    )
    openai_service = make_openai_service()
    dispatcher = create_dispatcher(
        make_settings(database.path), database, openai_service
    )
    bot = make_bot()

    with database._connect() as connection:
        connection.execute("DELETE FROM app_settings WHERE key = 'owner_user_id'")
    await dispatcher.feed_update(bot, callback_update(1, OWNER_ID, recording_id))

    openai_service.summarize.assert_not_awaited()
    callback_answers = telegram_requests(bot, AnswerCallbackQuery)
    assert len(callback_answers) == 1
    assert callback_answers[0].show_alert is True


@pytest.mark.asyncio
async def test_parallel_identical_callbacks_share_one_summary_request(
    tmp_path: Path,
) -> None:
    database = make_database(tmp_path)
    database.claim_owner(OWNER_ID)
    recording_id = database.add_recording(
        chat_id=CHAT_ID,
        user_id=OWNER_ID,
        source_name="voice.ogg",
        transcript="Расшифровка встречи",
    )
    summarize_started = asyncio.Event()
    allow_summary_to_finish = asyncio.Event()

    async def slow_summary(*args: object) -> str:
        summarize_started.set()
        await allow_summary_to_finish.wait()
        return "Единственная выжимка"

    openai_service = make_openai_service()
    openai_service.summarize.side_effect = slow_summary
    dispatcher = create_dispatcher(
        make_settings(database.path), database, openai_service
    )
    bot = make_bot()

    first = asyncio.create_task(
        dispatcher.feed_update(bot, callback_update(1, OWNER_ID, recording_id))
    )
    await asyncio.wait_for(summarize_started.wait(), timeout=1)
    second = asyncio.create_task(
        dispatcher.feed_update(bot, callback_update(2, OWNER_ID, recording_id))
    )
    await asyncio.sleep(0)
    allow_summary_to_finish.set()
    await asyncio.gather(first, second)

    openai_service.summarize.assert_awaited_once_with(
        "Расшифровка встречи", "detailed", OWNER_ID
    )
    assert database.get_output(recording_id, "detailed") == "Единственная выжимка"
