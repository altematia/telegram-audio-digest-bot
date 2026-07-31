from app.text import split_text


def test_short_text_is_unchanged() -> None:
    assert split_text("Короткий текст") == ["Короткий текст"]


def test_long_text_respects_limit_and_preserves_words() -> None:
    text = " ".join(f"слово{i}" for i in range(100))
    chunks = split_text(text, limit=80)

    assert len(chunks) > 1
    assert all(len(chunk) <= 80 for chunk in chunks)
    assert " ".join(chunks) == text
