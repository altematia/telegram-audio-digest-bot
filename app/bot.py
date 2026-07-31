from __future__ import annotations

import asyncio
import hmac
import logging
import tempfile
from contextlib import suppress
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.config import Settings
from app.database import Database, Recording
from app.media import MediaConversionError, extract_media, prepare_for_openai
from app.openai_service import FORMAT_PROMPTS, FORMAT_TITLES, OpenAIService
from app.text import split_text


logger = logging.getLogger(__name__)


def recording_keyboard(recording_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚡ Кратко", callback_data=f"digest:{recording_id}:short"
                ),
                InlineKeyboardButton(
                    text="🧠 Подробно", callback_data=f"digest:{recording_id}:detailed"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📌 Тезисы", callback_data=f"digest:{recording_id}:bullets"
                ),
                InlineKeyboardButton(
                    text="✅ Задачи", callback_data=f"digest:{recording_id}:actions"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📝 Полный текст", callback_data=f"digest:{recording_id}:transcript"
                )
            ],
        ]
    )


async def _send_text(message: Message, title: str, content: str) -> None:
    chunks = split_text(f"{title}\n\n{content}")
    for chunk in chunks:
        await message.answer(chunk)


async def _send_transcript(message: Message, recording: Recording) -> None:
    if len(recording.transcript) <= 11_000:
        await _send_text(message, FORMAT_TITLES["transcript"], recording.transcript)
        return

    payload = recording.transcript.encode("utf-8")
    safe_stem = Path(recording.source_name).stem[:80] or "transcript"
    document = BufferedInputFile(payload, filename=f"{safe_stem}-transcript.txt")
    await message.answer_document(
        document,
        caption="📝 Полная расшифровка — в TXT, потому что она длиннее лимита сообщений Telegram.",
    )


