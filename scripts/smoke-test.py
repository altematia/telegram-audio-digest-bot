#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from dotenv import load_dotenv
from openai import AsyncOpenAI

from app.config import Settings
from app.media import prepare_for_openai


def _silent_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x00\x00" * 8_000)


async def main(openai_only: bool = False) -> None:
    load_dotenv()
    settings = Settings.from_env()
    result: dict[str, str] = {}

    if not openai_only:
        session = AiohttpSession(proxy=settings.telegram_proxy_url)
        bot = Bot(settings.telegram_bot_token, session=session)
        try:
            me = await bot.get_me()
            result["telegram"] = f"ok:@{me.username}"
        finally:
            await bot.session.close()

    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
    )
    response = await client.responses.create(
        model=settings.summary_model,
        input="Ответь одним словом: работает",
        reasoning={"effort": "low"},
        max_output_tokens=40,
        safety_identifier="deployment-smoke-test",
        store=False,
    )
    result["summary"] = "ok" if response.output_text.strip() else "empty"

    with tempfile.TemporaryDirectory(prefix="audio-smoke-") as temp_dir:
        wav_path = Path(temp_dir) / "silence.wav"
        ogg_path = Path(temp_dir) / "voice.ogg"
        _silent_wav(wav_path)
        if shutil.which(settings.ffmpeg_bin):
            subprocess.run(
                [
                    settings.ffmpeg_bin,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(wav_path),
                    "-c:a",
                    "libopus",
                    str(ogg_path),
                ],
                check=True,
            )
            prepared = await prepare_for_openai(ogg_path, settings.ffmpeg_bin)
            if prepared.suffix != ".webm" or not prepared.is_file():
                raise RuntimeError("Telegram OGG was not converted to WebM")
            result["voice_conversion"] = "ok"
        elif openai_only:
            prepared = wav_path
            result["voice_conversion"] = "skipped:no-local-ffmpeg"
        else:
            raise RuntimeError("ffmpeg is required for the deployment smoke test")
        with prepared.open("rb") as audio_file:
            await client.audio.transcriptions.create(
                model=settings.transcribe_model,
                file=audio_file,
            )
    result["transcription"] = "ok"

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--openai-only", action="store_true", help="Skip Telegram connectivity check"
    )
    arguments = parser.parse_args()
    asyncio.run(main(openai_only=arguments.openai_only))
