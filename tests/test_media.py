from types import SimpleNamespace

from app.media import extract_media


def message(**kwargs):
    defaults = {"voice": None, "audio": None, "video": None, "document": None}
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_extracts_telegram_voice_as_ogg() -> None:
    voice = SimpleNamespace(file_id="voice-id", file_size=123)
    result = extract_media(message(voice=voice))

    assert result is not None
    assert result.extension == ".ogg"
    assert result.file_name == "voice.ogg"


def test_accepts_mp3_document() -> None:
    document = SimpleNamespace(
        file_id="doc-id", file_size=456, file_name="Meeting.MP3", mime_type="audio/mpeg"
    )
    result = extract_media(message(document=document))

    assert result is not None
    assert result.extension == ".mp3"
    assert result.file_name == "Meeting.MP3"


def test_accepts_mp4_video() -> None:
    video = SimpleNamespace(
        file_id="video-id", file_size=789, file_name="clip.mp4", mime_type="video/mp4"
    )
    result = extract_media(message(video=video))

    assert result is not None
    assert result.extension == ".mp4"


def test_rejects_unrelated_document() -> None:
    document = SimpleNamespace(
        file_id="pdf-id", file_size=12, file_name="notes.pdf", mime_type="application/pdf"
    )
    assert extract_media(message(document=document)) is None