def create_dispatcher(
    settings: Settings, database: Database, openai_service: OpenAIService
) -> Dispatcher:
    dispatcher = Dispatcher()
    router = Router()
    format_locks: dict[tuple[int, str], asyncio.Lock] = {}

    def user_is_allowed(user_id: int) -> bool:
        if settings.allowed_user_ids:
            return settings.user_is_allowed(user_id)
        owner_id = database.get_owner()
        return owner_id == user_id

    @router.message(Command("claim"))
    async def claim(message: Message) -> None:
        if message.from_user is None:
            return
        with suppress(Exception):
            await message.delete()
        if settings.allowed_user_ids or settings.bot_claim_secret is None:
            await message.answer("Привязка владельца для этого бота отключена.")
            return
        supplied = (message.text or "").partition(" ")[2].strip()
        if not hmac.compare_digest(supplied, settings.bot_claim_secret):
            await message.answer("Неверный код привязки.")
            return
        owner_id = database.claim_owner(message.from_user.id)
        if owner_id != message.from_user.id:
            await message.answer("Бот уже привязан к другому владельцу.")
            return
        logger.info("Bot ownership claimed by Telegram user %s", owner_id)
        await message.answer("Готово: вы стали владельцем бота. Теперь пришлите запись.")

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        if message.from_user is None or not user_is_allowed(message.from_user.id):
            await message.answer("У этого аккаунта нет доступа к боту.")
            return
        await message.answer(
            "Пришлите или перешлите голосовое сообщение, аудио либо MP3/MP4-файл до "
            f"{settings.max_file_size_mb} МБ. Я расшифрую запись, сразу дам краткую "
            "выжимку и добавлю кнопки для других форматов."
        )

    @router.message(Command("privacy"))
    async def privacy(message: Message) -> None:
        if message.from_user is None or not user_is_allowed(message.from_user.id):
            await message.answer("У этого аккаунта нет доступа к боту.")
            return
        await message.answer(
            "Аудиофайлы хранятся на сервере только во временной директории и удаляются "
            "сразу после обработки. Аудио и текст передаются в OpenAI для распознавания "
            f"и выжимки. Расшифровки и результаты хранятся на сервере {settings.retention_days} "
            "дней, чтобы работали кнопки под сообщением."
        )

    @router.message(F.voice | F.audio | F.video | F.document)
    async def process_media(message: Message, bot: Bot) -> None:
        if message.from_user is None or not user_is_allowed(message.from_user.id):
            await message.answer("У этого аккаунта нет доступа к боту.")
            return

        media = extract_media(message)
        if media is None:
            await message.answer(
                "Не вижу поддерживаемого аудио. Пришлите голосовое, MP3, MP4, M4A, WAV или WebM."
            )
            return
        if media.file_size and media.file_size > settings.max_file_size_bytes:
            await message.answer(
                f"Файл больше {settings.max_file_size_mb} МБ — Telegram Bot API не даст мне его скачать."
            )
            return

        status = await message.answer("⏳ Скачиваю и расшифровываю запись…")
        recording_id: int | None = None
        try:
            with tempfile.TemporaryDirectory(prefix="telegram-audio-") as temp_dir:
                source = Path(temp_dir) / f"input{media.extension}"
                await bot.download(media.file_id, destination=source)
                if source.stat().st_size > settings.max_file_size_bytes:
                    await status.edit_text(
                        f"Файл больше {settings.max_file_size_mb} МБ и не может быть обработан."
                    )
                    return
                prepared = await prepare_for_openai(source, settings.ffmpeg_bin)
                transcript = await openai_service.transcribe(prepared)

            recording_id = database.add_recording(
                chat_id=message.chat.id,
                user_id=message.from_user.id,
                source_name=media.file_name,
                transcript=transcript,
            )
            database.purge_older_than(settings.retention_days)
            try:
                summary = await openai_service.summarize(
                    transcript, "short", message.from_user.id
                )
                database.save_output(recording_id, "short", summary)
                await status.edit_text(
                    f"{FORMAT_TITLES['short']}\n\n{summary}\n\nВыберите другой формат:",
                    reply_markup=recording_keyboard(recording_id),
                )
            except Exception:
                logger.exception("Initial summary failed for recording %s", recording_id)
                await status.edit_text(
                    "✅ Расшифровка готова, но краткую выжимку сейчас получить не удалось. "
                    "Можно открыть полный текст или повторить выжимку кнопкой ниже.",
                    reply_markup=recording_keyboard(recording_id),
                )
        except MediaConversionError:
            logger.exception("Audio conversion failed")
            await status.edit_text("Не получилось подготовить голосовое сообщение к распознаванию.")
        except Exception:
            logger.exception("Media processing failed")
            await status.edit_text(
                "Не получилось обработать запись. Проверьте формат и попробуйте ещё раз чуть позже."
            )

    @router.callback_query(F.data.startswith("digest:"))
    async def format_callback(callback: CallbackQuery) -> None:
        if callback.from_user is None or callback.message is None or not callback.data:
            await callback.answer()
            return

        if not user_is_allowed(callback.from_user.id):
            await callback.answer("У этого аккаунта нет доступа к боту", show_alert=True)
            return

        try:
            _, raw_id, format_key = callback.data.split(":", 2)
            recording_id = int(raw_id)
        except (TypeError, ValueError):
            await callback.answer("Некорректная кнопка", show_alert=True)
            return

        database.purge_older_than(settings.retention_days)
        recording = database.get_recording(recording_id)
        if (
            recording is None
            or recording.user_id != callback.from_user.id
            or recording.chat_id != callback.message.chat.id
        ):
            await callback.answer("Эта расшифровка недоступна", show_alert=True)
            return

        if format_key == "transcript":
            await callback.answer("Отправляю полный текст…")
            await _send_transcript(callback.message, recording)
            return
        if format_key not in FORMAT_PROMPTS:
            await callback.answer("Неизвестный формат", show_alert=True)
            return

        await callback.answer("Готовлю формат…")
        progress = await callback.message.answer("⏳ Готовлю выбранный формат…")
        try:
            lock = format_locks.setdefault((recording_id, format_key), asyncio.Lock())
            async with lock:
                content = database.get_output(recording_id, format_key)
                if content is None:
                    content = await openai_service.summarize(
                        recording.transcript, format_key, callback.from_user.id
                    )
                    database.save_output(recording_id, format_key, content)

            chunks = split_text(f"{FORMAT_TITLES[format_key]}\n\n{content}")
            if not chunks:
                raise RuntimeError("empty formatted output")
            await progress.edit_text(chunks[0])
            for chunk in chunks[1:]:
                await callback.message.answer(chunk)
        except Exception:
            logger.exception("Requested summary failed for recording %s", recording_id)
            await progress.edit_text("Не удалось подготовить этот формат. Попробуйте ещё раз позже.")

    @router.message()
    async def unsupported(message: Message) -> None:
        if message.from_user is None or not user_is_allowed(message.from_user.id):
            await message.answer("У этого аккаунта нет доступа к боту.")
            return
        await message.answer(
            "Пришлите голосовое сообщение или поддерживаемый аудио/MP4-файл. Команда /start покажет подсказку."
        )

    dispatcher.include_router(router)
    return dispatcher
