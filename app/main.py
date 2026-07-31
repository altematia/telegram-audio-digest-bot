from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from dotenv import load_dotenv

from app.bot import create_dispatcher
from app.config import Settings
from app.database import Database
from app.openai_service import OpenAIService


async def run() -> None:
    load_dotenv()
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger = logging.getLogger(__name__)

    database = Database(settings.database_path)
    database.initialize()
    purged = database.purge_older_than(settings.retention_days)
    if purged:
        logger.info("Purged %s expired recordings", purged)

    session = AiohttpSession(
        proxy=settings.telegram_proxy_url,
        limit=settings.max_concurrent_updates + 2,
    )
    bot = Bot(token=settings.telegram_bot_token, session=session)
    dispatcher = create_dispatcher(settings, database, OpenAIService(settings))
    me = await bot.get_me()
    logger.info("Starting long polling for @%s", me.username)
    await bot.delete_webhook(drop_pending_updates=False)

    async def purge_periodically() -> None:
        while True:
            await asyncio.sleep(6 * 60 * 60)
            removed = database.purge_older_than(settings.retention_days)
            if removed:
                logger.info("Purged %s expired recordings", removed)

    purge_task = asyncio.create_task(purge_periodically())
    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
            tasks_concurrency_limit=settings.max_concurrent_updates,
        )
    finally:
        purge_task.cancel()
        with suppress(asyncio.CancelledError):
            await purge_task
        await bot.session.close()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
