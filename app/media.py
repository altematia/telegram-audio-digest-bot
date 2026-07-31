from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


OPENAI_EXTENSIONS = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm"}
CONVERT_EXTENSIONS = {".ogg", ".oga", ".opus"}
ACCEPTED_EXTENSIONS = OPENAI_EXTENSIONS | CONVERT_EXTENSIONS

MIME_EXTENSIONS = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "video/mp4": ".mp4",
    "audio/x-m4a": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "video/webm": ".webm",
    "audio/ogg": ".ogg",
    "application/ogg": ".ogg",
}


class MediaConversionError(RuntimeError):
    """Raised when Telegram OGG/Opus cannot be converted for OpenAI."""


@dataclass(frozen=True, slots=True)
class IncomingMedia:
    file_id: str
    file_size: int
    file_name: str
    extension: str


def _safe_name(name: str) -> str:
    base = Path(name).name.strip() or "audio"
    return re.sub(r"[^\w.()\- ]+", "_", base, flags=re.UNICODE)[:160]


def _extension(file_name: str | None, mime_type: str | None, default: str) -> str:
    suffix = Path(file_name or "").suffix.lower()
    if suffix in ACCEPTED_EXTENSIONS:
        return suffix
    return MIME_EXTENSIONS.get((mime_type or "").lower(), default)


def extract_media(message: Any) -> IncomingMedia | None:
    """Return supported Telegram media metadata without downloading the file."""
    if getattr(message, "voice", None) is not None:
        item = message.voice
        return IncomingMedia(
            file_id=item.file_id,
            file_size=int(item.file_size or 0),
            file_name="voice.ogg",
            extension=".ogg",
        )

    candidates = (
        (getattr(message, "audio", None), ".mp3", "audio"),
        (getattr(message, "video", None), ".mp4", "video"),
        (getattr(message, "document", None), "", "file"),
    )
    for item, default_extension, fallback_name in candidates:
        if item is None:
            continue
        file_name = getattr(item, "file_name", None)
        mime_type = getattr(item, "mime_type", None)
        extension = _extension(file_name, mime_type, default_extension)
        if extension not in ACCEPTED_EXTENSIONS:
            return None
        display_name = _safe_name(file_name or f"{fallback_name}{extension}")
        return IncomingMedia(
            file_id=item.file_id,
            file_size=int(getattr(item, "file_size", 0) or 0),
            file_name=display_name,
            extension=extension,
        )
    return None


async def _ffmpeg(command: list[str]) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
    except TimeoutError:
        process.kill()
        await process.communicate()
        return 124, "conversion timed out"
    return process.returncode or 0, stderr.decode("utf-8", errors="replace")[-1200:]


async def prepare_for_openai(source: Path, ffmpeg_bin: str) -> Path:
    """Convert only Telegram-specific OGG/Opus inputs; supported files pass through."""
    if source.suffix.lower() in OPENAI_EXTENSIONS:
        return source
    if source.suffix.lower() not in CONVERT_EXTENSIONS:
        raise MediaConversionError("unsupported audio format")

    output = source.with_suffix(".webm")
    common = [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-vn"]

    code, error = await _ffmpeg([*common, "-c:a", "copy", str(output)])
    if code == 0 and output.exists() and output.stat().st_size > 0:
        return output

    code, transcode_error = await _ffmpeg(
        [*common, "-c:a", "libopus", "-b:a", "48k", str(output)]
    )
    if code != 0 or not output.exists() or output.stat().st_size == 0:
        details = transcode_error or error or "unknown ffmpeg error"
        raise MediaConversionError(f"ffmpeg failed: {details}")
    return output
