from __future__ import annotations


def split_text(text: str, limit: int = 3900) -> list[str]:
    """Split Telegram text at natural boundaries without losing content."""
    remaining = text.strip()
    if not remaining:
        return []

    chunks: list[str] = []
    while len(remaining) > limit:
        cut = remaining.rfind("\n\n", 0, limit + 1)
        if cut < limit // 2:
            cut = remaining.rfind("\n", 0, limit + 1)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit + 1)
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks
